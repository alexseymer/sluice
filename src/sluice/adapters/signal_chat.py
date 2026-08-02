"""Signal chat adapter (Phase 4 stub)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sluice.adapters.chat import ChatAdapter, IncomingMessage, OutgoingMessage


class SignalChatAdapter(ChatAdapter):
    """Signal adapter via signal-cli — not yet implemented."""

    def __init__(self, phone_number: str, recipient: str) -> None:
        self._phone_number = phone_number
        self._recipient = recipient

    @property
    def adapter_id(self) -> str:
        return "signal"

    async def start(self) -> None:
        raise NotImplementedError("Signal adapter not yet implemented")

    async def stop(self) -> None:
        pass

    async def send(self, message: OutgoingMessage) -> None:
        raise NotImplementedError("Signal adapter not yet implemented")

    async def listen(self) -> AsyncIterator[IncomingMessage]:
        raise NotImplementedError("Signal adapter not yet implemented")
        yield  # pragma: no cover

    async def start_jour_fixe_prompt(self) -> None:
        await self.send(
            OutgoingMessage(
                text=(
                    "Good to meet — let's do a short jour fixe. "
                    "Where do we stand since last time?"
                ),
                recipient=self._recipient,
            )
        )
