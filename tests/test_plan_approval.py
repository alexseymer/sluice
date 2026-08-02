"""Tests for plan approval flow."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from sluice.core.plan_approval import PlanApprovalError, PlanApprovalManager
from sluice.models.issue import ForgeIssue, IssueStatus
from sluice.models.plan import Plan, PlanTask


@pytest.fixture
def forge() -> AsyncMock:
    mock = AsyncMock()
    mock.is_configured = True
    counter = {"n": 0}

    async def create_issue(task: PlanTask) -> ForgeIssue:
        counter["n"] += 1
        number = counter["n"]
        return ForgeIssue(
            id=str(number),
            number=number,
            title=task.title,
            body=task.description,
            status=IssueStatus.OPEN,
            url=f"https://github.com/acme/sluice/issues/{number}",
        )

    mock.create_issue.side_effect = create_issue
    mock.link_dependency = AsyncMock()
    return mock


@pytest.fixture
def store() -> AsyncMock:
    mock = AsyncMock()
    mock.save_plan = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_submit_and_approve_creates_issues(forge: AsyncMock, store: AsyncMock) -> None:
    blocker_id = uuid4()
    blocked_id = uuid4()
    plan = Plan(
        tasks=[
            PlanTask(id=blocker_id, title="Schema"),
            PlanTask(id=blocked_id, title="API client", depends_on=[blocker_id]),
        ]
    )
    manager = PlanApprovalManager(forge, store)

    await manager.submit(plan)
    approved = await manager.approve()

    assert approved.is_approved
    assert forge.create_issue.await_count == 2
    forge.link_dependency.assert_awaited_once_with("2", "1")
    assert approved.tasks[0].forge_issue_id == "1"
    assert approved.tasks[1].forge_issue_id == "2"
    assert manager.pending_plan is None


@pytest.mark.asyncio
async def test_reject_clears_pending_plan(forge: AsyncMock, store: AsyncMock) -> None:
    manager = PlanApprovalManager(forge, store)
    plan = Plan(tasks=[PlanTask(title="One thing")])

    await manager.submit(plan)
    await manager.reject()

    assert manager.pending_plan is None
    forge.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_without_pending_raises(forge: AsyncMock, store: AsyncMock) -> None:
    manager = PlanApprovalManager(forge, store)
    with pytest.raises(PlanApprovalError, match="No plan"):
        await manager.approve()


@pytest.mark.asyncio
async def test_format_plan_shows_dependencies(forge: AsyncMock, store: AsyncMock) -> None:
    blocker_id = uuid4()
    plan = Plan(
        tasks=[
            PlanTask(id=blocker_id, title="Schema"),
            PlanTask(title="API client", depends_on=[blocker_id]),
        ]
    )
    manager = PlanApprovalManager(forge, store)
    text = manager.format_plan(plan)

    assert "1. Schema" in text
    assert "after issue 1" in text
    assert "/approve" in text
