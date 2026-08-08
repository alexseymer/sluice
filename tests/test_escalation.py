"""Tests for Matrix escalation helpers and chat resume flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sluice.adapters.chat import IncomingMessage
from sluice.core.chat_loop import handle_message
from sluice.core.escalation import (
    apply_direction,
    find_pending_escalation,
    format_escalation_message,
    mark_retry,
    mark_skipped,
)
from sluice.core.orchestrator import extract_escalation
from sluice.models.plan import Plan, PlanTask, TaskStatus


def test_extract_escalation_line() -> None:
    assert extract_escalation("ESCALATE: Use JWT or sessions?") == "Use JWT or sessions?"
    assert extract_escalation("noise\nescalate: Pick a DB\nmore") == "Pick a DB"
    assert extract_escalation("no escalate here") is None


def test_find_and_format_pending_escalation() -> None:
    task = PlanTask(
        title="Add auth",
        description="Implement login\n\nEscalation:\nJWT or sessions?",
        status=TaskStatus.NEEDS_INPUT,
    )
    plan = Plan(tasks=[task])
    escalation = find_pending_escalation(plan)
    assert escalation is not None
    assert escalation.title == "Add auth"
    assert "JWT or sessions?" in escalation.question
    message = format_escalation_message(escalation)
    assert "/retry" in message
    assert "/skip" in message


def test_apply_direction_and_retry_skip() -> None:
    task = PlanTask(title="Add auth", status=TaskStatus.NEEDS_INPUT)
    apply_direction(task, "Prefer JWT")
    assert task.status == TaskStatus.READY
    assert "Prefer JWT" in task.description

    task.status = TaskStatus.NEEDS_INPUT
    mark_retry(task)
    assert task.status == TaskStatus.READY

    task.status = TaskStatus.NEEDS_INPUT
    mark_skipped(task)
    assert task.status == TaskStatus.CANCELLED


@pytest.fixture
def app() -> MagicMock:
    mock = MagicMock()
    mock.chat = AsyncMock()
    mock.chat.send = AsyncMock()
    mock.chat.is_configured = True
    mock.jour_fixe = MagicMock()
    mock.jour_fixe.active_session = None
    mock.jour_fixe.handle_message = AsyncMock()
    mock.plan_approval = MagicMock()
    mock.plan_approval.has_pending_plan = False
    mock.scheduler = MagicMock()
    mock.scheduler.schedule_ready_tasks = AsyncMock(return_value=[])
    mock.store = AsyncMock()
    mock.store.save_plan = AsyncMock()
    mock.settings = MagicMock()
    mock.settings.plan_auto_approve = False
    return mock


@pytest.mark.asyncio
async def test_direction_resumes_escalated_task(app: MagicMock) -> None:
    task = PlanTask(
        title="Add auth",
        description="Implement login\n\nEscalation:\nJWT or sessions?",
        status=TaskStatus.NEEDS_INPUT,
    )
    plan = Plan(tasks=[task])
    app.active_plan = plan

    await handle_message(
        app, IncomingMessage(text="Use JWT with refresh tokens", sender="@you:example.com")
    )

    assert task.status == TaskStatus.READY
    assert "Use JWT with refresh tokens" in task.description
    app.scheduler.schedule_ready_tasks.assert_awaited_once_with(plan)
    assert "resuming" in app.chat.send.await_args.args[0].text.lower()


@pytest.mark.asyncio
async def test_retry_and_skip_commands(app: MagicMock) -> None:
    task = PlanTask(title="Add auth", status=TaskStatus.NEEDS_INPUT)
    plan = Plan(tasks=[task])
    app.active_plan = plan

    await handle_message(app, IncomingMessage(text="/retry", sender="@you:example.com"))
    assert task.status == TaskStatus.READY

    task.status = TaskStatus.NEEDS_INPUT
    await handle_message(app, IncomingMessage(text="/skip", sender="@you:example.com"))
    assert task.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_status_shows_escalation(app: MagicMock) -> None:
    task = PlanTask(
        title="Add auth",
        description="x\n\nEscalation:\nNeed a decision",
        status=TaskStatus.NEEDS_INPUT,
    )
    app.active_plan = Plan(tasks=[task])
    app.jour_fixe.next_scheduled_at = MagicMock(return_value=MagicMock(isoformat=lambda: "soon"))

    await handle_message(app, IncomingMessage(text="/status", sender="@you:example.com"))
    text = app.chat.send.await_args.args[0].text
    assert "Add auth" in text
    assert "Need a decision" in text
