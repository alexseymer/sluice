"""Tests for multi-backend CLI adapters."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sluice.adapters.agy_cli import AgyBackendAdapter
from sluice.adapters.backend_factory import build_backends
from sluice.adapters.claude_code import ClaudeCodeBackendAdapter
from sluice.adapters.codex_cli import CodexBackendAdapter
from sluice.adapters.cursor_cli import CursorBackendAdapter
from sluice.config import SluiceSettings
from sluice.models.plan import PlanTask
from sluice.store.sqlite import SQLiteStateStore


@pytest.mark.parametrize(
    ("adapter_cls", "expected_flags"),
    [
        (
            ClaudeCodeBackendAdapter,
            ["--dangerously-skip-permissions", "-p", "Fix login bug"],
        ),
        (
            CursorBackendAdapter,
            [
                "-p",
                "--output-format",
                "text",
                "--workspace",
                "WORKTREE",
                "--force",
                "--trust",
                "Fix login bug",
            ],
        ),
        (
            AgyBackendAdapter,
            [
                "-p",
                "--mode",
                "accept-edits",
                "--dangerously-skip-permissions",
                "Fix login bug",
            ],
        ),
        (
            CodexBackendAdapter,
            [
                "exec",
                "--sandbox",
                "workspace-write",
                "--ephemeral",
                "--skip-git-repo-check",
                "Fix login bug",
            ],
        ),
    ],
)
def test_build_invocation(adapter_cls, expected_flags) -> None:
    adapter = adapter_cls()
    worktree = Path("/tmp/worktrees/task-1")
    invocation = adapter.build_invocation(PlanTask(title="Fix login bug"), worktree)

    if "WORKTREE" in expected_flags:
        expected = [flag.replace("WORKTREE", str(worktree)) for flag in expected_flags]
    else:
        expected = expected_flags

    assert invocation.command == expected
    assert invocation.cwd == worktree


def test_build_backends_respects_enabled_list(tmp_path) -> None:
    settings = SluiceSettings(ai_backends="cursor,agy", data_dir=tmp_path)
    store = SQLiteStateStore(tmp_path / "sluice.db")
    backends = build_backends(settings, store)

    assert set(backends) == {"cursor", "agy"}


@pytest.mark.asyncio
async def test_dispatch_runs_cli_and_records_budget(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "sluice.db")
    await store.initialize()
    adapter = ClaudeCodeBackendAdapter(store=store, dispatch_timeout_seconds=5)
    await adapter.initialize()

    async def fake_communicate():
        return b"done", b""

    process = AsyncMock()
    process.returncode = 0
    process.communicate = AsyncMock(side_effect=fake_communicate)

    with patch(
        "sluice.adapters.cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ) as create_subprocess:
        task = PlanTask(title="Ship it")
        worktree = tmp_path / "worktree"
        result = await adapter.dispatch(task, worktree=worktree)

    create_subprocess.assert_awaited_once()
    called_command = create_subprocess.await_args.args
    assert called_command[0] == "claude"
    assert result.success is True
    assert result.backend_id == "claude_code"

    budget = await adapter.get_budget()
    assert budget.used_units == 1


@pytest.mark.asyncio
async def test_dispatch_missing_cli_returns_error(tmp_path) -> None:
    adapter = ClaudeCodeBackendAdapter(dispatch_timeout_seconds=5)
    with patch(
        "sluice.adapters.cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=FileNotFoundError(2, "No such file", "claude")),
    ):
        result = await adapter.dispatch(PlanTask(title="Ship"), worktree=tmp_path / "wt")
    assert result.success is False
    assert result.error is not None
    assert "CLI not found" in result.error


@pytest.mark.asyncio
async def test_dispatch_detects_rate_limit_fallback(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "sluice.db")
    await store.initialize()
    adapter = ClaudeCodeBackendAdapter(store=store, dispatch_timeout_seconds=5)

    process = AsyncMock()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(b"rate limit exceeded", b""))

    with patch(
        "sluice.adapters.cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        result = await adapter.dispatch(PlanTask(title="Task"), worktree=tmp_path / "wt")

    assert result.success is False
    assert result.quota_exceeded is True


@pytest.mark.asyncio
async def test_dispatch_detects_model_fallback(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "sluice.db")
    await store.initialize()
    adapter = ClaudeCodeBackendAdapter(store=store, dispatch_timeout_seconds=5)

    process = AsyncMock()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(b"using haiku due to limits", b""))

    with patch(
        "sluice.adapters.cli_backend.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        result = await adapter.dispatch(PlanTask(title="Task"), worktree=tmp_path / "wt")

    assert result.success is False
    assert result.fallback_detected is True
    assert await adapter.detect_fallback() is True
