"""Planner — converts jour fixe conversation into a structured plan."""

from __future__ import annotations

from sluice.models.plan import Plan, PlanTask


class Planner:
    """Generates dependency-ordered task lists from jour fixe discussion.

    Phase 1 stub: accepts a list of task descriptions and returns a flat plan.
    Future: LLM-driven conversation analysis with dependency inference.
    """

    async def generate_plan(
        self,
        *,
        session_id: str,
        task_descriptions: list[str],
    ) -> Plan:
        tasks = [PlanTask(title=desc, description=desc) for desc in task_descriptions]
        return Plan(tasks=tasks, jour_fixe_session_id=None)

    async def refine_plan(self, plan: Plan, amendments: str) -> Plan:
        """Apply human amendments to a draft plan (stub)."""
        return plan
