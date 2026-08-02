"""Persisted budget probe state for a backend window."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BudgetState:
    backend_id: str
    window_start: str
    used_units: int
    cautious_limit: int
    observed_limit: int | None = None
    exhausted: bool = False

    @property
    def has_headroom(self) -> bool:
        if self.exhausted:
            return False
        if self.observed_limit is not None:
            return self.used_units < self.observed_limit
        return True

    @property
    def is_probing(self) -> bool:
        return (
            not self.exhausted
            and self.observed_limit is None
            and self.used_units >= self.cautious_limit
        )
