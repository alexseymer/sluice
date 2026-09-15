"""Tests for scheduler queue management."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from sluice.core.budget import BudgetManager
from sluice.core.scheduler import Scheduler
from sluice.models.budget import BudgetSnapshot, BudgetWindow
from sluice.models.plan import Plan, PlanTask
from sluice.models.schedule import DispatchResult


def _snapshot(
    backend_id: str,
    *,
    used: int = 0,
    cautious: int = 10,
    observed: int | None = None,
    exhausted: bool = False,
    window_seconds: int = 3600,
    window_start: datetime | None = None,
) -> BudgetSnapshot:
    return BudgetSnapshot(
        backend_id=backend_id,
        used_units=used,
        window=BudgetWindow(
            backend_id=backend_id,
            window_seconds=window_seconds,
            cautious_limit=cautious,
            window_start=window_start if window_start is not None else datetime.now(UTC),
            observed_limit=observed,
        ),
        is_exhausted=exhausted,
    )


def _backend(snapshot: BudgetSnapshot) -> AsyncMock:
    backend = AsyncMock()
    backend.get_budget = AsyncMock(return_value=snapshot)
    return backend


@pytest.mark.asyncio
async def test_schedule_ready_tasks_skips_already_queued(tmp_path) -> None:
    backends = {
        "claude_code": _backend(_snapshot("claude_code", used=0, cautious=10)),
    }
    scheduler = Scheduler(
        backends=backends,
        budget_manager=BudgetManager(backends),
        worktree_base=tmp_path / "worktrees",
        default_backend="claude_code",
        dispatch_poll_seconds=30,
    )

    plan = Plan(tasks=[PlanTask(title="One"), PlanTask(title="Two")])
    first = await scheduler.schedule_ready_tasks(plan)
    second = await scheduler.schedule_ready_tasks(plan)

    assert len(first) == 2
    assert second == []
    assert scheduler.has_pending is True


@pytest.mark.asyncio
async def test_pick_backend_prefers_most_remaining(tmp_path) -> None:
    backends = {
        "low": _backend(_snapshot("low", used=8, cautious=10, observed=10)),
        "high": _backend(_snapshot("high", used=1, cautious=10, observed=10)),
    }
    scheduler = Scheduler(
        backends=backends,
        budget_manager=BudgetManager(backends),
        worktree_base=tmp_path / "worktrees",
        dispatch_poll_seconds=30,
    )
    assert await scheduler._pick_backend() == "high"


@pytest.mark.asyncio
async def test_pick_backend_prefers_default_on_tie(tmp_path) -> None:
    backends = {
        "alpha": _backend(_snapshot("alpha", used=5, cautious=10, observed=10)),
        "beta": _backend(_snapshot("beta", used=5, cautious=10, observed=10)),
    }
    scheduler = Scheduler(
        backends=backends,
        budget_manager=BudgetManager(backends),
        worktree_base=tmp_path / "worktrees",
        default_backend="beta",
        dispatch_poll_seconds=30,
    )
    assert await scheduler._pick_backend() == "beta"


@pytest.mark.asyncio
async def test_pick_backend_skips_default_when_worse(tmp_path) -> None:
    backends = {
        "default": _backend(_snapshot("default", used=9, cautious=10, observed=10)),
        "better": _backend(_snapshot("better", used=1, cautious=10, observed=10)),
    }
    scheduler = Scheduler(
        backends=backends,
        budget_manager=BudgetManager(backends),
        worktree_base=tmp_path / "worktrees",
        default_backend="default",
        dispatch_poll_seconds=30,
    )
    assert await scheduler._pick_backend() == "better"


@pytest.mark.asyncio
async def test_schedule_paces_scheduled_at_across_window(tmp_path) -> None:
    now = datetime.now(UTC)
    window_start = now - timedelta(seconds=100)
    backends = {
        "claude_code": _backend(
            _snapshot(
                "claude_code",
                used=0,
                cautious=4,
                observed=4,
                window_seconds=400,
                window_start=window_start,
            )
        ),
    }
    scheduler = Scheduler(
        backends=backends,
        budget_manager=BudgetManager(backends),
        worktree_base=tmp_path / "worktrees",
        default_backend="claude_code",
        dispatch_poll_seconds=30,
    )
    plan = Plan(
        tasks=[
            PlanTask(title="A", backend_id="claude_code"),
            PlanTask(title="B", backend_id="claude_code"),
            PlanTask(title="C", backend_id="claude_code"),
        ]
    )
    slots = await scheduler.schedule_ready_tasks(plan)
    assert len(slots) == 3
    assert slots[0].scheduled_at <= datetime.now(UTC) + timedelta(seconds=1)
    assert slots[1].scheduled_at > slots[0].scheduled_at
    assert slots[2].scheduled_at > slots[1].scheduled_at
    # interval = max(30, ~300/4) = 75; third slot at ~150s, still inside window
    gap = (slots[1].scheduled_at - slots[0].scheduled_at).total_seconds()
    assert gap == pytest.approx(75.0, abs=2.0)


@pytest.mark.asyncio
async def test_dispatch_next_skips_future_slots(tmp_path) -> None:
    backends = {
        "claude_code": _backend(_snapshot("claude_code", used=0, cautious=10)),
    }
    backends["claude_code"].dispatch = AsyncMock(
        return_value=DispatchResult(
            task_id=PlanTask(title="x").id,
            backend_id="claude_code",
            success=True,
        )
    )
    scheduler = Scheduler(
        backends=backends,
        budget_manager=BudgetManager(backends),
        worktree_base=tmp_path / "worktrees",
        default_backend="claude_code",
        dispatch_poll_seconds=30,
    )
    future = PlanTask(title="Later", backend_id="claude_code")
    due = PlanTask(title="Now", backend_id="claude_code")
    plan = Plan(tasks=[future, due])
    await scheduler.schedule_ready_tasks(plan)
    # Force first slot into the future; second stays due (re-stamp after schedule)
    scheduler._queue[0].scheduled_at = datetime.now(UTC) + timedelta(hours=1)
    scheduler._queue[1].scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
    backends["claude_code"].dispatch.return_value = DispatchResult(
        task_id=due.id,
        backend_id="claude_code",
        success=True,
    )

    result = await scheduler.dispatch_next(plan)
    assert result is not None
    assert result.task_id == due.id
    backends["claude_code"].dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_parallel_one_due_slot_per_backend(tmp_path) -> None:
    a = _backend(_snapshot("a", used=0, cautious=10, observed=10))
    b = _backend(_snapshot("b", used=0, cautious=10, observed=10))
    a.dispatch = AsyncMock()
    b.dispatch = AsyncMock()

    t1 = PlanTask(title="A1", backend_id="a")
    t2 = PlanTask(title="A2", backend_id="a")
    t3 = PlanTask(title="B1", backend_id="b")
    a.dispatch.return_value = DispatchResult(
        task_id=t1.id, backend_id="a", success=True
    )
    b.dispatch.return_value = DispatchResult(
        task_id=t3.id, backend_id="b", success=True
    )

    backends = {"a": a, "b": b}
    scheduler = Scheduler(
        backends=backends,
        budget_manager=BudgetManager(backends),
        worktree_base=tmp_path / "worktrees",
        dispatch_poll_seconds=30,
    )
    plan = Plan(tasks=[t1, t2, t3])
    await scheduler.schedule_ready_tasks(plan)
    # All due now
    for slot in scheduler._queue:
        slot.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)

    results = await scheduler.dispatch_ready_parallel(plan)
    assert len(results) == 2
    a.dispatch.assert_awaited_once()
    b.dispatch.assert_awaited_once()
    assert scheduler.pending_count == 1
    assert scheduler._queue[0].task_id == t2.id
