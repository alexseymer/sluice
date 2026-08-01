"""Budget and quota tracking models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BudgetWindow(BaseModel):
    """Tracked usage allowance for a backend over a time window."""

    backend_id: str
    window_seconds: int
    max_units: int
    safety_margin: float = Field(default=0.85, ge=0.0, le=1.0)
    window_start: datetime | None = None

    @property
    def effective_limit(self) -> int:
        return int(self.max_units * self.safety_margin)


class BudgetSnapshot(BaseModel):
    """Point-in-time budget state for a backend."""

    backend_id: str
    used_units: int
    window: BudgetWindow
    is_exhausted: bool = False
    fallback_detected: bool = False

    @property
    def remaining_units(self) -> int:
        return max(0, self.window.effective_limit - self.used_units)

    @property
    def has_headroom(self) -> bool:
        return not self.is_exhausted and self.remaining_units > 0
