"""Tests for orchestrator shaping and worker/reviewer loops."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sluice.core.orchestrator import (
    build_review_prompt,
    build_worker_prompt,
    execute_task_with_review,
    parse_review_output,
)
from sluice.core.planner_llm import _parse_plan_output
from sluice.models.plan import PlanTask, TaskStatus
from sluice.models.schedule import DispatchResult


def test_parse_plan_output_with_acceptance_criteria() -> None:
    output = """
    {
      "summary": "Ship auth",
      "tasks": [
        {
          "title": "Add login API",
          "description": "POST /login endpoint",
          "acceptance_criteria": "- returns JWT\\n- validates password",
          "depends_on": []
        }
      ]
    }
    """
    plan = _parse_plan_output(output, session_id="550e8400-e29b-41d4-a716-446655440000")
    assert plan is not None
    assert plan.tasks[0].acceptance_criteria == "- returns JWT\n- validates password"


def test_build_worker_prompt_includes_criteria_and_feedback() -> None:
    task = PlanTask(
        title="Add login",
        description="Implement login",
        acceptance_criteria="- returns JWT",
    )
    prompt = build_worker_prompt(task, review_feedback="Missing tests")
    assert "Acceptance criteria" in prompt
    assert "Missing tests" in prompt


def test_build_review_prompt_includes_worker_output() -> None:
    task = PlanTask(title="Add login", acceptance_criteria="- returns JWT")
    prompt = build_review_prompt(task, "implemented jwt handler")
    assert "implemented jwt handler" in prompt
    assert "approved" in prompt


def test_parse_review_output_approved() -> None:
    approved, feedback = parse_review_output('{"approved": true, "feedback": "LGTM"}')
    assert approved is True
    assert feedback == "LGTM"


def test_parse_review_output_rejected() -> None:
    approved, feedback = parse_review_output(
        '{"approved": false, "feedback": "Add unit tests"}'
    )
    assert approved is False
    assert "unit tests" in feedback


@pytest.mark.asyncio
async def test_execute_task_with_review_succeeds_on_approval(tmp_path: Path) -> None:
    task = PlanTask(
        title="Add login",
        description="Implement login",
        acceptance_criteria="- returns JWT",
    )
    worker = AsyncMock()
    worker.adapter_id = "claude_code"
    worker.dispatch = AsyncMock(
        side_effect=[
            DispatchResult(
                task_id=task.id,
                backend_id="claude_code",
                success=True,
                output="done",
            ),
        ]
    )
    reviewer = AsyncMock()
    reviewer.adapter_id = "cursor"
    reviewer.dispatch = AsyncMock(
        return_value=DispatchResult(
            task_id=task.id,
            backend_id="cursor",
            success=True,
            output='{"approved": true, "feedback": "Looks good"}',
        )
    )

    result = await execute_task_with_review(
        worker=worker,
        reviewer=reviewer,
        task=task,
        worktree=tmp_path,
        max_iterations=3,
    )

    assert result.success is True
    assert task.status == TaskStatus.COMPLETED
    assert worker.dispatch.await_count == 1


@pytest.mark.asyncio
async def test_execute_task_with_review_retries_until_approved(tmp_path: Path) -> None:
    task = PlanTask(title="Add login", acceptance_criteria="- returns JWT")
    worker = AsyncMock()
    worker.adapter_id = "claude_code"
    worker.dispatch = AsyncMock(
        return_value=DispatchResult(
            task_id=task.id,
            backend_id="claude_code",
            success=True,
            output="attempt",
        )
    )
    reviewer = AsyncMock()
    reviewer.adapter_id = "cursor"
    reviewer.dispatch = AsyncMock(
        side_effect=[
            DispatchResult(
                task_id=task.id,
                backend_id="cursor",
                success=True,
                output='{"approved": false, "feedback": "Add tests"}',
            ),
            DispatchResult(
                task_id=task.id,
                backend_id="cursor",
                success=True,
                output='{"approved": true, "feedback": "Now complete"}',
            ),
        ]
    )

    result = await execute_task_with_review(
        worker=worker,
        reviewer=reviewer,
        task=task,
        worktree=tmp_path,
        max_iterations=3,
    )

    assert result.success is True
    assert task.status == TaskStatus.COMPLETED
    assert worker.dispatch.await_count == 2
    assert reviewer.dispatch.await_count == 2


@pytest.mark.asyncio
async def test_execute_task_with_review_fails_after_max_iterations(tmp_path: Path) -> None:
    task = PlanTask(title="Add login", acceptance_criteria="- returns JWT")
    worker = AsyncMock()
    worker.adapter_id = "claude_code"
    worker.dispatch = AsyncMock(
        return_value=DispatchResult(
            task_id=task.id,
            backend_id="claude_code",
            success=True,
            output="attempt",
        )
    )
    reviewer = AsyncMock()
    reviewer.adapter_id = "cursor"
    reviewer.dispatch = AsyncMock(
        return_value=DispatchResult(
            task_id=task.id,
            backend_id="cursor",
            success=True,
            output='{"approved": false, "feedback": "Still missing tests"}',
        )
    )

    result = await execute_task_with_review(
        worker=worker,
        reviewer=reviewer,
        task=task,
        worktree=tmp_path,
        max_iterations=2,
    )

    assert result.success is False
    assert task.status == TaskStatus.FAILED
    assert worker.dispatch.await_count == 2
