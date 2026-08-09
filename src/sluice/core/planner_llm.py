"""LLM-backed plan generation from jour fixe conversation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import UUID

import structlog

from sluice.adapters.backend import BackendAdapter
from sluice.core.planner_inference import build_tasks_with_dependencies
from sluice.models.plan import Plan, PlanTask

log = structlog.get_logger()

_ORCHESTRATOR_SHAPE_PROMPT = """You are Sluice's orchestrator — the primary AI agent that turns a
jour fixe meeting into a GitHub-issue-backed execution plan.

Issues are the backbone of the plan. Shape them for best practice before any work starts:
- Group related changes into one issue when they ship together.
- Split only when work is genuinely independent or must land separately.
- Each issue should be completable by a specialist CLI agent in one focused session.
- Write clear acceptance criteria so a separate reviewer agent can verify completion.

Enabled worker backends (optional assignment): {enabled_backends}
Use backend_id only when a specific CLI clearly fits; otherwise null/omit for auto-assign.

Transcript:
{conversation}

Respond with ONLY valid JSON in this shape:
{{
  "summary": "2-4 sentence human overview of goals and approach",
  "tasks": [
    {{
      "title": "concise issue title",
      "description": "context and scope for the worker agent",
      "acceptance_criteria": "bullet list of testable done conditions",
      "depends_on": ["exact title of blocker issue"],
      "backend_id": "cursor"
    }}
  ]
}}

Rules:
- Prefer what was agreed in discussion over abandoned ideas.
- Use depends_on only when one issue must finish before another starts.
- Omit depends_on or use an empty list when there are no blockers.
- Parallelizable issues should share the same blockers, not depend on each other.
- backend_id must be one of the enabled backends listed above, or null/omitted for auto.
- Ignore slash-command noise and meta talk about Sluice itself.
"""

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


async def generate_plan_with_llm(
    *,
    backend: BackendAdapter,
    session_id: str,
    task_descriptions: list[str],
    worktree: Path,
    enabled_backends: list[str] | None = None,
) -> Plan | None:
    """Ask the orchestrator backend to shape jour fixe output into issues."""
    if not task_descriptions:
        return Plan(jour_fixe_session_id=_session_uuid(session_id))

    backends = list(enabled_backends or [])
    backends_label = (
        ", ".join(backends) if backends else "(none configured — leave backend_id null)"
    )
    conversation = "\n".join(task_descriptions)
    prompt = _ORCHESTRATOR_SHAPE_PROMPT.format(
        conversation=conversation,
        enabled_backends=backends_label,
    )
    planning_task = PlanTask(title="jour-fixe-orchestration", description=prompt)

    result = await backend.dispatch(planning_task, worktree=worktree)
    if not result.success or not result.output.strip():
        log.warning(
            "orchestrator_shape_failed",
            backend_id=result.backend_id,
            error=result.error,
        )
        return None

    plan = _parse_plan_output(
        result.output,
        session_id=session_id,
        enabled_backends=backends,
    )
    if plan is None:
        log.warning("orchestrator_shape_parse_failed", backend_id=result.backend_id)
    return plan


def _parse_backend_id(raw: object, *, enabled: set[str]) -> str | None:
    """Keep only enabled backend IDs; invalid/missing → None (auto)."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate or candidate.lower() in {"null", "none", "auto"}:
        return None
    if candidate in enabled:
        return candidate
    return None


def _parse_plan_output(
    output: str,
    *,
    session_id: str,
    enabled_backends: list[str] | None = None,
) -> Plan | None:
    match = _JSON_BLOCK.search(output)
    if match is None:
        return None

    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return None

    enabled = set(enabled_backends or [])
    tasks: list[PlanTask] = []
    tasks_by_title: dict[str, PlanTask] = {}

    for item in raw_tasks:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        description = str(item.get("description", title)).strip() or title
        acceptance = str(item.get("acceptance_criteria", "")).strip()
        backend_id = _parse_backend_id(item.get("backend_id"), enabled=enabled)
        task = PlanTask(
            title=title,
            description=description,
            acceptance_criteria=acceptance,
            backend_id=backend_id,
        )
        tasks.append(task)
        tasks_by_title[title.lower()] = task

    if not tasks:
        return None

    for item in raw_tasks:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip().lower()
        task = tasks_by_title.get(title)
        if task is None:
            continue
        depends_on = item.get("depends_on", [])
        if not isinstance(depends_on, list):
            continue
        for dep_title in depends_on:
            dep_key = str(dep_title).strip().lower()
            blocker = tasks_by_title.get(dep_key)
            if blocker is not None and blocker.id not in task.depends_on:
                task.depends_on.append(blocker.id)

    summary_raw = payload.get("summary")
    summary = str(summary_raw).strip() if summary_raw else None
    return Plan(
        tasks=tasks,
        jour_fixe_session_id=_session_uuid(session_id),
        summary=summary or None,
    )


def _human_task_lines(task_descriptions: list[str]) -> list[str]:
    """Drop assistant turns and role prefixes for heuristic planning."""
    lines: list[str] = []
    for raw in task_descriptions:
        text = raw.strip()
        if not text:
            continue
        lower = text.lower()
        if lower.startswith("assistant:"):
            continue
        if lower.startswith("human:"):
            text = text.split(":", maxsplit=1)[1].strip()
        if text:
            lines.append(text)
    return lines


def generate_plan_heuristic(
    *,
    session_id: str,
    task_descriptions: list[str],
) -> Plan:
    tasks = build_tasks_with_dependencies(_human_task_lines(task_descriptions))
    return Plan(tasks=tasks, jour_fixe_session_id=_session_uuid(session_id))


def _session_uuid(session_id: str) -> UUID | None:
    if not session_id:
        return None
    return UUID(session_id)
