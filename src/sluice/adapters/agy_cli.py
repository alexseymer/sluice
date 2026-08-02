"""Antigravity CLI (agy) backend adapter."""

from __future__ import annotations

from pathlib import Path

from sluice.adapters.cli_backend import CLIBackendAdapter, CLIInvocation
from sluice.models.plan import PlanTask
from sluice.store.sqlite import SQLiteStateStore


class AgyBackendAdapter(CLIBackendAdapter):
    """Dispatches tasks to Google's Antigravity CLI (`agy`) in print mode."""

    def __init__(
        self,
        *,
        cli_path: str = "agy",
        max_requests_per_window: int = 20,
        window_seconds: int = 24 * 60 * 60,
        store: SQLiteStateStore | None = None,
        dispatch_timeout_seconds: int = 3600,
        mode: str = "accept-edits",
        skip_permissions: bool = True,
    ) -> None:
        super().__init__(
            adapter_id="agy",
            cli_path=cli_path,
            cautious_limit=max_requests_per_window,
            window_seconds=window_seconds,
            store=store,
            dispatch_timeout_seconds=dispatch_timeout_seconds,
        )
        self._mode = mode
        self._skip_permissions = skip_permissions

    def build_invocation(self, task: PlanTask, worktree: Path) -> CLIInvocation:
        prompt = self.build_task_prompt(task)
        command = [
            "-p",
            "--mode",
            self._mode,
        ]
        if self._skip_permissions:
            command.append("--dangerously-skip-permissions")
        command.append(prompt)

        return CLIInvocation(
            command=command,
            cwd=worktree,
            timeout_seconds=self._dispatch_timeout_seconds,
        )
