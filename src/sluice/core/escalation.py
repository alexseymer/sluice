"""Matrix escalation — ask the human when the coordinator cannot proceed alone."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sluice.models.plan import Plan, PlanTask, TaskStatus


@dataclass
class PendingEscalation:
    """One blocked issue waiting on human direction in Matrix."""

    task_id: UUID
    plan_id: UUID
    title: str
    question: str


def find_pending_escalation(plan: Plan | None) -> PendingEscalation | None:
    """Return the first task waiting on human input, if any."""
    if plan is None:
        return None
    for task in plan.tasks:
        if task.status == TaskStatus.NEEDS_INPUT:
            return PendingEscalation(
                task_id=task.id,
                plan_id=plan.id,
                title=task.title,
                question=_question_from_task(task),
            )
    return None


def format_escalation_message(escalation: PendingEscalation) -> str:
    """Human-facing Matrix prompt for an escalation."""
    return (
        f"I need your direction before continuing on: {escalation.title}\n\n"
        f"{escalation.question}\n\n"
        "Reply with guidance (I'll resume with your direction), "
        "`/retry` to try again as-is, or `/skip` to abandon this issue."
    )


def apply_direction(task: PlanTask, direction: str) -> None:
    """Attach human direction and mark the task ready for re-dispatch."""
    note = direction.strip()
    if note:
        block = f"\n\nHuman direction (from Matrix):\n{note}"
        task.description = (task.description or task.title) + block
    task.status = TaskStatus.READY


def mark_skipped(task: PlanTask) -> None:
    """Abandon an escalated issue after the human skips it."""
    task.status = TaskStatus.CANCELLED


def mark_retry(task: PlanTask) -> None:
    """Re-queue an escalated issue without new direction."""
    task.status = TaskStatus.READY


def _question_from_task(task: PlanTask) -> str:
    marker = "Human direction (from Matrix):"
    desc = task.description or ""
    if "Escalation:" in desc:
        # Prefer the last escalation block if present.
        parts = desc.split("Escalation:")
        return parts[-1].strip().split(marker)[0].strip() or (
            "The worker hit a substantial question it couldn't resolve alone."
        )
    return "The worker hit a substantial question it couldn't resolve alone."
