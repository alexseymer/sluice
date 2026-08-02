"""Cursor Agent CLI backend adapter."""

from __future__ import annotations

from pathlib import Path

from sluice.adapters.cli_backend import CLIBackendAdapter, CLIInvocation
from sluice.models.plan import PlanTask
from sluice.store.sqlite import SQLiteStateStore


class CursorBackendAdapter(CLIBackendAdapter):
    """Dispatches tasks to the Cursor Agent CLI (`agent`) in print mode."""

    def __init__(
        self,
        *,
        cli_path: str = "agent",
        max_requests_per_window: int = 200,
        window_seconds: int = 30 * 24 * 60 * 60,
        safety_margin: float = 0.85,
        store: SQLiteStateStore | None = None,
        dispatch_timeout_seconds: int = 3600,
        output_format: str = "text",
        force: bool = True,
        trust_workspace: bool = True,
    ) -> None:
        super().__init__(
            adapter_id="cursor",
            cli_path=cli_path,
            max_requests_per_window=max_requests_per_window,
            window_seconds=window_seconds,
            safety_margin=safety_margin,
            store=store,
            dispatch_timeout_seconds=dispatch_timeout_seconds,
        )
        self._output_format = output_format
        self._force = force
        self._trust_workspace = trust_workspace

    def build_invocation(self, task: PlanTask, worktree: Path) -> CLIInvocation:
        prompt = self.build_task_prompt(task)
        command = [
            "-p",
            "--output-format",
            self._output_format,
            "--workspace",
            str(worktree),
        ]
        if self._force:
            command.append("--force")
        if self._trust_workspace:
            command.append("--trust")
        command.append(prompt)

        return CLIInvocation(
            command=command,
            cwd=worktree,
            timeout_seconds=self._dispatch_timeout_seconds,
        )
