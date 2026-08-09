"""Tests for runtime AI CLI install / Matrix auth helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sluice.config import SluiceSettings
from sluice.setup.cli_runtime import (
    SPECS,
    bootstrap_ai_clis,
    extract_first_url,
    looks_like_auth_code,
    resolve_binary,
)


def test_extract_first_url() -> None:
    text = "Open https://cursor.com/login?token=abc then continue."
    assert extract_first_url(text) == "https://cursor.com/login?token=abc"


def test_looks_like_auth_code() -> None:
    assert looks_like_auth_code("4/abcd-EFGH")
    assert looks_like_auth_code("  abc123xyz  ")
    assert not looks_like_auth_code("/cli-auth")
    assert not looks_like_auth_code("hi")


def test_resolve_binary_finds_local(tmp_path: Path) -> None:
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    agent = bin_dir / "agent"
    agent.write_text("#!/bin/sh\n", encoding="utf-8")
    agent.chmod(0o755)
    found = resolve_binary(SPECS["cursor"], tmp_path)
    assert found == str(agent)


@pytest.mark.asyncio
async def test_bootstrap_skips_when_disabled(tmp_path: Path) -> None:
    settings = SluiceSettings(
        data_dir=tmp_path,
        ai_backends="cursor,agy",
        cli_bootstrap_enabled=False,
    )
    chat = MagicMock()
    chat.is_configured = True
    chat.is_running = True
    chat.send = AsyncMock()
    await bootstrap_ai_clis(settings=settings, chat=chat, home=tmp_path / "home")
    chat.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_bootstrap_secondary_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    settings = SluiceSettings(
        data_dir=tmp_path,
        ai_backends="cursor,agy",
        planner_backend="cursor",
        cli_bootstrap_enabled=True,
    )
    chat = MagicMock()
    chat.is_configured = True
    chat.is_running = True
    chat.send = AsyncMock()
    chat.drain_pending_messages = MagicMock(return_value=0)
    chat.wait_for_message = AsyncMock()

    with (
        patch("sluice.setup.cli_runtime.bootstrap_backend", new_callable=AsyncMock) as boot,
    ):
        boot.return_value = True
        await bootstrap_ai_clis(
            settings=settings,
            chat=chat,
            home=home,
            backend_ids=settings.secondary_backend_ids(),
        )

    boot.assert_awaited_once()
    assert boot.await_args.kwargs["backend_id"] == "agy"


@pytest.mark.asyncio
async def test_bootstrap_installs_and_auths(tmp_path: Path) -> None:
    home = tmp_path / "home"
    settings = SluiceSettings(
        data_dir=tmp_path,
        ai_backends="cursor,agy",
        cli_bootstrap_enabled=True,
        cli_auth_timeout_seconds=30,
    )
    chat = MagicMock()
    chat.is_configured = True
    chat.is_running = True
    chat.send = AsyncMock()
    chat.drain_pending_messages = MagicMock(return_value=0)
    chat.wait_for_message = AsyncMock()

    with (
        patch("sluice.setup.cli_runtime.install_cli", new_callable=AsyncMock) as install,
        patch(
            "sluice.setup.cli_runtime.resolve_binary",
            side_effect=["/bin/agent", "/bin/agy"],
        ),
        patch(
            "sluice.setup.cli_runtime.is_backend_authenticated",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "sluice.setup.cli_runtime.authenticate_cursor",
            new_callable=AsyncMock,
            return_value=True,
        ) as auth_cursor,
        patch(
            "sluice.setup.cli_runtime.authenticate_agy",
            new_callable=AsyncMock,
            return_value=True,
        ) as auth_agy,
    ):
        install.return_value = (True, "installed")
        await bootstrap_ai_clis(settings=settings, chat=chat, home=home)

    assert install.await_count == 2
    auth_cursor.assert_awaited_once()
    auth_agy.assert_awaited_once()
    sent = " ".join(call.args[0].text for call in chat.send.await_args_list)
    assert "cursor" in sent.lower() or "CLI" in sent
