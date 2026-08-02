"""Jour fixe session manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from croniter import croniter

from sluice.adapters.chat import ChatAdapter, IncomingMessage
from sluice.core.planner import Planner
from sluice.models.plan import Plan


@dataclass
class JourFixeSession:
    id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    messages: list[IncomingMessage] = field(default_factory=list)
    plan: Plan | None = None

    @property
    def is_active(self) -> bool:
        return self.ended_at is None


class JourFixeManager:
    """Manages recurring jour fixe sessions and the planning flow."""

    def __init__(
        self,
        chat: ChatAdapter,
        planner: Planner,
        cron_expression: str,
        timeout_minutes: int = 60,
    ) -> None:
        self._chat = chat
        self._planner = planner
        self._cron = croniter(cron_expression)
        self._timeout_minutes = timeout_minutes
        self._session: JourFixeSession | None = None

    @property
    def active_session(self) -> JourFixeSession | None:
        return self._session

    def next_scheduled_at(self) -> datetime:
        return self._cron.get_next(datetime)

    async def start_session(self) -> JourFixeSession:
        self._session = JourFixeSession()
        await self._chat.start_jour_fixe_prompt()
        return self._session

    async def handle_message(self, message: IncomingMessage) -> None:
        if self._session is None or not self._session.is_active:
            return
        self._session.messages.append(message)

    async def close_session(self, *, task_descriptions: list[str] | None = None) -> Plan:
        if self._session is None:
            raise RuntimeError("No active jour fixe session")

        descriptions = task_descriptions or [m.text for m in self._session.messages]
        plan = await self._planner.generate_plan(
            session_id=str(self._session.id),
            task_descriptions=descriptions,
        )
        self._session.plan = plan
        self._session.ended_at = datetime.now(UTC)
        return plan
