"""Heuristic dependency inference for jour fixe task lists."""

from __future__ import annotations

import re
from uuid import UUID

from sluice.models.plan import PlanTask

_COMMAND_PREFIX = re.compile(r"^/\w+")
_NUMBERED_LINE = re.compile(r"^\s*(?:\d+[\).\]]\s*|-\s*)")
_DEPENDENCY_PATTERNS = (
    re.compile(r"\bdepends?\s+on\s+(.+?)(?:[,.;)]|$)", re.IGNORECASE),
    re.compile(r"\bafter\s+(.+?)(?:[,.;)]|$)", re.IGNORECASE),
    re.compile(r"\bblocked\s+by\s+(.+?)(?:[,.;)]|$)", re.IGNORECASE),
)
_TASK_NUMBER = re.compile(r"\b(?:task\s*)?#?(\d+)\b", re.IGNORECASE)


def build_tasks_with_dependencies(descriptions: list[str]) -> list[PlanTask]:
    """Turn jour fixe lines into tasks with inferred dependencies."""
    entries: list[tuple[str, str]] = []
    for raw in descriptions:
        cleaned = _clean_line(raw)
        if not cleaned or _COMMAND_PREFIX.match(cleaned):
            continue
        entries.append((raw, cleaned))

    if not entries:
        return []

    tasks = [PlanTask(title=cleaned, description=cleaned) for _, cleaned in entries]
    for index, ((raw, _), task) in enumerate(zip(entries, tasks, strict=True)):
        explicit = _explicit_dependencies(raw, tasks, current_index=index)
        if explicit:
            task.depends_on = explicit
            continue

        if _NUMBERED_LINE.match(raw) and index > 0:
            task.depends_on = [tasks[index - 1].id]

    return tasks


def _clean_line(line: str) -> str:
    cleaned = line.strip()
    cleaned = _NUMBERED_LINE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -")


def _explicit_dependencies(
    line: str,
    tasks: list[PlanTask],
    *,
    current_index: int,
) -> list[UUID]:
    refs: list[str] = []
    for pattern in _DEPENDENCY_PATTERNS:
        match = pattern.search(line)
        if match:
            refs.append(match.group(1).strip())

    for match in _TASK_NUMBER.finditer(line):
        refs.append(match.group(1))

    if not refs:
        return []

    dependencies: list[UUID] = []
    for ref in refs:
        cleaned_ref = ref.strip().strip(")").strip()
        dep_id = _resolve_reference(cleaned_ref, tasks, current_index=current_index)
        if dep_id is not None and dep_id not in dependencies:
            dependencies.append(dep_id)
    return dependencies


def _resolve_reference(
    reference: str,
    tasks: list[PlanTask],
    *,
    current_index: int,
) -> UUID | None:
    if reference.isdigit():
        task_index = int(reference) - 1
        if 0 <= task_index < len(tasks) and task_index != current_index:
            return tasks[task_index].id

    lowered = reference.lower()
    for index, task in enumerate(tasks):
        if index == current_index:
            continue
        title = task.title.lower()
        if lowered in title or title in lowered:
            return task.id
    return None
