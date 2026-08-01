"""Claude Code CLI backend adapter (Phase 1 stub)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sluice.adapters.backend import BackendAdapter
from sluice.models.budget import BudgetSnapshot, BudgetWindow
from sluice.models.plan import PlanTask
from sluice.models.schedule import DispatchResult


class ClaudeCodeBackendAdapter(BackendAdapter):
    """Claude Code CLI adapter — not yet implemented."""

    def __init__(
        self,
        *,
        cli_path: str = "claude",
        max_requests_per_window: int = 50,
        window_seconds: int = 5 * 60 * 60,
        safety_margin: float = 0.85,
    ) -> None:
        self._cli_path = cli_path
        self._max_requests = max_requests_per_window
        self._window_seconds = window_seconds
        self._safety_margin = safety_margin
        self._used_units = 0

    @property
    def adapter_id(self) -> str:
        return "claude_code"

    async def dispatch(self, task: PlanTask, *, worktree: Path) -> DispatchResult:
        raise NotImplementedError("Claude Code adapter not yet implemented")

    async def get_budget(self) -> BudgetSnapshot:
        window = self.default_budget_window()
        return BudgetSnapshot(
            backend_id=self.adapter_id,
            used_units=self._used_units,
            window=window,
            is_exhausted=self._used_units >= window.effective_limit,
        )

    async def detect_fallback(self) -> bool:
        return False

    async def cancel(self, task_id: str) -> None:
        raise NotImplementedError("Claude Code adapter not yet implemented")

    def default_budget_window(self) -> BudgetWindow:
        return BudgetWindow(
            backend_id=self.adapter_id,
            window_seconds=self._window_seconds,
            max_units=self._max_requests,
            safety_margin=self._safety_margin,
            window_start=datetime.now(UTC),
        )
