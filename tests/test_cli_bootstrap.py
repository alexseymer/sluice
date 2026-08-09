"""Tests for primary CLI setup during `sluice setup`."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from sluice.config import SluiceSettings
from sluice.setup.cli_bootstrap import (
    PrimaryCliSetupError,
    setup_primary_cli,
)


@pytest.mark.asyncio
async def test_setup_primary_cli_skips_when_ready(tmp_path, capsys) -> None:
    settings = SluiceSettings(
        data_dir=tmp_path,
        matrix_homeserver="https://matrix.example.com",
        matrix_room_id="!room:example.com",
        matrix_access_token="token",
        planner_backend="cursor",
        ai_backends="cursor,agy",
    )
    with patch(
        "sluice.setup.cli_bootstrap.primary_cli_already_ready",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await setup_primary_cli(settings=settings)
    assert "already signed in" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_setup_primary_cli_requires_matrix(tmp_path) -> None:
    settings = SluiceSettings(data_dir=tmp_path, ai_backends="cursor")
    with pytest.raises(PrimaryCliSetupError, match="Matrix is not configured"):
        await setup_primary_cli(settings=settings)


@pytest.mark.asyncio
async def test_setup_primary_cli_bootstraps_over_matrix(tmp_path) -> None:
    settings = SluiceSettings(
        data_dir=tmp_path,
        matrix_homeserver="https://matrix.example.com",
        matrix_room_id="!room:example.com",
        matrix_access_token="token",
        planner_backend="cursor",
        ai_backends="cursor,agy",
    )
    chat = AsyncMock()
    chat.start = AsyncMock()
    chat.stop = AsyncMock()

    with (
        patch(
            "sluice.setup.cli_bootstrap.primary_cli_already_ready",
            new_callable=AsyncMock,
            side_effect=[False, True],
        ),
        patch("sluice.setup.cli_bootstrap.build_matrix_chat", return_value=chat),
        patch(
            "sluice.setup.cli_bootstrap.bootstrap_ai_clis",
            new_callable=AsyncMock,
        ) as bootstrap,
    ):
        await setup_primary_cli(settings=settings)

    chat.start.assert_awaited_once()
    chat.stop.assert_awaited_once()
    bootstrap.assert_awaited_once()
    assert bootstrap.await_args.kwargs["backend_ids"] == ["cursor"]
