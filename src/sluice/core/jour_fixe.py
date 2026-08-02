"""Jour fixe session manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import structlog
from croniter import croniter

from sluice.adapters.backend import BackendAdapter
from sluice.adapters.chat import ChatAdapter, IncomingMessage, OutgoingMessage
from sluice.core.jour_fixe_chat import (
    NO_BACKEND_REPLY,
    JourFixeLlmSettings,
    facilitate_turn,
)
from sluice.core.planner import Planner
from sluice.models.plan import Plan

log = structlog.get_logger()

ConversationRole = Literal["human", "assistant"]


@dataclass
class ConversationTurn:
    role: ConversationRole
    text: str
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class JourFixeSession:
    id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    messages: list[IncomingMessage] = field(default_factory=list)
    turns: list[ConversationTurn] = field(default_factory=list)
    plan: Plan | None = None

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    def elapsed_seconds(self, *, now: datetime | None = None) -> float:
        current = now or datetime.now(UTC)
        return (current - self.started_at).total_seconds()

    def transcript_lines(self) -> list[str]:
        lines: list[str] = []
        for turn in self.turns:
            label = "Human" if turn.role == "human" else "Assistant"
            lines.append(f"{label}: {turn.text}")
        return lines


class JourFixeManager:
    """Manages recurring jour fixe sessions and the planning flow."""

    def __init__(
        self,
        chat: ChatAdapter,
        planner: Planner,
        cron_expression: str,
        timeout_minutes: int = 60,
        *,
        conversation_backend: BackendAdapter | None = None,
        worktree_base: Path | None = None,
        llm: JourFixeLlmSettings | None = None,
    ) -> None:
        self._chat = chat
        self._planner = planner
        self._cron_expression = cron_expression
        self._timeout_minutes = timeout_minutes
        self._conversation_backend = conversation_backend
        self._worktree_base = worktree_base or Path(".sluice-data/planner")
        self._llm = llm or JourFixeLlmSettings()
        self._session: JourFixeSession | None = None

    @property
    def active_session(self) -> JourFixeSession | None:
        return self._session

    def next_scheduled_at(self, *, after: datetime | None = None) -> datetime:
        """Return the next cron fire time as timezone-aware UTC.

        Builds a fresh croniter each call so logging/peeking does not advance
        a shared iterator past the real next session.
        """
        base = after or datetime.now(UTC)
        base = base.replace(tzinfo=UTC) if base.tzinfo is None else base.astimezone(UTC)
        return croniter(self._cron_expression, base).get_next(datetime)

    def is_session_timed_out(self, *, now: datetime | None = None) -> bool:
        if self._session is None or not self._session.is_active:
            return False
        return self._session.elapsed_seconds(now=now) >= self._timeout_minutes * 60

    def can_start_scheduled_session(self, *, has_pending_plan: bool) -> bool:
        if has_pending_plan:
            return False
        return self._session is None or not self._session.is_active

    async def start_session(self) -> JourFixeSession:
        self._session = JourFixeSession()
        await self._chat.start_jour_fixe_prompt()
        return self._session

    async def handle_message(self, message: IncomingMessage) -> None:
        if self._session is None or not self._session.is_active:
            return

        self._session.messages.append(message)
        self._session.turns.append(ConversationTurn(role="human", text=message.text))

        has_llm = self._llm.is_configured
        has_cli = self._conversation_backend is not None
        if not has_llm and not has_cli:
            await self._chat.send(OutgoingMessage(text=NO_BACKEND_REPLY))
            return

        await self._chat.send(OutgoingMessage(text="Thinking…"))
        worktree = self._worktree_base / str(self._session.id) / "chat"
        turns = [(t.role, t.text) for t in self._session.turns]
        try:
            reply, error = await facilitate_turn(
                turns=turns,
                latest_human=message.text,
                worktree=worktree,
                backend=self._conversation_backend,
                llm=self._llm,
            )
        except Exception:
            log.exception("jour_fixe_facilitate_failed", session_id=str(self._session.id))
            await self._chat.send(
                OutgoingMessage(
                    text=(
                        "Something went wrong while thinking that through. "
                        "Try again, or say you're done and I'll draft a plan from notes."
                    )
                )
            )
            return

        if error and not reply:
            await self._chat.send(OutgoingMessage(text=error))
            return
        if reply is None:
            await self._chat.send(
                OutgoingMessage(
                    text=(
                        "I couldn't get a reply just now. "
                        "Say a bit more, or tell me when you're done and I'll draft the plan."
                    )
                )
            )
            return

        self._session.turns.append(ConversationTurn(role="assistant", text=reply))
        await self._chat.send(OutgoingMessage(text=reply))
        log.info(
            "jour_fixe_facilitator_replied",
            session_id=str(self._session.id),
            reply_chars=len(reply),
        )

    async def close_session(self, *, task_descriptions: list[str] | None = None) -> Plan:
        if self._session is None:
            raise RuntimeError("No active jour fixe session")

        descriptions = task_descriptions or self._session.transcript_lines()
        if not descriptions:
            descriptions = [m.text for m in self._session.messages]
        session_id = self._session.id
        plan = await self._planner.generate_plan(
            session_id=str(session_id),
            task_descriptions=descriptions,
        )
        plan.jour_fixe_session_id = session_id
        self._session.plan = plan
        self._session.ended_at = datetime.now(UTC)
        return plan
