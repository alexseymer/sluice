"""Budget manager — empirical probe-aware quota tracking."""

from __future__ import annotations

from sluice.adapters.backend import BackendAdapter
from sluice.models.budget import BudgetSnapshot


class BudgetManager:
    """Tracks per-backend usage and supports probing past cautious limits."""

    def __init__(self, backends: dict[str, BackendAdapter]) -> None:
        self._backends = backends

    async def snapshot(self, backend_id: str) -> BudgetSnapshot:
        backend = self._backends[backend_id]
        return await backend.get_budget()

    async def can_dispatch(self, backend_id: str) -> bool:
        budget = await self.snapshot(backend_id)
        return budget.has_headroom

    async def available_backends(self) -> list[str]:
        available: list[str] = []
        for backend_id in self._backends:
            if await self.can_dispatch(backend_id):
                available.append(backend_id)
        return available

    async def rank_available(self) -> list[str]:
        """Backends with headroom, best remaining first.

        Probing backends (no ``observed_limit``, at/past cautious) sort after
        backends with positive remaining, and ahead of exhausted (excluded).
        Ties keep configured backend insertion order.
        """
        ranked: list[tuple[int, int, int, str]] = []
        for index, backend_id in enumerate(self._backends):
            budget = await self.snapshot(backend_id)
            if not budget.has_headroom:
                continue
            # Primary: more remaining first. Probing → remaining_units 0, so last
            # among headroom backends; is_probing is a stable secondary key.
            ranked.append(
                (
                    -budget.remaining_units,
                    1 if budget.is_probing else 0,
                    index,
                    backend_id,
                )
            )
        ranked.sort()
        return [backend_id for *_, backend_id in ranked]

    async def exhausted_backends(self) -> list[str]:
        exhausted: list[str] = []
        for backend_id in self._backends:
            budget = await self.snapshot(backend_id)
            if not budget.has_headroom:
                exhausted.append(backend_id)
        return exhausted
