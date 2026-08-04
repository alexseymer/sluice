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

QUOTA_OUTPUT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"rate.?limit",
        r"quota.?exceeded",
        r"usage.?limit",
        r"too many requests",
        r"try again later",
    )
)

FALLBACK_OUTPUT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"fallback",
        r"degraded.?model",
        r"weaker model",
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
        cautious_limit: int,
        window_seconds: int,
        store: SQLiteStateStore | None = None,
        dispatch_timeout_seconds: int = 3600,
    ) -> None:
        self._adapter_id = adapter_id
        self._cli_path = cli_path
        self._cautious_limit = cautious_limit
        self._window_seconds = window_seconds
        self._store = store
        self._dispatch_timeout_seconds = dispatch_timeout_seconds
        self._window_start = self._current_window_start()
        self._running_tasks: dict[str, asyncio.subprocess.Process] = {}
        self._fallback_latched = False

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def cli_path(self) -> str:
        return self._cli_path

    @property
    def cautious_limit(self) -> int:
        return self._cautious_limit

    async def initialize(self) -> None:
        return

    async def dispatch(self, task: PlanTask, *, worktree: Path) -> DispatchResult:
        if not await self._has_headroom():
            return DispatchResult(
                task_id=task.id,
                backend_id=self._adapter_id,
                success=False,
                error="Backend budget exhausted for current window",
                quota_exceeded=True,
                completed_at=datetime.now(UTC),
            )

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

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=invocation.cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            log.error(
                "backend_cli_not_found",
                backend=self._adapter_id,
                cli_path=self._cli_path,
            )
            return DispatchResult(
                task_id=task.id,
                backend_id=self._adapter_id,
                success=False,
                error=(
                    f"CLI not found: {self._cli_path!r}. "
                    "Sluice installs enabled backends on startup — check Matrix "
                    "for login prompts or say /cli-auth."
                ),
                completed_at=datetime.now(UTC),
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
            await self._record_attempt()
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
        state = await self._record_attempt()
        quota_exceeded = self._detect_quota_exceeded(combined)
        fallback_detected = self._detect_fallback(combined)

        if quota_exceeded:
            await self._record_quota_failure(state.used_units)
            log.warning(
                "backend_quota_exceeded",
                backend=self._adapter_id,
                attempt=state.used_units,
                observed_limit=max(0, state.used_units - 1),
            )

        if fallback_detected:
            self._fallback_latched = True
            log.warning("backend_fallback_detected", backend=self._adapter_id)

        success = process.returncode == 0 and not quota_exceeded and not fallback_detected

        return DispatchResult(
            task_id=task.id,
            backend_id=self._adapter_id,
            success=success,
            output=combined,
            error=None if success else stderr or stdout or f"exit code {process.returncode}",
            fallback_detected=fallback_detected,
            quota_exceeded=quota_exceeded,
            completed_at=datetime.now(UTC),
        )

    async def get_budget(self) -> BudgetSnapshot:
        state = await self._load_state()
        return BudgetSnapshot(
            backend_id=self._adapter_id,
            used_units=state.used_units,
            window=BudgetWindow(
                backend_id=self._adapter_id,
                window_seconds=self._window_seconds,
                cautious_limit=self._cautious_limit,
                window_start=self._window_start,
                observed_limit=state.observed_limit,
            ),
            is_exhausted=state.exhausted,
            quota_exceeded=state.exhausted and state.observed_limit is not None,
        )

    async def detect_fallback(self) -> bool:
        return self._fallback_latched

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
            cautious_limit=self._cautious_limit,
            window_start=self._window_start,
            observed_limit=None,
        )

    def build_invocation(self, task: PlanTask, worktree: Path) -> CLIInvocation:
        raise NotImplementedError

    @staticmethod
    def build_task_prompt(task: PlanTask) -> str:
        if task.description and task.description != task.title:
            return f"{task.title}\n\n{task.description}"
        return task.title

    def _detect_quota_exceeded(self, output: str) -> bool:
        return any(pattern.search(output) for pattern in QUOTA_OUTPUT_PATTERNS)

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
            self._fallback_latched = False

    async def _load_state(self):
        from sluice.models.budget_state import BudgetState

        await self._refresh_window_if_needed()
        if self._store is None:
            return BudgetState(
                backend_id=self._adapter_id,
                window_start=self._window_start.isoformat(),
                used_units=0,
                cautious_limit=self._cautious_limit,
            )
        return await self._store.get_budget_state(
            self._adapter_id,
            self._window_start.isoformat(),
            self._cautious_limit,
        )

    async def _has_headroom(self) -> bool:
        state = await self._load_state()
        return state.has_headroom

    async def _record_attempt(self):
        if self._store is None:
            from sluice.models.budget_state import BudgetState

            return BudgetState(
                backend_id=self._adapter_id,
                window_start=self._window_start.isoformat(),
                used_units=1,
                cautious_limit=self._cautious_limit,
            )
        return await self._store.record_budget_attempt(
            self._adapter_id,
            self._window_start.isoformat(),
            self._cautious_limit,
        )

    async def _record_quota_failure(self, failed_attempt: int) -> None:
        if self._store is None:
            return
        await self._store.record_quota_limit(
            self._adapter_id,
            self._window_start.isoformat(),
            self._cautious_limit,
            failed_attempt=failed_attempt,
        )
