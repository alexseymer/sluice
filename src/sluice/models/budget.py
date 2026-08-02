"""Budget and quota tracking models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BudgetWindow(BaseModel):
    """Tracked usage allowance for a backend over a time window."""

    backend_id: str
    window_seconds: int
    cautious_limit: int
    window_start: datetime | None = None
    observed_limit: int | None = None

    @property
    def effective_limit(self) -> int:
        """Hard limit if learned, otherwise the cautious starting point."""
        if self.observed_limit is not None:
            return self.observed_limit
        return self.cautious_limit


class BudgetSnapshot(BaseModel):
    """Point-in-time budget state for a backend."""

    backend_id: str
    used_units: int
    window: BudgetWindow
    is_exhausted: bool = False
    quota_exceeded: bool = False

    @property
    def is_probing(self) -> bool:
        """Attempting beyond the cautious limit to discover the real cap."""
        return (
            not self.is_exhausted
            and self.window.observed_limit is None
            and self.used_units >= self.window.cautious_limit
        )

    @property
    def remaining_units(self) -> int:
        if self.window.observed_limit is not None:
            return max(0, self.window.observed_limit - self.used_units)
        if self.used_units < self.window.cautious_limit:
            return self.window.cautious_limit - self.used_units
        return 0

    @property
    def has_headroom(self) -> bool:
        if self.is_exhausted:
            return False
        if self.window.observed_limit is not None:
            return self.used_units < self.window.observed_limit
        return True
