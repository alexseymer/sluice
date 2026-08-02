"""AI CLI backend adapter protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from sluice.models.budget import BudgetSnapshot, BudgetWindow
from sluice.models.plan import PlanTask
from sluice.models.schedule import DispatchResult


class BackendAdapter(ABC):
    """Common interface for Cursor, Agy, Codex, Claude Code, etc."""

    @property
    @abstractmethod
    def adapter_id(self) -> str:
        """Unique identifier for this backend adapter."""

    @abstractmethod
    async def dispatch(self, task: PlanTask, *, worktree: Path) -> DispatchResult:
        """Run a task in an isolated worktree and return the outcome."""

    @abstractmethod
    async def get_budget(self) -> BudgetSnapshot:
        """Return current quota/budget status for this backend."""

    @abstractmethod
    async def detect_fallback(self) -> bool:
        """Return True if the backend appears to be on a degraded fallback model."""

    @abstractmethod
    async def cancel(self, task_id: str) -> None:
        """Cancel a running task, if supported."""

    @abstractmethod
    def default_budget_window(self) -> BudgetWindow:
        """Return the configured budget window for this backend."""
