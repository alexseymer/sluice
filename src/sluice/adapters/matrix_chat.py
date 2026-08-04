"""Matrix chat adapter using matrix-nio."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import structlog
from nio import AsyncClient, AsyncClientConfig, MatrixRoom, RoomMessageText, SyncError

from sluice.adapters.chat import ChatAdapter, IncomingMessage, OutgoingMessage

log = structlog.get_logger()


class MatrixChatAdapter(ChatAdapter):
    """Matrix bot adapter backed by matrix-nio sync loop."""

    def __init__(
        self,
        *,
        homeserver: str,
        room_id: str,
        access_token: str,
        user_id: str | None = None,
        allowed_sender: str | None = None,
        store_path: Path | None = None,
        sync_timeout_ms: int = 30_000,
    ) -> None:
        self._homeserver = homeserver.rstrip("/")
        self._room_id = room_id
        self._access_token = access_token
        self._user_id = user_id
        self._allowed_sender = allowed_sender
        self._store_path = store_path
        self._sync_timeout_ms = sync_timeout_ms

        self._client: AsyncClient | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()
        self._running = False
        self._logged_sync_error = False
        # Drop timeline events from the initial catch-up sync so a restart
        # does not re-run old /jour-fixe /done /approve commands.
        self._catching_up = False

    @property
    def adapter_id(self) -> str:
        return "matrix"

    @property
    def is_configured(self) -> bool:
        return bool(self._homeserver and self._room_id and self._access_token)

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if not self.is_configured:
            log.warning(
                "matrix_not_configured", reason="missing homeserver, room_id, or access_token"
            )
            return

        if self._running:
            return

        user_id = self._user_id or await self._resolve_user_id()
        self._user_id = user_id

        config = AsyncClientConfig(store_sync_tokens=True)
        store = ""
        if self._store_path is not None:
            self._store_path.mkdir(parents=True, exist_ok=True)
            store = str(self._store_path)
        self._client = AsyncClient(
            self._homeserver,
            user_id,
            store_path=store,
            config=config,
        )
        self._client.access_token = self._access_token
        self._client.add_event_callback(self._on_room_message, RoomMessageText)
        self._client.add_response_callback(self._on_sync_response)

        await self._ensure_joined_room()
        self._catching_up = True
        try:
            await self._client.sync(timeout=0, full_state=True)
        finally:
            self._catching_up = False

        self._sync_task = asyncio.create_task(
            self._client.sync_forever(timeout=self._sync_timeout_ms, full_state=False),
            name="matrix-sync",
        )
        self._running = True
        log.info(
            "matrix_started",
            homeserver=self._homeserver,
            room_id=self._room_id,
            user_id=user_id,
            sync_timeout_ms=self._sync_timeout_ms,
        )

    async def stop(self) -> None:
        self._running = False
        if self._sync_task is not None:
            self._sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sync_task
            self._sync_task = None

        if self._client is not None:
            await self._client.close()
            self._client = None

        log.info("matrix_stopped")

    async def send(self, message: OutgoingMessage) -> None:
        client = self._require_client()
        room_id = message.recipient or self._room_id
        await client.room_send(
            room_id,
            "m.room.message",
            {
                "msgtype": "m.text",
                "body": message.text,
            },
        )

    async def listen(self) -> AsyncIterator[IncomingMessage]:
        while self._running:
            yield await self._queue.get()

    async def wait_for_message(self, *, timeout_seconds: float) -> IncomingMessage:
        """Wait for the next allowed incoming message (used for CLI auth codes)."""
        if not self._running:
            raise RuntimeError("Matrix client is not started")
        return await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)

    def drain_pending_messages(self) -> int:
        """Drop queued messages so an auth wait does not consume stale commands."""
        dropped = 0
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            dropped += 1
        return dropped

    async def start_jour_fixe_prompt(self) -> None:
        await self.send(
            OutgoingMessage(
                text=(
                    "Good to meet — let's do a short jour fixe.\n\n"
                    "Where do we stand, and what problems or surprises showed up "
                    "since last time? Once we've talked it through, say you're done "
                    "and I'll turn our discussion into a concrete plan."
                )
            )
        )

    async def _resolve_user_id(self) -> str:
        probe = AsyncClient(self._homeserver, "")
        probe.access_token = self._access_token
        try:
            response = await probe.whoami()
        finally:
            await probe.close()

        if not hasattr(response, "user_id"):
            msg = f"Matrix whoami failed: {response}"
            raise RuntimeError(msg)

        return str(response.user_id)

    async def _ensure_joined_room(self) -> None:
        client = self._require_client()
        if self._room_id in client.rooms:
            return

        response = await client.join(self._room_id)
        if hasattr(response, "room_id"):
            log.info("matrix_joined_room", room_id=self._room_id)
            return

        log.warning("matrix_join_room_failed", room_id=self._room_id, response=str(response))

    async def _on_sync_response(self, response: object) -> None:
        if not isinstance(response, SyncError):
            self._logged_sync_error = False
            return
        if self._logged_sync_error:
            return
        self._logged_sync_error = True
        log.warning(
            "matrix_sync_error",
            message=getattr(response, "message", None),
            status_code=getattr(response, "status_code", None),
            sync_timeout_ms=self._sync_timeout_ms,
            hint=(
                "Homeserver/proxy may be cutting long-poll sync (often ~10s). "
                "Lower SLUICE_MATRIX_SYNC_TIMEOUT_MS (e.g. 8000) or raise the "
                "proxy idle timeout for /_matrix/client/*/sync."
            ),
        )

    async def _on_room_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        if self._catching_up:
            return
        if room.room_id != self._room_id:
            return
        if event.sender == self._user_id:
            return
        if self._allowed_sender and event.sender != self._allowed_sender:
            return

        body = event.body.strip()
        if not body:
            return

        log.info(
            "matrix_message_received",
            sender=event.sender,
            room_id=room.room_id,
            text_preview=body[:80],
        )
        await self._queue.put(
            IncomingMessage(
                text=body,
                sender=event.sender,
                received_at=datetime.now(UTC),
                session_id=room.room_id,
            )
        )

    def _require_client(self) -> AsyncClient:
        if self._client is None:
            raise RuntimeError("Matrix client is not started")
        return self._client
