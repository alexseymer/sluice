"""Tests for forge status sync."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from sluice.core.forge_sync import close_forge_issue_for_task, sync_forge_status
from sluice.models.issue import ForgeIssue, IssueStatus
from sluice.models.plan import Plan, PlanTask, TaskStatus


@pytest.mark.asyncio
async def test_sync_marks_task_complete_when_issue_closed() -> None:
    task = PlanTask(title="Schema", forge_issue_id="1", status=TaskStatus.PENDING)
    plan = Plan(tasks=[task], approved_at=datetime.now(UTC))

    app = MagicMock()
    app.active_plan = plan
    app.forge = AsyncMock()
    app.forge.is_configured = True
    app.forge.get_issue = AsyncMock(
        return_value=ForgeIssue(
            id="1",
            number=1,
            title="Schema",
            status=IssueStatus.CLOSED,
        )
    )
    app.scheduler = AsyncMock()
    app.scheduler.has_pending = False
    app.scheduler.schedule_ready_tasks = AsyncMock(return_value=[])
    app.store = AsyncMock()
    app.store.save_plan = AsyncMock()

    await sync_forge_status(app)

    assert task.status == TaskStatus.COMPLETED
    app.scheduler.schedule_ready_tasks.assert_awaited_once_with(plan)
    app.store.save_plan.assert_awaited_once_with(plan)


@pytest.mark.asyncio
async def test_close_forge_issue_for_task() -> None:
    task = PlanTask(title="Schema", forge_issue_id="7")

    app = MagicMock()
    app.forge = AsyncMock()
    app.forge.is_configured = True
    app.forge.set_status = AsyncMock()

    await close_forge_issue_for_task(app, task)

    app.forge.set_status.assert_awaited_once_with("7", IssueStatus.CLOSED)
