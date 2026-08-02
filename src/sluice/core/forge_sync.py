"""Forge status sync — reflect external issue changes in the active plan."""

from __future__ import annotations

import asyncio

import structlog

from sluice.core.app import SluiceApp
from sluice.models.issue import IssueStatus
from sluice.models.plan import PlanTask, TaskStatus, plan_is_complete

log = structlog.get_logger()

_TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}


async def run_forge_sync_loop(app: SluiceApp) -> None:
    """Poll the forge and keep active-plan task statuses in sync."""
    poll_seconds = max(1, app.settings.forge_sync_poll_seconds)
    log.info("forge_sync_started", poll_seconds=poll_seconds)

    while True:
        await sync_forge_status(app)
        await asyncio.sleep(poll_seconds)


async def sync_forge_status(app: SluiceApp) -> None:

    plan = app.active_plan
    if plan is None or not _forge_is_ready(app):
        return

    changed = False
    for task in plan.tasks:
        if not task.forge_issue_id or task.status in _TERMINAL_TASK_STATUSES:
            continue

        issue = await app.forge.get_issue(task.forge_issue_id)
        if issue.status == IssueStatus.CLOSED and task.status != TaskStatus.COMPLETED:
            task.status = TaskStatus.COMPLETED
            changed = True
            log.info(
                "forge_issue_closed",
                task_id=str(task.id),
                issue_id=task.forge_issue_id,
            )

    if not changed:
        return

    await app.scheduler.schedule_ready_tasks(plan)
    await app.store.save_plan(plan)

    if plan_is_complete(plan) and not app.scheduler.has_pending:
        log.info("plan_dispatch_complete", plan_id=str(plan.id), source="forge_sync")
        app.active_plan = None


async def close_forge_issue_for_task(app: SluiceApp, task: PlanTask) -> None:
    """Close the linked forge issue after successful dispatch."""
    if not task.forge_issue_id or not _forge_is_ready(app):
        return

    await app.forge.set_status(task.forge_issue_id, IssueStatus.CLOSED)
    log.info("forge_issue_closed_by_dispatch", issue_id=task.forge_issue_id, task_id=str(task.id))


def _forge_is_ready(app: SluiceApp) -> bool:
    is_configured = getattr(app.forge, "is_configured", None)
    if callable(is_configured):
        return bool(is_configured())
    return True
