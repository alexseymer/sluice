"""Scheduler — dispatches ready tasks to backends within budget."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import structlog

from sluice.adapters.backend import BackendAdapter
from sluice.core.budget import BudgetManager
from sluice.core.graph import DependencyGraph
from sluice.core.orchestrator import (
    escalate_task,
    execute_task_with_review,
    extract_escalation,
)
from sluice.models.budget import BudgetSnapshot
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
        *,
        reviewer_backend: BackendAdapter | None = None,
        max_review_iterations: int = 3,
        dispatch_poll_seconds: int = 30,
    ) -> None:
        self._backends = backends
        self._budget = budget_manager
        self._worktree_base = worktree_base
        self._default_backend = default_backend
        self._reviewer = reviewer_backend
        self._max_review_iterations = max_review_iterations
        self._dispatch_poll_seconds = max(1, dispatch_poll_seconds)
        self._queue: list[ScheduleSlot] = []
        self._queued_task_ids: set[UUID] = set()

    @property
    def has_pending(self) -> bool:
        return bool(self._queue)

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    async def schedule_plan(self, plan: Plan) -> list[ScheduleSlot]:
        """Enqueue ready tasks that are not already queued."""
        return await self.schedule_ready_tasks(plan)

    async def schedule_ready_tasks(self, plan: Plan) -> list[ScheduleSlot]:
        """Build a dispatch queue from ready tasks in the plan."""
        graph = DependencyGraph(plan)
        graph.validate()
        ready = graph.ready_tasks()
        now = datetime.now(UTC)
        queued_per_backend: dict[str, int] = {}
        for existing in self._queue:
            queued_per_backend[existing.backend_id] = (
                queued_per_backend.get(existing.backend_id, 0) + 1
            )
        snapshots: dict[str, BudgetSnapshot] = {}
        slots: list[ScheduleSlot] = []
        for task in ready:
            if task.id in self._queued_task_ids:
                continue
            backend_id = task.backend_id or await self._pick_backend()
            if backend_id is None:
                log.warning("no_backend_available", task_id=str(task.id))
                continue
            if backend_id not in snapshots:
                snapshots[backend_id] = await self._budget.snapshot(backend_id)
            index = queued_per_backend.get(backend_id, 0)
            slot = ScheduleSlot(
                backend_id=backend_id,
                task_id=task.id,
                scheduled_at=self._pace_scheduled_at(
                    now, snapshots[backend_id], index
                ),
            )
            queued_per_backend[backend_id] = index + 1
            slots.append(slot)
            self._queued_task_ids.add(task.id)
        self._queue.extend(slots)
        return slots

    def _pace_scheduled_at(
        self, now: datetime, snapshot: BudgetSnapshot, index: int
    ) -> datetime:
        """Stagger the index-th slot for a backend across the remaining window."""
        window = snapshot.window
        window_end: datetime | None = None
        if window.window_start is not None:
            start = window.window_start
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            window_end = start + timedelta(seconds=window.window_seconds)
            window_seconds_left = max(0.0, (window_end - now).total_seconds())
        else:
            window_seconds_left = float(window.window_seconds)

        interval = max(
            float(self._dispatch_poll_seconds),
            window_seconds_left / max(1, snapshot.remaining_units),
        )
        scheduled = now + timedelta(seconds=index * interval)
        if window_end is not None and scheduled > window_end:
            return window_end
        return scheduled

    async def _pick_backend(self) -> str | None:
        ranked = await self._budget.rank_available()
        if not ranked:
            return None

        best = ranked[0]
        default = self._default_backend
        if (
            default
            and default in self._backends
            and default in ranked
        ):
            default_snap = await self._budget.snapshot(default)
            best_snap = await self._budget.snapshot(best)
            if default_snap.remaining_units >= best_snap.remaining_units:
                return default
        return best

    def _next_due_slot(self, now: datetime) -> ScheduleSlot | None:
        for slot in self._queue:
            if self._is_due(slot, now):
                return slot
        return None

    def _due_slots_one_per_backend(self, now: datetime) -> list[ScheduleSlot]:
        """Due slots only; at most one per backend (queue order)."""
        selected: list[ScheduleSlot] = []
        seen_backends: set[str] = set()
        for slot in self._queue:
            if not self._is_due(slot, now):
                continue
            if slot.backend_id in seen_backends:
                continue
            seen_backends.add(slot.backend_id)
            selected.append(slot)
        return selected

    @staticmethod
    def _is_due(slot: ScheduleSlot, now: datetime) -> bool:
        scheduled = slot.scheduled_at
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=UTC)
        compare_now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        return scheduled <= compare_now

    async def dispatch_next(self, plan: Plan) -> DispatchResult | None:
        """Dispatch the next due queued task, failing over on quota exhaustion."""
        if not self._queue:
            return None

        slot = self._next_due_slot(datetime.now(UTC))
        if slot is None:
            return None

        result = await self._dispatch_slot(plan, slot)
        if result is not None and not self._should_requeue(result):
            self._dequeue(slot.task_id)
        return result

    async def dispatch_ready_parallel(self, plan: Plan) -> list[DispatchResult]:
        """Dispatch due slots concurrently — at most one per backend per poll."""
        if not self._queue:
            return []

        slots = self._due_slots_one_per_backend(datetime.now(UTC))
        if not slots:
            return []

        results = await asyncio.gather(
            *(self._dispatch_slot(plan, slot) for slot in slots),
            return_exceptions=True,
        )

        dispatched: list[DispatchResult] = []
        for slot, result in zip(slots, results, strict=True):
            if isinstance(result, BaseException):
                log.exception(
                    "parallel_dispatch_failed",
                    task_id=str(slot.task_id),
                    exc=result,
                )
                task = self.find_task(plan, slot.task_id)
                if task is not None:
                    task.status = TaskStatus.FAILED
                self._dequeue(slot.task_id)
                continue
            if result is not None:
                dispatched.append(result)
                if not self._should_requeue(result):
                    self._dequeue(slot.task_id)
        return dispatched

    @staticmethod
    def _should_requeue(result: DispatchResult) -> bool:
        return result.quota_exceeded or result.fallback_detected

    async def _dispatch_slot(self, plan: Plan, slot: ScheduleSlot) -> DispatchResult | None:
        task = self.find_task(plan, slot.task_id)
        if task is None:
            return None

        worktree = self._worktree_base / str(task.id)
        worktree.mkdir(parents=True, exist_ok=True)

        if self._reviewer is not None:
            worker = await self._resolve_worker_backend(task, slot.backend_id)
            if worker is None:
                task.status = TaskStatus.FAILED
                return DispatchResult(
                    task_id=task.id,
                    backend_id=slot.backend_id,
                    success=False,
                    error="No worker backend available",
                )
            return await execute_task_with_review(
                worker=worker,
                reviewer=self._reviewer,
                task=task,
                worktree=worktree,
                max_iterations=self._max_review_iterations,
            )

        return await self._dispatch_single_backend(plan, task, slot, worktree)

    async def _resolve_worker_backend(
        self, task: PlanTask, preferred_id: str
    ) -> BackendAdapter | None:
        if (
            task.backend_id
            and task.backend_id in self._backends
            and await self._budget.can_dispatch(task.backend_id)
        ):
            return self._backends[task.backend_id]
        if preferred_id in self._backends and await self._budget.can_dispatch(preferred_id):
            return self._backends[preferred_id]
        for backend_id in await self._budget.available_backends():
            return self._backends[backend_id]
        return None

    async def _dispatch_single_backend(
        self,
        plan: Plan,
        task: PlanTask,
        slot: ScheduleSlot,
        worktree: Path,
    ) -> DispatchResult | None:
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

            escalation = extract_escalation(result.output)
            if escalation:
                return escalate_task(
                    task,
                    backend_id=backend_id,
                    question=escalation,
                    output=result.output,
                    completed_at=result.completed_at,
                )

            task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
            task.backend_id = backend_id
            return result

        if last_result is not None and last_result.fallback_detected:
            task.status = TaskStatus.READY
            return last_result

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
