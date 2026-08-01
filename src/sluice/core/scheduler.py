"""Scheduler — dispatches ready tasks to backends within budget."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import structlog

from sluice.adapters.backend import BackendAdapter
from sluice.core.budget import BudgetManager
from sluice.core.graph import DependencyGraph
from sluice.models.plan import Plan, PlanTask, TaskStatus
from sluice.models.schedule import DispatchResult, ScheduleSlot

log = structlog.get_logger()


class Scheduler:
    """Spreads ready (unblocked) tasks across schedule slots."""

    def __init__(
        self,
        backends: dict[str, BackendAdapter],
        budget_manager: BudgetManager,
        worktree_base: Path,
    ) -> None:
        self._backends = backends
        self._budget = budget_manager
        self._worktree_base = worktree_base
        self._queue: list[ScheduleSlot] = []

    async def schedule_plan(self, plan: Plan) -> list[ScheduleSlot]:
        """Build a dispatch queue from ready tasks in the plan."""
        graph = DependencyGraph(plan)
        graph.validate()
        ready = graph.ready_tasks()
        slots: list[ScheduleSlot] = []
        for task in ready:
            backend_id = task.backend_id or next(iter(self._backends))
            slot = ScheduleSlot(
                backend_id=backend_id,
                task_id=task.id,
                scheduled_at=plan.created_at,
            )
            slots.append(slot)
        self._queue.extend(slots)
        return slots

    async def dispatch_next(self, plan: Plan) -> DispatchResult | None:
        """Dispatch the next queued task if budget allows."""
        if not self._queue:
            return None

        slot = self._queue[0]
        if not await self._budget.can_dispatch(slot.backend_id):
            log.info("budget_exhausted", backend=slot.backend_id)
            return None

        task = self._find_task(plan, slot.task_id)
        if task is None:
            self._queue.pop(0)
            return None

        backend = self._backends[slot.backend_id]
        worktree = self._worktree_base / str(task.id)
        worktree.mkdir(parents=True, exist_ok=True)

        task.status = TaskStatus.IN_PROGRESS
        result = await backend.dispatch(task, worktree=worktree)
        self._queue.pop(0)

        task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
        return result

    @staticmethod
    def _find_task(plan: Plan, task_id: UUID) -> PlanTask | None:
        for task in plan.tasks:
            if task.id == task_id:
                return task
        return None
