"""Tests for jour fixe conversational facilitator helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from sluice.adapters.chat import IncomingMessage
from sluice.core.chat_loop import is_natural_close
from sluice.core.jour_fixe import JourFixeManager
from sluice.core.jour_fixe_chat import (
    JourFixeLlmSettings,
    extract_facilitator_reply,
    facilitate_turn,
    format_transcript,
)
from sluice.models.schedule import DispatchResult


def test_format_transcript_labels_roles() -> None:
    text = format_transcript(
        [("human", "Status is rough"), ("assistant", "What broke?")]
    )
    assert "Human: Status is rough" in text
    assert "Assistant: What broke?" in text


def test_extract_facilitator_reply_prefers_last_block() -> None:
    output = "Prompt echo noise\n\nGot it — let's dig into the deploy failures."
    assert extract_facilitator_reply(output) == "Got it — let's dig into the deploy failures."


def test_natural_close_phrases() -> None:
    assert is_natural_close("done")
    assert is_natural_close("That's all.")
    assert is_natural_close("lets wrap up")
    assert not is_natural_close("not done yet")
    assert not is_natural_close("/approve")


@pytest.mark.asyncio
async def test_facilitate_turn_dispatches_backend(tmp_path: Path) -> None:
    backend = AsyncMock()
    backend.dispatch = AsyncMock(
        return_value=DispatchResult(
            task_id=uuid4(),
            backend_id="cursor",
            success=True,
            output="Sounds like the outage is the main issue. What have you tried?",
        )
    )
    reply, error = await facilitate_turn(
        backend=backend,
        turns=[("human", "Prod keeps falling over")],
        latest_human="Prod keeps falling over",
        worktree=tmp_path / "chat",
    )
    assert error is None
    assert reply is not None
    assert "outage" in reply.lower() or "falling" in reply.lower() or "issue" in reply.lower()
    backend.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_facilitate_turn_cli_missing_hint(tmp_path: Path) -> None:
    backend = AsyncMock()
    backend.dispatch = AsyncMock(
        return_value=DispatchResult(
            task_id=uuid4(),
            backend_id="cursor",
            success=False,
            error="CLI not found: 'agent'",
        )
    )
    reply, error = await facilitate_turn(
        backend=backend,
        turns=[("human", "Hi")],
        latest_human="Hi",
        worktree=tmp_path / "chat",
    )
    assert reply is None
    assert error is not None
    assert "SLUICE_JOUR_FIXE_LLM" in error


@pytest.mark.asyncio
async def test_handle_message_replies_via_backend(tmp_path: Path) -> None:
    chat = AsyncMock()
    chat.send = AsyncMock()
    planner = MagicMock()
    backend = AsyncMock()
    backend.dispatch = AsyncMock(
        return_value=DispatchResult(
            task_id=uuid4(),
            backend_id="cursor",
            success=True,
            output="Tell me more about the regression.",
        )
    )
    manager = JourFixeManager(
        chat=chat,
        planner=planner,
        cron_expression="0 9 * * *",
        conversation_backend=backend,
        worktree_base=tmp_path,
    )
    session = await manager.start_session()
    chat.send.reset_mock()

    await manager.handle_message(
        IncomingMessage(text="Auth broke after the deploy", sender="@you:example.com")
    )

    assert any(t.role == "human" for t in session.turns)
    assert any(t.role == "assistant" for t in session.turns)
    sent = [call.args[0].text for call in chat.send.await_args_list]
    assert "Thinking…" in sent
    assert any("regression" in text.lower() or "auth" in text.lower() for text in sent)


@pytest.mark.asyncio
async def test_handle_message_without_backend_explains(tmp_path: Path) -> None:
    chat = AsyncMock()
    chat.send = AsyncMock()
    manager = JourFixeManager(
        chat=chat,
        planner=MagicMock(),
        cron_expression="0 9 * * *",
        conversation_backend=None,
        worktree_base=tmp_path,
        llm=JourFixeLlmSettings(),
    )
    await manager.start_session()
    chat.send.reset_mock()
    await manager.handle_message(
        IncomingMessage(text="Hello", sender="@you:example.com")
    )
    assert "SLUICE_JOUR_FIXE_LLM" in chat.send.await_args.args[0].text
