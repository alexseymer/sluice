"""Tests for Matrix chat adapter."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from nio import MatrixRoom, RoomMessageText

from sluice.adapters.chat import OutgoingMessage
from sluice.adapters.matrix_chat import MatrixChatAdapter


@pytest.fixture
def adapter(tmp_path) -> MatrixChatAdapter:
    return MatrixChatAdapter(
        homeserver="https://matrix.example.com",
        room_id="!room:example.com",
        access_token="syt_test",
        user_id="@bot:example.com",
        allowed_sender="@human:example.com",
        store_path=tmp_path / "matrix-store",
    )


def test_is_configured_requires_credentials() -> None:
    assert (
        MatrixChatAdapter(
            homeserver="",
            room_id="!room:example.com",
            access_token="token",
        ).is_configured
        is False
    )


@pytest.mark.asyncio
async def test_start_skips_when_not_configured(adapter: MatrixChatAdapter) -> None:
    adapter._homeserver = ""
    await adapter.start()
    assert adapter.is_running is False


@pytest.mark.asyncio
async def test_on_room_message_filters_sender(adapter: MatrixChatAdapter) -> None:
    room = MatrixRoom("!room:example.com", None)
    ignored = RoomMessageText(
        source={
            "type": "m.room.message",
            "sender": "@stranger:example.com",
            "content": {"msgtype": "m.text", "body": "hello"},
            "event_id": "$1",
            "origin_server_ts": 1,
        },
        body="hello",
        formatted_body=None,
        format=None,
    )
    accepted = RoomMessageText(
        source={
            "type": "m.room.message",
            "sender": "@human:example.com",
            "content": {"msgtype": "m.text", "body": "ship it"},
            "event_id": "$2",
            "origin_server_ts": 2,
        },
        body="ship it",
        formatted_body=None,
        format=None,
    )

    await adapter._on_room_message(room, ignored)
    await adapter._on_room_message(room, accepted)

    assert adapter._queue.qsize() == 1
    message = adapter._queue.get_nowait()
    assert message.text == "ship it"
    assert message.sender == "@human:example.com"


@pytest.mark.asyncio
async def test_on_room_message_skips_while_catching_up(adapter: MatrixChatAdapter) -> None:
    room = MatrixRoom("!room:example.com", None)
    event = RoomMessageText(
        source={
            "type": "m.room.message",
            "sender": "@human:example.com",
            "content": {"msgtype": "m.text", "body": "/done"},
            "event_id": "$old",
            "origin_server_ts": 1,
        },
        body="/done",
        formatted_body=None,
        format=None,
    )
    adapter._catching_up = True
    await adapter._on_room_message(room, event)
    assert adapter._queue.qsize() == 0


@pytest.mark.asyncio
async def test_send_uses_room_send(adapter: MatrixChatAdapter) -> None:
    client = AsyncMock()
    adapter._client = client

    await adapter.send(OutgoingMessage(text="ping"))

    client.room_send.assert_awaited_once_with(
        "!room:example.com",
        "m.room.message",
        {"msgtype": "m.text", "body": "ping"},
    )


@pytest.mark.asyncio
async def test_stop_closes_client(adapter: MatrixChatAdapter) -> None:
    client = AsyncMock()
    adapter._client = client
    adapter._running = True
    adapter._sync_task = asyncio.create_task(asyncio.sleep(60))

    await adapter.stop()

    client.close.assert_awaited_once()
    assert adapter._client is None
    assert adapter._running is False
