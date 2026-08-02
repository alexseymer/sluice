"""Planner — converts jour fixe conversation into a structured plan."""

from __future__ import annotations

from pathlib import Path

import structlog

from sluice.adapters.backend import BackendAdapter
from sluice.core.planner_llm import generate_plan_heuristic, generate_plan_with_llm
from sluice.models.plan import Plan

log = structlog.get_logger()


class Planner:
    """Generates dependency-ordered issue lists from jour fixe discussion."""

    def __init__(
        self,
        *,
        orchestrator: BackendAdapter | None = None,
        worktree_base: Path | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._worktree_base = worktree_base or Path(".sluice-data/planner")

    async def generate_plan(
        self,
        *,
        session_id: str,
        task_descriptions: list[str],
    ) -> Plan:
        if self._orchestrator is not None:
            self._worktree_base.mkdir(parents=True, exist_ok=True)
            worktree = self._worktree_base / session_id
            worktree.mkdir(parents=True, exist_ok=True)
            shaped = await generate_plan_with_llm(
                backend=self._orchestrator,
                session_id=session_id,
                task_descriptions=task_descriptions,
                worktree=worktree,
            )
            if shaped is not None:
                log.info("orchestrator_plan_shaped", tasks=len(shaped.tasks))
                return shaped
            log.info("orchestrator_shape_fallback_to_heuristics")

        return generate_plan_heuristic(
            session_id=session_id,
            task_descriptions=task_descriptions,
        )

    async def refine_plan(self, plan: Plan, amendments: str) -> Plan:
        """Apply human amendments to a draft plan."""
        extra = [line.strip() for line in amendments.splitlines() if line.strip()]
        if not extra:
            return plan

        amended = generate_plan_heuristic(session_id="", task_descriptions=extra)
        return plan.model_copy(update={"tasks": [*plan.tasks, *amended.tasks]})
