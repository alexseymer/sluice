"""Tests for scheduler queue management."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sluice.core.budget import BudgetManager
from sluice.core.scheduler import Scheduler
from sluice.models.plan import Plan, PlanTask


@pytest.mark.asyncio
async def test_schedule_ready_tasks_skips_already_queued(tmp_path) -> None:
    backend = AsyncMock()
    backend.get_budget = AsyncMock()
    backends = {"claude_code": backend}
    scheduler = Scheduler(
        backends=backends,
        budget_manager=BudgetManager(backends),
        worktree_base=tmp_path / "worktrees",
        default_backend="claude_code",
    )

    plan = Plan(tasks=[PlanTask(title="One"), PlanTask(title="Two")])
    first = await scheduler.schedule_ready_tasks(plan)
    second = await scheduler.schedule_ready_tasks(plan)

    assert len(first) == 2
    assert second == []
    assert scheduler.has_pending is True
