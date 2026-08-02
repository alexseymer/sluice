"""Dependency graph engine — DAG validation and ready-task queries."""

from __future__ import annotations

from uuid import UUID

from sluice.models.plan import Plan, PlanTask, TaskStatus


class DependencyGraphError(Exception):
    """Raised when the dependency graph is invalid."""


class DependencyGraph:
    """Forge-agnostic DAG of plan tasks."""

    def __init__(self, plan: Plan) -> None:
        self._plan = plan
        self._tasks_by_id = {task.id: task for task in plan.tasks}

    def validate(self) -> None:
        """Detect unknown dependencies and circular references."""
        for task in self._plan.tasks:
            for dep_id in task.depends_on:
                if dep_id not in self._tasks_by_id:
                    msg = f"Task {task.id} depends on unknown task {dep_id}"
                    raise DependencyGraphError(msg)

        visited: set[UUID] = set()
        stack: set[UUID] = set()

        def visit(task_id: UUID) -> None:
            if task_id in stack:
                raise DependencyGraphError(f"Circular dependency detected at task {task_id}")
            if task_id in visited:
                return
            stack.add(task_id)
            for dep_id in self._tasks_by_id[task_id].depends_on:
                visit(dep_id)
            stack.remove(task_id)
            visited.add(task_id)

        for task in self._plan.tasks:
            visit(task.id)

    def ready_tasks(self) -> list[PlanTask]:
        """Return tasks whose blockers are all completed."""
        completed = {t.id for t in self._plan.tasks if t.status == TaskStatus.COMPLETED}
        ready: list[PlanTask] = []
        for task in self._plan.tasks:
            if task.status not in (TaskStatus.PENDING, TaskStatus.READY):
                continue
            if all(dep_id in completed for dep_id in task.depends_on):
                ready.append(task)
        return ready

    def blocked_tasks(self) -> list[PlanTask]:
        """Return tasks waiting on incomplete blockers."""
        ready_ids = {t.id for t in self.ready_tasks()}
        return [
            t
            for t in self._plan.tasks
            if t.status in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.BLOCKED)
            and t.id not in ready_ids
        ]
