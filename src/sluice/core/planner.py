"""Planner — converts jour fixe conversation into a structured plan."""

from __future__ import annotations

from uuid import UUID

from sluice.core.planner_inference import build_tasks_with_dependencies
from sluice.models.plan import Plan


class Planner:
    """Generates dependency-ordered task lists from jour fixe discussion."""

    async def generate_plan(
        self,
        *,
        session_id: str,
        task_descriptions: list[str],
    ) -> Plan:
        tasks = build_tasks_with_dependencies(task_descriptions)
        session_uuid = UUID(session_id) if session_id else None
        return Plan(tasks=tasks, jour_fixe_session_id=session_uuid)

    async def refine_plan(self, plan: Plan, amendments: str) -> Plan:
        """Apply human amendments to a draft plan."""
        extra = [line.strip() for line in amendments.splitlines() if line.strip()]
        if not extra:
            return plan

        new_tasks = build_tasks_with_dependencies(extra)
        return plan.model_copy(update={"tasks": [*plan.tasks, *new_tasks]})
