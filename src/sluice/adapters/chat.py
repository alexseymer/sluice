"""Chat backend adapter protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class IncomingMessage:
    text: str
    sender: str
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    session_id: str | None = None


@dataclass
class OutgoingMessage:
    text: str
    recipient: str | None = None


class ChatAdapter(ABC):
    """Common interface for Signal, Matrix, and Telegram chat backends."""

    @property
    @abstractmethod
    def adapter_id(self) -> str:
        """Unique identifier for this adapter instance."""

    @abstractmethod
    async def start(self) -> None:
        """Connect to the chat backend and begin listening."""

    @abstractmethod
    async def stop(self) -> None:
        """Disconnect cleanly."""

    @abstractmethod
    async def send(self, message: OutgoingMessage) -> None:
        """Send a message to the configured human contact or room."""

    @abstractmethod
    def listen(self) -> AsyncIterator[IncomingMessage]:
        """Yield incoming messages as they arrive."""

    @abstractmethod
    async def start_jour_fixe_prompt(self) -> None:
        """Proactively message the human to begin a jour fixe session."""
