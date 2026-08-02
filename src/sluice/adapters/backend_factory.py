"""Factory for configured AI CLI backend adapters."""

from __future__ import annotations

from collections.abc import Callable

from sluice.adapters.agy_cli import AgyBackendAdapter
from sluice.adapters.backend import BackendAdapter
from sluice.adapters.claude_code import ClaudeCodeBackendAdapter
from sluice.adapters.cursor_cli import CursorBackendAdapter
from sluice.config import SluiceSettings
from sluice.store.sqlite import SQLiteStateStore


def build_backends(settings: SluiceSettings, store: SQLiteStateStore) -> dict[str, BackendAdapter]:
    """Build all enabled AI CLI backends from settings."""
    builders: dict[str, Callable[[SluiceSettings, SQLiteStateStore], BackendAdapter]] = {
        "claude_code": _build_claude_code,
        "cursor": _build_cursor,
        "agy": _build_agy,
    }

    backends: dict[str, BackendAdapter] = {}
    for backend_id in settings.enabled_backend_ids():
        builder = builders.get(backend_id)
        if builder is None:
            raise ValueError(f"Unknown AI backend {backend_id!r}")
        adapter = builder(settings, store)
        backends[adapter.adapter_id] = adapter
    return backends


def _build_claude_code(
    settings: SluiceSettings, store: SQLiteStateStore
) -> ClaudeCodeBackendAdapter:
    return ClaudeCodeBackendAdapter(
        cli_path=settings.claude_code_cli_path,
        max_requests_per_window=settings.claude_code_max_requests,
        window_seconds=settings.claude_code_window_seconds,
        safety_margin=settings.budget_safety_margin,
        store=store,
        dispatch_timeout_seconds=settings.backend_dispatch_timeout_seconds,
        skip_permissions=settings.claude_code_skip_permissions,
    )


def _build_cursor(settings: SluiceSettings, store: SQLiteStateStore) -> CursorBackendAdapter:
    return CursorBackendAdapter(
        cli_path=settings.cursor_cli_path,
        max_requests_per_window=settings.cursor_max_requests,
        window_seconds=settings.cursor_window_seconds,
        safety_margin=settings.budget_safety_margin,
        store=store,
        dispatch_timeout_seconds=settings.backend_dispatch_timeout_seconds,
        output_format=settings.cursor_output_format,
        force=settings.cursor_force,
        trust_workspace=settings.cursor_trust_workspace,
    )


def _build_agy(settings: SluiceSettings, store: SQLiteStateStore) -> AgyBackendAdapter:
    return AgyBackendAdapter(
        cli_path=settings.agy_cli_path,
        max_requests_per_window=settings.agy_max_requests,
        window_seconds=settings.agy_window_seconds,
        safety_margin=settings.budget_safety_margin,
        store=store,
        dispatch_timeout_seconds=settings.backend_dispatch_timeout_seconds,
        mode=settings.agy_mode,
        skip_permissions=settings.agy_skip_permissions,
    )
