"""Tests for casual chat outside jour fixe sessions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from sluice.adapters.chat import IncomingMessage
from sluice.core.casual_chat import CasualChatManager
from sluice.core.jour_fixe_chat import ChatMode, facilitate_turn
from sluice.models.schedule import DispatchResult


@pytest.mark.asyncio
async def test_facilitate_turn_casual_mode_uses_casual_prompt(tmp_path: Path) -> None:
    backend = AsyncMock()
    backend.dispatch = AsyncMock(
        return_value=DispatchResult(
            task_id=uuid4(),
            backend_id="cursor",
            success=True,
            output="Sure — what part of auth is giving you trouble?",
        )
    )
    reply, error = await facilitate_turn(
        backend=backend,
        turns=[("human", "How should I approach auth?")],
        latest_human="How should I approach auth?",
        worktree=tmp_path / "chat",
        mode=ChatMode.CASUAL,
    )
    assert error is None
    assert reply is not None
    prompt = backend.dispatch.await_args.kwargs["worktree"]
    assert prompt == tmp_path / "chat"
    task = backend.dispatch.await_args.args[0]
    assert "ask mode" in task.description.lower() or "normal chat" in task.description.lower()


@pytest.mark.asyncio
async def test_casual_chat_replies_via_backend(tmp_path: Path) -> None:
    chat = AsyncMock()
    chat.send = AsyncMock()
    backend = AsyncMock()
    backend.dispatch = AsyncMock(
        return_value=DispatchResult(
            task_id=uuid4(),
            backend_id="cursor",
            success=True,
            output="OAuth is usually the right default for a solo builder app.",
        )
    )
    manager = CasualChatManager(
        chat=chat,
        conversation_backend=backend,
        worktree_base=tmp_path,
    )

    await manager.handle_message(
        IncomingMessage(text="Should I use OAuth?", sender="@you:example.com")
    )

    sent = [call.args[0].text for call in chat.send.await_args_list]
    assert any("oauth" in text.lower() for text in sent)
    assert len(manager.turns) == 2


@pytest.mark.asyncio
async def test_casual_chat_without_backend_explains(tmp_path: Path) -> None:
    chat = AsyncMock()
    chat.send = AsyncMock()
    manager = CasualChatManager(
        chat=chat,
        conversation_backend=None,
        worktree_base=tmp_path,
    )

    await manager.handle_message(
        IncomingMessage(text="Hello", sender="@you:example.com")
    )

    text = chat.send.await_args.args[0].text
    assert "/cli-auth" in text or "SLUICE_AI_BACKENDS" in text
