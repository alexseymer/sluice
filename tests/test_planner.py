"""Tests for planner dependency inference."""

from __future__ import annotations

import pytest

from sluice.core.planner import Planner
from sluice.core.planner_inference import build_tasks_with_dependencies


def test_numbered_list_chains_dependencies() -> None:
    tasks = build_tasks_with_dependencies(
        [
            "1. Design schema",
            "2. Build API client",
            "3. Add integration tests",
        ]
    )

    assert len(tasks) == 3
    assert tasks[0].depends_on == []
    assert tasks[1].depends_on == [tasks[0].id]
    assert tasks[2].depends_on == [tasks[1].id]


def test_explicit_dependency_by_title() -> None:
    tasks = build_tasks_with_dependencies(
        [
            "Design schema",
            "Build API client (depends on schema)",
        ]
    )

    assert tasks[1].depends_on == [tasks[0].id]


def test_explicit_dependency_by_task_number() -> None:
    tasks = build_tasks_with_dependencies(
        [
            "Design schema",
            "Build API client (after task 1)",
        ]
    )

    assert tasks[1].depends_on == [tasks[0].id]


def test_skips_chat_commands() -> None:
    tasks = build_tasks_with_dependencies(
        [
            "/help",
            "Ship auth module",
            "/done",
        ]
    )

    assert len(tasks) == 1
    assert tasks[0].title == "Ship auth module"


@pytest.mark.asyncio
async def test_generate_plan_sets_session_id() -> None:
    planner = Planner()
    plan = await planner.generate_plan(
        session_id="550e8400-e29b-41d4-a716-446655440000",
        task_descriptions=["1. Schema", "2. API"],
    )

    assert str(plan.jour_fixe_session_id) == "550e8400-e29b-41d4-a716-446655440000"
    assert plan.tasks[1].depends_on == [plan.tasks[0].id]
