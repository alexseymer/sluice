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
        default_backend: str | None = None,
    ) -> None:
        self._backends = backends
        self._budget = budget_manager
        self._worktree_base = worktree_base
        self._default_backend = default_backend
        self._queue: list[ScheduleSlot] = []
        self._queued_task_ids: set[UUID] = set()

    @property
    def has_pending(self) -> bool:
        return bool(self._queue)

    async def schedule_plan(self, plan: Plan) -> list[ScheduleSlot]:
        """Enqueue ready tasks that are not already queued."""
        return await self.schedule_ready_tasks(plan)

    async def schedule_ready_tasks(self, plan: Plan) -> list[ScheduleSlot]:
        """Build a dispatch queue from ready tasks in the plan."""
        graph = DependencyGraph(plan)
        graph.validate()
        ready = graph.ready_tasks()
        slots: list[ScheduleSlot] = []
        for task in ready:
            if task.id in self._queued_task_ids:
                continue
            backend_id = task.backend_id or await self._pick_backend()
            if backend_id is None:
                log.warning("no_backend_available", task_id=str(task.id))
                continue
            slot = ScheduleSlot(
                backend_id=backend_id,
                task_id=task.id,
                scheduled_at=plan.created_at,
            )
            slots.append(slot)
            self._queued_task_ids.add(task.id)
        self._queue.extend(slots)
        return slots

    async def _pick_backend(self) -> str | None:
        if (
            self._default_backend
            and self._default_backend in self._backends
            and await self._budget.can_dispatch(self._default_backend)
        ):
            return self._default_backend

        available = await self._budget.available_backends()
        return available[0] if available else None

    async def dispatch_next(self, plan: Plan) -> DispatchResult | None:
        """Dispatch the next queued task, failing over on quota exhaustion."""
        if not self._queue:
            return None

        slot = self._queue[0]
        task = self.find_task(plan, slot.task_id)
        if task is None:
            self._dequeue(slot.task_id)
            return None

        worktree = self._worktree_base / str(task.id)
        worktree.mkdir(parents=True, exist_ok=True)
        task.status = TaskStatus.IN_PROGRESS

        preferred = [slot.backend_id] if slot.backend_id in self._backends else []
        candidates = preferred + [
            backend_id
            for backend_id in await self._budget.available_backends()
            if backend_id not in preferred
        ]

        last_result: DispatchResult | None = None
        for backend_id in candidates:
            if not await self._budget.can_dispatch(backend_id):
                continue

            backend = self._backends[backend_id]
            result = await backend.dispatch(task, worktree=worktree)
            last_result = result

            if result.quota_exceeded:
                log.warning(
                    "backend_quota_failover",
                    from_backend=backend_id,
                    task_id=str(task.id),
                )
                continue

            if result.fallback_detected:
                log.warning(
                    "backend_fallback_failover",
                    from_backend=backend_id,
                    task_id=str(task.id),
                )
                continue

            self._dequeue(slot.task_id)
            task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
            task.backend_id = backend_id
            return result

        if last_result is not None and last_result.fallback_detected:
            task.status = TaskStatus.READY
            return last_result

        self._dequeue(slot.task_id)
        task.status = TaskStatus.FAILED
        return last_result

    def _dequeue(self, task_id: UUID) -> None:
        if self._queue and self._queue[0].task_id == task_id:
            self._queue.pop(0)
        else:
            self._queue = [slot for slot in self._queue if slot.task_id != task_id]
        self._queued_task_ids.discard(task_id)

    @staticmethod
    def find_task(plan: Plan, task_id: UUID) -> PlanTask | None:
        for task in plan.tasks:
            if task.id == task_id:
                return task
        return None
