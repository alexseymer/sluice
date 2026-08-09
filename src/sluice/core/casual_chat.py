"""Always-on conversational chat outside jour fixe sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog

from sluice.adapters.backend import BackendAdapter
from sluice.adapters.chat import ChatAdapter, IncomingMessage, OutgoingMessage
from sluice.core.jour_fixe import ConversationTurn
from sluice.core.jour_fixe_chat import (
    NO_BACKEND_REPLY,
    ChatMode,
    facilitate_turn,
)

log = structlog.get_logger()

_MAX_TURNS = 40


@dataclass
class CasualChatManager:
    """Natural ask-mode chat when no jour fixe session is active."""

    chat: ChatAdapter
    conversation_backend: BackendAdapter | None
    worktree_base: Path
    turns: list[ConversationTurn] = field(default_factory=list)

    def _recent_turns(self) -> list[tuple[str, str]]:
        recent = self.turns[-_MAX_TURNS:]
        return [(t.role, t.text) for t in recent]

    async def handle_message(self, message: IncomingMessage) -> None:
        text = message.text.strip()
        if not text:
            return

        self.turns.append(ConversationTurn(role="human", text=text))

        if self.conversation_backend is None:
            await self.chat.send(OutgoingMessage(text=NO_BACKEND_REPLY))
            return

        worktree = self.worktree_base / "chat"
        try:
            reply, error = await facilitate_turn(
                turns=self._recent_turns(),
                latest_human=text,
                worktree=worktree,
                backend=self.conversation_backend,
                mode=ChatMode.CASUAL,
            )
        except Exception:
            log.exception("casual_chat_facilitate_failed")
            await self.chat.send(
                OutgoingMessage(
                    text=(
                        "Something went wrong while thinking that through. "
                        "Try again in a moment."
                    )
                )
            )
            return

        if error and not reply:
            await self.chat.send(OutgoingMessage(text=error))
            return
        if reply is None:
            await self.chat.send(
                OutgoingMessage(
                    text="I couldn't get a reply just now — try again in a moment."
                )
            )
            return

        self.turns.append(
            ConversationTurn(role="assistant", text=reply, at=datetime.now(UTC))
        )
        await self.chat.send(OutgoingMessage(text=reply))
        log.info("casual_chat_replied", reply_chars=len(reply))
