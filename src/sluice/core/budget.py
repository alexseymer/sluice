"""Budget manager — conservative per-backend quota tracking."""

from __future__ import annotations

from sluice.adapters.backend import BackendAdapter
from sluice.models.budget import BudgetSnapshot


class BudgetManager:
    """Tracks and enforces per-backend usage windows."""

    def __init__(self, backends: dict[str, BackendAdapter]) -> None:
        self._backends = backends

    async def snapshot(self, backend_id: str) -> BudgetSnapshot:
        backend = self._backends[backend_id]
        return await backend.get_budget()

    async def can_dispatch(self, backend_id: str) -> bool:
        budget = await self.snapshot(backend_id)
        if budget.fallback_detected:
            return False
        return budget.has_headroom

    async def exhausted_backends(self) -> list[str]:
        exhausted: list[str] = []
        for backend_id in self._backends:
            budget = await self.snapshot(backend_id)
            if not budget.has_headroom or budget.fallback_detected:
                exhausted.append(backend_id)
        return exhausted
