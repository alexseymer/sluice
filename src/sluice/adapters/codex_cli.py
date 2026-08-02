"""OpenAI Codex CLI backend adapter."""

from __future__ import annotations

import re
from pathlib import Path

from sluice.adapters.cli_backend import CLIBackendAdapter, CLIInvocation
from sluice.models.plan import PlanTask
from sluice.store.sqlite import SQLiteStateStore

_CODEX_FALLBACK_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"fallback",
        r"degraded.?model",
        r"gpt-3\.5",
        r"\bmini\b",
        r"lower.?tier",
    )
)


class CodexBackendAdapter(CLIBackendAdapter):
    """Dispatches tasks to the Codex CLI (`codex exec`) in headless mode."""

    def __init__(
        self,
        *,
        cli_path: str = "codex",
        max_requests_per_window: int = 50,
        window_seconds: int = 5 * 60 * 60,
        store: SQLiteStateStore | None = None,
        dispatch_timeout_seconds: int = 3600,
        sandbox: str = "workspace-write",
        ephemeral: bool = True,
        skip_git_repo_check: bool = True,
    ) -> None:
        super().__init__(
            adapter_id="codex",
            cli_path=cli_path,
            cautious_limit=max_requests_per_window,
            window_seconds=window_seconds,
            store=store,
            dispatch_timeout_seconds=dispatch_timeout_seconds,
        )
        self._sandbox = sandbox
        self._ephemeral = ephemeral
        self._skip_git_repo_check = skip_git_repo_check

    def build_invocation(self, task: PlanTask, worktree: Path) -> CLIInvocation:
        prompt = self.build_task_prompt(task)
        command = [
            "exec",
            "--sandbox",
            self._sandbox,
        ]
        if self._ephemeral:
            command.append("--ephemeral")
        if self._skip_git_repo_check:
            command.append("--skip-git-repo-check")
        command.append(prompt)

        return CLIInvocation(
            command=command,
            cwd=worktree,
            timeout_seconds=self._dispatch_timeout_seconds,
        )

    def _detect_fallback(self, output: str) -> bool:
        if any(pattern.search(output) for pattern in _CODEX_FALLBACK_PATTERNS):
            return True
        return super()._detect_fallback(output)
