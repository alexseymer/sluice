"""Tests for the dependency graph engine."""

from uuid import uuid4

import pytest

from sluice.core.graph import DependencyGraph, DependencyGraphError
from sluice.models.plan import Plan, PlanTask, TaskStatus


def test_ready_tasks_with_no_dependencies() -> None:
    task = PlanTask(title="Do thing")
    plan = Plan(tasks=[task])
    graph = DependencyGraph(plan)
    graph.validate()
    assert graph.ready_tasks() == [task]


def test_ready_tasks_waits_for_blockers() -> None:
    blocker = PlanTask(title="Schema", status=TaskStatus.IN_PROGRESS)
    blocked = PlanTask(title="API client", depends_on=[blocker.id])
    plan = Plan(tasks=[blocker, blocked])
    graph = DependencyGraph(plan)
    graph.validate()
    ready = graph.ready_tasks()
    assert blocked not in ready
    assert ready == []


def test_circular_dependency_raises() -> None:
    a_id, b_id = uuid4(), uuid4()
    a = PlanTask(id=a_id, title="A", depends_on=[b_id])
    b = PlanTask(id=b_id, title="B", depends_on=[a_id])
    plan = Plan(tasks=[a, b])
    graph = DependencyGraph(plan)
    with pytest.raises(DependencyGraphError, match="Circular"):
        graph.validate()
