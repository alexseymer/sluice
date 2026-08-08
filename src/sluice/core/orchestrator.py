"""Orchestrator — shapes jour fixe into issues and runs worker/reviewer loops."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import structlog

from sluice.adapters.backend import BackendAdapter
from sluice.models.plan import PlanTask, TaskStatus
from sluice.models.schedule import DispatchResult

log = structlog.get_logger()

_REVIEW_JSON = re.compile(r"\{[\s\S]*\}")
_ESCALATE_RE = re.compile(r"^ESCALATE:\s*(.+)$", re.MULTILINE | re.IGNORECASE)


def extract_escalation(output: str) -> str | None:
    """Return an escalation question if the worker asked for human direction."""
    match = _ESCALATE_RE.search(output or "")
    if match is None:
        return None
    question = match.group(1).strip()
    return question or None


def build_worker_prompt(task: PlanTask, *, review_feedback: str = "") -> str:
    """Prompt for the worker CLI agent implementing an issue."""
    lines = [
        f"Issue: {task.title}",
        "",
        "Description:",
        task.description or task.title,
    ]
    if task.acceptance_criteria:
        lines.extend(["", "Acceptance criteria:", task.acceptance_criteria])
    if review_feedback:
        lines.extend(
            [
                "",
                "Previous review feedback — address before resubmitting:",
                review_feedback,
            ]
        )
    lines.extend(
        [
            "",
            "Implement this issue in the worktree. Make focused changes that satisfy "
            "the acceptance criteria.",
            "",
            "If you hit a substantial product, architecture, or scope question you "
            "cannot resolve from the issue alone, do not guess. Stop and reply with "
            "exactly one line of the form:",
            "ESCALATE: <the question for the human>",
        ]
    )
    return "\n".join(lines)


def build_review_prompt(task: PlanTask, worker_output: str) -> str:
    """Prompt for the reviewer CLI agent checking worker output."""
    criteria = task.acceptance_criteria or "The implementation matches the issue description."
    return f"""You are reviewing work on a GitHub issue before it can be marked done.

Issue: {task.title}

Description:
{task.description or task.title}

Acceptance criteria:
{criteria}

Worker output:
{worker_output}

Respond with ONLY valid JSON:
{{
  "approved": true or false,
  "feedback": "specific gaps if not approved, or brief confirmation if approved"
}}

Rules:
- approved is true only when every acceptance criterion is met.
- feedback must be actionable when approved is false.
"""


def parse_review_output(output: str) -> tuple[bool, str]:
    """Parse reviewer JSON output into (approved, feedback)."""
    match = _REVIEW_JSON.search(output)
    if match is None:
        return False, "Reviewer did not return valid JSON."

    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return False, "Reviewer returned malformed JSON."

    approved = bool(payload.get("approved"))
    feedback = str(payload.get("feedback", "")).strip()
    return approved, feedback


async def execute_task_with_review(
    *,
    worker: BackendAdapter,
    reviewer: BackendAdapter,
    task: PlanTask,
    worktree: Path,
    max_iterations: int,
) -> DispatchResult:
    """Run worker → reviewer loop until criteria pass, escalate, or fail hard."""
    review_feedback = ""
    last_worker: DispatchResult | None = None

    for iteration in range(1, max_iterations + 1):
        task.review_iterations = iteration
        task.status = TaskStatus.IN_PROGRESS

        worker_task = PlanTask(
            id=task.id,
            title=task.title,
            description=build_worker_prompt(task, review_feedback=review_feedback),
        )
        worker_result = await worker.dispatch(worker_task, worktree=worktree)
        last_worker = worker_result

        if worker_result.quota_exceeded or worker_result.fallback_detected:
            task.status = TaskStatus.READY
            return worker_result

        if not worker_result.success:
            task.status = TaskStatus.FAILED
            return worker_result

        escalation = extract_escalation(worker_result.output)
        if escalation:
            return escalate_task(
                task,
                backend_id=worker.adapter_id,
                question=escalation,
                output=worker_result.output,
                completed_at=worker_result.completed_at,
            )

        task.status = TaskStatus.IN_REVIEW
        review_task = PlanTask(
            id=task.id,
            title=f"Review: {task.title}",
            description=build_review_prompt(task, worker_result.output),
        )
        review_result = await reviewer.dispatch(review_task, worktree=worktree)

        if review_result.quota_exceeded or review_result.fallback_detected:
            task.status = TaskStatus.READY
            return review_result

        if not review_result.success:
            task.status = TaskStatus.FAILED
            return DispatchResult(
                task_id=task.id,
                backend_id=review_result.backend_id,
                success=False,
                output=worker_result.output,
                error=review_result.error or "Reviewer dispatch failed",
                completed_at=review_result.completed_at,
            )

        approved, feedback = parse_review_output(review_result.output)
        if approved:
            task.status = TaskStatus.COMPLETED
            log.info(
                "task_review_approved",
                task_id=str(task.id),
                iterations=iteration,
                worker=worker.adapter_id,
                reviewer=reviewer.adapter_id,
            )
            return DispatchResult(
                task_id=task.id,
                backend_id=worker.adapter_id,
                success=True,
                output=worker_result.output,
                completed_at=worker_result.completed_at,
            )

        review_feedback = feedback or "Review did not pass; revise the implementation."
        task.status = TaskStatus.NEEDS_REVISION
        log.info(
            "task_review_revision",
            task_id=str(task.id),
            iteration=iteration,
            feedback=review_feedback[:200],
        )

    question = (
        review_feedback
        if review_feedback
        else f"Acceptance criteria not met after {max_iterations} review iteration(s)"
    )
    return escalate_task(
        task,
        backend_id=last_worker.backend_id if last_worker else worker.adapter_id,
        question=question,
        output=last_worker.output if last_worker else "",
        completed_at=last_worker.completed_at if last_worker else None,
    )


def escalate_task(
    task: PlanTask,
    *,
    backend_id: str,
    question: str,
    output: str,
    completed_at: datetime | None,
) -> DispatchResult:
    """Pause the issue and surface a substantial question to Matrix."""
    note = f"\n\nEscalation:\n{question}"
    base = task.description or task.title
    if "Escalation:" not in base:
        task.description = base + note
    else:
        task.description = base.rsplit("Escalation:", 1)[0].rstrip() + note
    task.status = TaskStatus.NEEDS_INPUT
    log.info(
        "task_needs_input",
        task_id=str(task.id),
        question=question[:200],
    )
    return DispatchResult(
        task_id=task.id,
        backend_id=backend_id,
        success=False,
        output=output,
        error=question,
        needs_input=True,
        escalation_question=question,
        completed_at=completed_at,
    )
