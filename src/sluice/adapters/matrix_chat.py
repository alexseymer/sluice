"""Matrix chat adapter (Phase 1 stub)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sluice.adapters.chat import ChatAdapter, IncomingMessage, OutgoingMessage


class MatrixChatAdapter(ChatAdapter):
    """Matrix bot adapter — not yet implemented."""

    def __init__(self, homeserver: str, room_id: str, access_token: str) -> None:
        self._homeserver = homeserver
        self._room_id = room_id
        self._access_token = access_token

    @property
    def adapter_id(self) -> str:
        return "matrix"

    async def start(self) -> None:
        raise NotImplementedError("Matrix adapter not yet implemented")

    async def stop(self) -> None:
        pass

    async def send(self, message: OutgoingMessage) -> None:
        raise NotImplementedError("Matrix adapter not yet implemented")

    async def listen(self) -> AsyncIterator[IncomingMessage]:
        raise NotImplementedError("Matrix adapter not yet implemented")
        yield  # pragma: no cover

    async def start_jour_fixe_prompt(self) -> None:
        await self.send(OutgoingMessage(text="Good morning — ready for today's jour fixe?"))
