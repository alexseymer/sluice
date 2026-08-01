"""Tests for chat loop command handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sluice.adapters.chat import IncomingMessage
from sluice.core.chat_loop import handle_message
from sluice.core.jour_fixe import JourFixeManager, JourFixeSession


@pytest.fixture
def app() -> MagicMock:
    mock = MagicMock()
    mock.chat = AsyncMock()
    mock.chat.send = AsyncMock()
    mock.jour_fixe = MagicMock(spec=JourFixeManager)
    mock.jour_fixe.active_session = None
    mock.jour_fixe.start_session = AsyncMock(return_value=JourFixeSession())
    mock.jour_fixe.handle_message = AsyncMock()
    mock.jour_fixe.close_session = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_help_command(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/help", sender="@you:example.com"))
    app.chat.send.assert_awaited_once()
    assert "/jour-fixe" in app.chat.send.await_args.args[0].text


@pytest.mark.asyncio
async def test_start_jour_fixe(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/jour-fixe", sender="@you:example.com"))
    app.jour_fixe.start_session.assert_awaited_once()
    app.chat.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_done_without_session(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/done", sender="@you:example.com"))
    app.jour_fixe.close_session.assert_not_awaited()
    assert "No active jour fixe" in app.chat.send.await_args.args[0].text


@pytest.mark.asyncio
async def test_plain_message_forwarded_to_jour_fixe(app: MagicMock) -> None:
    message = IncomingMessage(text="Build auth module", sender="@you:example.com")
    await handle_message(app, message)
    app.jour_fixe.handle_message.assert_awaited_once_with(message)
