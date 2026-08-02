"""Background dispatch loop — runs approved plan tasks through AI backends."""

from __future__ import annotations

import asyncio

import structlog

from sluice.adapters.chat import OutgoingMessage
from sluice.core.app import SluiceApp
from sluice.core.forge_sync import close_forge_issue_for_task
from sluice.core.scheduler import Scheduler
from sluice.models.plan import Plan, plan_is_complete
from sluice.models.schedule import DispatchResult

log = structlog.get_logger()


async def on_plan_approved(app: SluiceApp, plan: Plan) -> None:
    """Schedule ready tasks and begin background dispatch for an approved plan."""
    app.active_plan = plan
    slots = await app.scheduler.schedule_plan(plan)
    await app.store.save_plan(plan)
    log.info("plan_scheduled", plan_id=str(plan.id), slots=len(slots))
    if slots and app.chat.is_configured:
        await app.chat.send(
            OutgoingMessage(
                text=f"Plan approved. Scheduled {len(slots)} task(s) for dispatch."
            )
        )


async def run_dispatch_loop(app: SluiceApp) -> None:
    """Poll the scheduler and dispatch queued tasks within budget."""
    poll_seconds = max(1, app.settings.dispatch_poll_seconds)
    log.info("dispatch_loop_started", poll_seconds=poll_seconds)

    while True:
        plan = app.active_plan
        if plan is not None:
            if app.scheduler.has_pending:
                result = await app.scheduler.dispatch_next(plan)
                if result is not None:
                    await _notify_dispatch_result(app, plan, result)
                    await app.scheduler.schedule_ready_tasks(plan)
                    await app.store.save_plan(plan)

            if plan_is_complete(plan) and not app.scheduler.has_pending:
                log.info("plan_dispatch_complete", plan_id=str(plan.id))
                app.active_plan = None

        await asyncio.sleep(poll_seconds)


async def _notify_dispatch_result(
    app: SluiceApp, plan: Plan, result: DispatchResult
) -> None:
    task = Scheduler.find_task(plan, result.task_id)
    title = task.title if task is not None else str(result.task_id)

    if result.success:
        message = f"Task completed: {title} ({result.backend_id})"
        log.info(
            "task_dispatched",
            task_id=str(result.task_id),
            backend_id=result.backend_id,
            success=True,
        )
        if task is not None:
            await close_forge_issue_for_task(app, task)
    elif result.quota_exceeded:
        message = f"Task deferred (quota): {title} on {result.backend_id}"
        log.warning(
            "task_quota_deferred",
            task_id=str(result.task_id),
            backend_id=result.backend_id,
        )
    else:
        message = f"Task failed: {title} ({result.backend_id})"
        if result.error:
            message = f"{message} — {result.error}"
        log.warning(
            "task_dispatch_failed",
            task_id=str(result.task_id),
            backend_id=result.backend_id,
            error=result.error,
        )

    if app.chat.is_configured:
        await app.chat.send(OutgoingMessage(text=message))
