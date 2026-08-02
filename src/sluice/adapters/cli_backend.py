"""Shared subprocess runner for AI CLI backends."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog

from sluice.adapters.backend import BackendAdapter
from sluice.models.budget import BudgetSnapshot, BudgetWindow
from sluice.models.plan import PlanTask
from sluice.models.schedule import DispatchResult
from sluice.store.sqlite import SQLiteStateStore

log = structlog.get_logger()

FALLBACK_OUTPUT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"rate.?limit",
        r"quota.?exceeded",
        r"usage.?limit",
        r"fallback",
        r"degraded.?model",
        r"try again later",
    )
)


@dataclass(frozen=True)
class CLIInvocation:
    """Resolved CLI command to execute for a task."""

    command: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 3600


class CLIBackendAdapter(BackendAdapter):
    """Base adapter that dispatches tasks by running a headless CLI subprocess."""

    def __init__(
        self,
        *,
        adapter_id: str,
        cli_path: str,
        max_requests_per_window: int,
        window_seconds: int,
        safety_margin: float = 0.85,
        store: SQLiteStateStore | None = None,
        dispatch_timeout_seconds: int = 3600,
    ) -> None:
        self._adapter_id = adapter_id
        self._cli_path = cli_path
        self._max_requests = max_requests_per_window
        self._window_seconds = window_seconds
        self._safety_margin = safety_margin
        self._store = store
        self._dispatch_timeout_seconds = dispatch_timeout_seconds
        self._used_units = 0
        self._window_start = self._current_window_start()
        self._running_tasks: dict[str, asyncio.subprocess.Process] = {}

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def cli_path(self) -> str:
        return self._cli_path

    async def initialize(self) -> None:
        await self._load_usage()

    async def dispatch(self, task: PlanTask, *, worktree: Path) -> DispatchResult:
        worktree.mkdir(parents=True, exist_ok=True)
        invocation = self.build_invocation(task, worktree)
        command = [self._cli_path, *invocation.command]

        log.info(
            "backend_dispatch_start",
            backend=self._adapter_id,
            task_id=str(task.id),
            worktree=str(worktree),
            command=command,
        )

        env = os.environ.copy()
        env.update(invocation.env)

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=invocation.cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._running_tasks[str(task.id)] = process

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=invocation.timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return DispatchResult(
                task_id=task.id,
                backend_id=self._adapter_id,
                success=False,
                error=f"CLI timed out after {invocation.timeout_seconds}s",
                completed_at=datetime.now(UTC),
            )
        finally:
            self._running_tasks.pop(str(task.id), None)

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        combined = "\n".join(part for part in (stdout, stderr) if part)
        fallback_detected = self._detect_fallback(combined)
        success = process.returncode == 0 and not fallback_detected

        if success:
            await self._record_dispatch()

        return DispatchResult(
            task_id=task.id,
            backend_id=self._adapter_id,
            success=success,
            output=combined,
            error=None if success else stderr or stdout or f"exit code {process.returncode}",
            fallback_detected=fallback_detected,
            completed_at=datetime.now(UTC),
        )

    async def get_budget(self) -> BudgetSnapshot:
        await self._refresh_window_if_needed()
        window = self.default_budget_window()
        used = self._used_units
        exhausted = used >= window.effective_limit
        return BudgetSnapshot(
            backend_id=self._adapter_id,
            used_units=used,
            window=window,
            is_exhausted=exhausted,
        )

    async def detect_fallback(self) -> bool:
        return False

    async def cancel(self, task_id: str) -> None:
        process = self._running_tasks.get(task_id)
        if process is None:
            return
        process.kill()
        await process.communicate()
        self._running_tasks.pop(task_id, None)

    def default_budget_window(self) -> BudgetWindow:
        return BudgetWindow(
            backend_id=self._adapter_id,
            window_seconds=self._window_seconds,
            max_units=self._max_requests,
            safety_margin=self._safety_margin,
            window_start=self._window_start,
        )

    def build_invocation(self, task: PlanTask, worktree: Path) -> CLIInvocation:
        raise NotImplementedError

    @staticmethod
    def build_task_prompt(task: PlanTask) -> str:
        if task.description and task.description != task.title:
            return f"{task.title}\n\n{task.description}"
        return task.title

    def _detect_fallback(self, output: str) -> bool:
        return any(pattern.search(output) for pattern in FALLBACK_OUTPUT_PATTERNS)

    def _current_window_start(self) -> datetime:
        now = datetime.now(UTC)
        epoch = int(now.timestamp())
        window_start_epoch = epoch - (epoch % self._window_seconds)
        return datetime.fromtimestamp(window_start_epoch, tz=UTC)

    async def _refresh_window_if_needed(self) -> None:
        current = self._current_window_start()
        if current != self._window_start:
            self._window_start = current
            self._used_units = 0
            await self._load_usage()

    async def _load_usage(self) -> None:
        if self._store is None:
            return
        used = await self._store.get_budget_usage(
            self._adapter_id,
            self._window_start.isoformat(),
        )
        self._used_units = used

    async def _record_dispatch(self) -> None:
        self._used_units += 1
        if self._store is None:
            return
        await self._store.record_budget_usage(
            self._adapter_id,
            self._window_start.isoformat(),
            self._used_units,
        )
