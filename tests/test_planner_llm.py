"""Tests for LLM planner parsing."""

from __future__ import annotations

from sluice.core.planner_llm import _parse_plan_output


def test_parse_plan_output_with_dependencies() -> None:
    output = """
    Here is the plan:
    {
      "tasks": [
        {"title": "Schema", "description": "Design DB schema"},
        {"title": "API client", "depends_on": ["Schema"]}
      ]
    }
    """

    plan = _parse_plan_output(output, session_id="550e8400-e29b-41d4-a716-446655440000")

    assert plan is not None
    assert len(plan.tasks) == 2
    assert plan.tasks[1].depends_on == [plan.tasks[0].id]
    assert plan.tasks[0].backend_id is None
    assert plan.tasks[1].backend_id is None


def test_parse_plan_output_rejects_invalid_json() -> None:
    assert _parse_plan_output("not json", session_id="") is None


def test_parse_plan_output_keeps_enabled_backend_id() -> None:
    output = """
    {
      "tasks": [
        {"title": "Schema", "backend_id": "cursor"},
        {"title": "API", "backend_id": "agy"}
      ]
    }
    """
    plan = _parse_plan_output(
        output,
        session_id="",
        enabled_backends=["cursor", "agy"],
    )

    assert plan is not None
    assert plan.tasks[0].backend_id == "cursor"
    assert plan.tasks[1].backend_id == "agy"


def test_parse_plan_output_drops_invalid_or_missing_backend_id() -> None:
    output = """
    {
      "tasks": [
        {"title": "Schema", "backend_id": "unknown"},
        {"title": "API", "backend_id": null},
        {"title": "Docs"}
      ]
    }
    """
    plan = _parse_plan_output(
        output,
        session_id="",
        enabled_backends=["cursor"],
    )

    assert plan is not None
    assert all(task.backend_id is None for task in plan.tasks)