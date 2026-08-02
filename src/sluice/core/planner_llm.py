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

_PLANNER_PROMPT = """You are a work planner.
Convert the jour fixe discussion below into a JSON plan.

Discussion:
{conversation}

Respond with ONLY valid JSON in this shape:
{{
  "tasks": [
    {{
      "title": "short task title",
      "description": "optional longer description",
      "depends_on": ["exact title of blocker task"]
    }}
  ]
}}

Rules:
- Each task should be issue-sized (completable in one AI coding session).
- Use depends_on only when one task must finish before another starts.
- Omit depends_on or use an empty list when there are no blockers.
"""

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


async def generate_plan_with_llm(
    *,
    backend: BackendAdapter,
    session_id: str,
    task_descriptions: list[str],
    worktree: Path,
) -> Plan | None:
    """Ask an AI backend to structure the jour fixe discussion."""
    if not task_descriptions:
        return Plan(jour_fixe_session_id=_session_uuid(session_id))

    conversation = "\n".join(task_descriptions)
    prompt = _PLANNER_PROMPT.format(conversation=conversation)
    planning_task = PlanTask(title="jour-fixe-planning", description=prompt)

    result = await backend.dispatch(planning_task, worktree=worktree)
    if not result.success or not result.output.strip():
        log.warning(
            "llm_planner_dispatch_failed",
            backend_id=result.backend_id,
            error=result.error,
        )
        return None

    plan = _parse_plan_output(result.output, session_id=session_id)
    if plan is None:
        log.warning("llm_planner_parse_failed", backend_id=result.backend_id)
    return plan


def _parse_plan_output(output: str, *, session_id: str) -> Plan | None:
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

    tasks: list[PlanTask] = []
    tasks_by_title: dict[str, PlanTask] = {}

    for item in raw_tasks:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        description = str(item.get("description", title)).strip() or title
        task = PlanTask(title=title, description=description)
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

    return Plan(tasks=tasks, jour_fixe_session_id=_session_uuid(session_id))


def generate_plan_heuristic(
    *,
    session_id: str,
    task_descriptions: list[str],
) -> Plan:
    tasks = build_tasks_with_dependencies(task_descriptions)
    return Plan(tasks=tasks, jour_fixe_session_id=_session_uuid(session_id))


def _session_uuid(session_id: str) -> UUID | None:
    if not session_id:
        return None
    return UUID(session_id)
