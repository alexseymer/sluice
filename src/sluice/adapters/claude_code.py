"""Claude Code CLI backend adapter."""

from __future__ import annotations

from pathlib import Path

from sluice.adapters.cli_backend import CLIBackendAdapter, CLIInvocation
from sluice.models.plan import PlanTask
from sluice.store.sqlite import SQLiteStateStore


class ClaudeCodeBackendAdapter(CLIBackendAdapter):
    """Dispatches tasks to the Claude Code CLI in print mode."""

    def __init__(
        self,
        *,
        cli_path: str = "claude",
        max_requests_per_window: int = 50,
        window_seconds: int = 5 * 60 * 60,
        store: SQLiteStateStore | None = None,
        dispatch_timeout_seconds: int = 3600,
        skip_permissions: bool = True,
    ) -> None:
        super().__init__(
            adapter_id="claude_code",
            cli_path=cli_path,
            cautious_limit=max_requests_per_window,
            window_seconds=window_seconds,
            store=store,
            dispatch_timeout_seconds=dispatch_timeout_seconds,
        )
        self._skip_permissions = skip_permissions

    def build_invocation(self, task: PlanTask, worktree: Path) -> CLIInvocation:
        prompt = self.build_task_prompt(task)
        command = ["-p", prompt]
        if self._skip_permissions:
            command.insert(0, "--dangerously-skip-permissions")

        return CLIInvocation(
            command=command,
            cwd=worktree,
            timeout_seconds=self._dispatch_timeout_seconds,
        )
