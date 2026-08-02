"""Tests for empirical budget probing."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from sluice.adapters.claude_code import ClaudeCodeBackendAdapter
from sluice.adapters.cursor_cli import CursorBackendAdapter
from sluice.core.budget import BudgetManager
from sluice.core.scheduler import Scheduler
from sluice.models.budget import BudgetSnapshot, BudgetWindow
from sluice.models.plan import Plan, PlanTask, TaskStatus
from sluice.models.schedule import DispatchResult
from sluice.store.sqlite import SQLiteStateStore


@pytest.mark.asyncio
async def test_counts_failed_attempts_not_only_success(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "sluice.db")
    await store.initialize()
    adapter = ClaudeCodeBackendAdapter(
        store=store,
        max_requests_per_window=50,
        dispatch_timeout_seconds=5,
    )

    process = AsyncMock()
    process.returncode = 1
    process.communicate = AsyncMock(return_value=(b"boom", b""))

    with patch(
        "sluice.adapters.cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        await adapter.dispatch(PlanTask(title="Task"), worktree=tmp_path / "wt")

    budget = await adapter.get_budget()
    assert budget.used_units == 1


@pytest.mark.asyncio
async def test_probes_beyond_cautious_limit_until_quota_error(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "sluice.db")
    await store.initialize()
    adapter = ClaudeCodeBackendAdapter(
        store=store,
        max_requests_per_window=3,
        dispatch_timeout_seconds=5,
    )

    process_ok = AsyncMock()
    process_ok.returncode = 0
    process_ok.communicate = AsyncMock(return_value=(b"ok", b""))

    with patch(
        "sluice.adapters.cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process_ok),
    ):
        for _ in range(3):
            assert await adapter._has_headroom()
            await adapter.dispatch(PlanTask(title="Task"), worktree=tmp_path / "wt")

        assert await adapter._has_headroom()
        await adapter.dispatch(PlanTask(title="Task 4"), worktree=tmp_path / "wt4")

    budget = await adapter.get_budget()
    assert budget.used_units == 4
    assert budget.is_probing is True
    assert budget.has_headroom is True


@pytest.mark.asyncio
async def test_quota_error_sets_observed_limit_and_stops_dispatch(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "sluice.db")
    await store.initialize()
    adapter = ClaudeCodeBackendAdapter(
        store=store,
        max_requests_per_window=3,
        dispatch_timeout_seconds=5,
    )

    process_ok = AsyncMock()
    process_ok.returncode = 0
    process_ok.communicate = AsyncMock(return_value=(b"ok", b""))
    process_quota = AsyncMock()
    process_quota.returncode = 0
    process_quota.communicate = AsyncMock(return_value=(b"rate limit exceeded", b""))

    with patch(
        "sluice.adapters.cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=[process_ok, process_ok, process_ok, process_quota]),
    ):
        for _ in range(3):
            await adapter.dispatch(PlanTask(title="Task"), worktree=tmp_path / "wt")
        result = await adapter.dispatch(PlanTask(title="Task 4"), worktree=tmp_path / "wt4")

    assert result.quota_exceeded is True
    budget = await adapter.get_budget()
    assert budget.window.observed_limit == 3
    assert budget.is_exhausted is True
    assert budget.has_headroom is False


@pytest.mark.asyncio
async def test_scheduler_failover_on_quota_exceeded(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "sluice.db")
    await store.initialize()

    claude = ClaudeCodeBackendAdapter(
        store=store,
        max_requests_per_window=1,
        dispatch_timeout_seconds=5,
    )
    cursor = CursorBackendAdapter(
        store=store,
        max_requests_per_window=10,
        dispatch_timeout_seconds=5,
    )

    claude.dispatch = AsyncMock()
    cursor.dispatch = AsyncMock()

    plan = Plan(tasks=[PlanTask(title="Ship", backend_id="claude_code")])
    task = plan.tasks[0]

    claude.dispatch.return_value = DispatchResult(
        task_id=task.id,
        backend_id="claude_code",
        success=False,
        quota_exceeded=True,
        error="quota",
    )
    cursor.dispatch.return_value = DispatchResult(
        task_id=task.id,
        backend_id="cursor",
        success=True,
        output="done",
    )

    backends = {"claude_code": claude, "cursor": cursor}
    scheduler = Scheduler(
        backends=backends,
        budget_manager=BudgetManager(backends),
        worktree_base=tmp_path / "worktrees",
    )

    await scheduler.schedule_plan(plan)
    result = await scheduler.dispatch_next(plan)

    assert result is not None
    assert result.success is True
    claude.dispatch.assert_awaited_once()
    cursor.dispatch.assert_awaited_once()
    assert plan.tasks[0].backend_id == "cursor"


@pytest.mark.asyncio
async def test_scheduler_failover_on_fallback_detected(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "sluice.db")
    await store.initialize()

    claude = ClaudeCodeBackendAdapter(
        store=store,
        max_requests_per_window=10,
        dispatch_timeout_seconds=5,
    )
    cursor = CursorBackendAdapter(
        store=store,
        max_requests_per_window=10,
        dispatch_timeout_seconds=5,
    )

    claude.dispatch = AsyncMock()
    cursor.dispatch = AsyncMock()

    plan = Plan(tasks=[PlanTask(title="Ship", backend_id="claude_code")])
    task = plan.tasks[0]

    claude.dispatch.return_value = DispatchResult(
        task_id=task.id,
        backend_id="claude_code",
        success=False,
        fallback_detected=True,
        error="fallback",
    )
    cursor.dispatch.return_value = DispatchResult(
        task_id=task.id,
        backend_id="cursor",
        success=True,
        output="done",
    )

    backends = {"claude_code": claude, "cursor": cursor}
    scheduler = Scheduler(
        backends=backends,
        budget_manager=BudgetManager(backends),
        worktree_base=tmp_path / "worktrees",
    )

    await scheduler.schedule_plan(plan)
    result = await scheduler.dispatch_next(plan)

    assert result is not None
    assert result.success is True
    claude.dispatch.assert_awaited_once()
    cursor.dispatch.assert_awaited_once()
    assert plan.tasks[0].backend_id == "cursor"


@pytest.mark.asyncio
async def test_scheduler_keeps_task_queued_when_all_backends_fallback(tmp_path) -> None:
    claude = ClaudeCodeBackendAdapter(dispatch_timeout_seconds=5)
    claude.dispatch = AsyncMock(
        return_value=DispatchResult(
            task_id=PlanTask(title="Ship").id,
            backend_id="claude_code",
            success=False,
            fallback_detected=True,
        )
    )

    plan = Plan(tasks=[PlanTask(title="Ship", backend_id="claude_code")])
    task = plan.tasks[0]
    claude.dispatch.return_value.task_id = task.id

    backends = {"claude_code": claude}
    scheduler = Scheduler(
        backends=backends,
        budget_manager=BudgetManager(backends),
        worktree_base=tmp_path / "worktrees",
    )

    await scheduler.schedule_plan(plan)
    result = await scheduler.dispatch_next(plan)

    assert result is not None
    assert result.fallback_detected is True
    assert task.status == TaskStatus.READY
    assert scheduler.has_pending is True


def test_budget_snapshot_headroom_with_observed_limit() -> None:
    snapshot = BudgetSnapshot(
        backend_id="claude_code",
        used_units=50,
        window=BudgetWindow(
            backend_id="claude_code",
            window_seconds=3600,
            cautious_limit=50,
            observed_limit=50,
        ),
        is_exhausted=True,
    )
    assert snapshot.has_headroom is False
    assert snapshot.remaining_units == 0
