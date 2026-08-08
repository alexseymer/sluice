"""Tests for post-approval dispatch scheduling and loop."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from sluice.core.dispatch_loop import _notify_dispatch_result, on_plan_approved, run_dispatch_loop
from sluice.models.plan import Plan, PlanTask, TaskStatus, plan_is_complete
from sluice.models.schedule import DispatchResult


@pytest.mark.asyncio
async def test_on_plan_approved_schedules_tasks() -> None:
    plan = Plan(tasks=[PlanTask(title="Ship feature")])
    app = MagicMock()
    app.active_plan = None
    app.scheduler = AsyncMock()
    app.scheduler.schedule_plan = AsyncMock(return_value=[MagicMock()])
    app.store = AsyncMock()
    app.store.save_plan = AsyncMock()
    app.chat = AsyncMock()
    app.chat.is_configured = True
    app.chat.send = AsyncMock()

    await on_plan_approved(app, plan)

    assert app.active_plan is plan
    app.scheduler.schedule_plan.assert_awaited_once_with(plan)
    app.store.save_plan.assert_awaited_once_with(plan)
    app.chat.send.assert_awaited_once()


def test_plan_is_complete_when_all_terminal() -> None:
    plan = Plan(
        tasks=[
            PlanTask(title="Done", status=TaskStatus.COMPLETED),
            PlanTask(title="Failed", status=TaskStatus.FAILED),
        ]
    )
    assert plan_is_complete(plan) is True


def test_plan_is_not_complete_with_pending_tasks() -> None:
    plan = Plan(
        tasks=[
            PlanTask(title="Done", status=TaskStatus.COMPLETED),
            PlanTask(title="Waiting", status=TaskStatus.PENDING),
        ]
    )
    assert plan_is_complete(plan) is False


def test_plan_is_not_complete_with_needs_input() -> None:
    plan = Plan(
        tasks=[
            PlanTask(title="Done", status=TaskStatus.COMPLETED),
            PlanTask(title="Waiting on human", status=TaskStatus.NEEDS_INPUT),
        ]
    )
    assert plan_is_complete(plan) is False


@pytest.mark.asyncio
async def test_dispatch_notifies_escalation() -> None:
    task = PlanTask(
        title="Add auth",
        description="x\n\nEscalation:\nJWT?",
        status=TaskStatus.NEEDS_INPUT,
    )
    plan = Plan(tasks=[task])
    result = DispatchResult(
        task_id=task.id,
        backend_id="claude_code",
        success=False,
        needs_input=True,
        escalation_question="JWT?",
    )
    app = MagicMock()
    app.chat = AsyncMock()
    app.chat.is_configured = True
    app.chat.send = AsyncMock()

    await _notify_dispatch_result(app, plan, result)

    text = app.chat.send.await_args.args[0].text
    assert "Add auth" in text
    assert "/retry" in text


@pytest.mark.asyncio
async def test_dispatch_loop_runs_task_and_clears_plan() -> None:
    task = PlanTask(title="Ship", status=TaskStatus.COMPLETED)
    plan = Plan(tasks=[task])
    result = DispatchResult(task_id=task.id, backend_id="claude_code", success=True)

    class SchedulerStub:
        def __init__(self) -> None:
            self.has_pending = True
            self.pending_count = 1
            self.dispatch_next = AsyncMock(return_value=result)
            self.schedule_ready_tasks = AsyncMock(return_value=[])

    scheduler = SchedulerStub()
    app = MagicMock()
    app.active_plan = plan
    app.settings = MagicMock()
    app.settings.dispatch_poll_seconds = 1
    app.scheduler = scheduler
    app.store = AsyncMock()
    app.store.save_plan = AsyncMock()
    app.chat = AsyncMock()
    app.chat.is_configured = True
    app.chat.send = AsyncMock()

    call_count = 0

    async def stop_after_one_sleep(_seconds: float) -> None:
        nonlocal call_count
        call_count += 1
        scheduler.has_pending = False
        if call_count > 1:
            raise asyncio.CancelledError

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(asyncio, "sleep", stop_after_one_sleep)
        with pytest.raises(asyncio.CancelledError):
            await run_dispatch_loop(app)

    scheduler.dispatch_next.assert_awaited_once_with(plan)
    assert app.active_plan is None
