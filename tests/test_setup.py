"""Tests for setup envfile and GitHub/Matrix helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from sluice.setup.envfile import upsert_env_file
from sluice.setup.github_oauth import (
    GitHubAuthError,
    authorize_github,
    parse_github_repo,
    verify_github_token,
)
from sluice.setup.matrix_provision import (
    provision_matrix,
    synapse_registration_mac,
)


def test_parse_github_repo_variants() -> None:
    assert parse_github_repo("alexseymer/sluice") == ("alexseymer", "sluice")
    assert parse_github_repo("https://github.com/alexseymer/sluice.git") == (
        "alexseymer",
        "sluice",
    )
    assert parse_github_repo("git@github.com:alexseymer/sluice.git") == (
        "alexseymer",
        "sluice",
    )


def test_parse_github_repo_rejects_garbage() -> None:
    with pytest.raises(GitHubAuthError):
        parse_github_repo("not-a-repo")


def test_upsert_env_file_preserves_and_updates(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("SLUICE_LOG_LEVEL=DEBUG\nSLUICE_GITHUB_TOKEN=old\n", encoding="utf-8")
    upsert_env_file(
        path,
        {
            "SLUICE_GITHUB_TOKEN": "new",
            "SLUICE_GITHUB_OWNER": "alexseymer",
        },
    )
    text = path.read_text(encoding="utf-8")
    assert "SLUICE_LOG_LEVEL=DEBUG" in text
    assert "SLUICE_GITHUB_TOKEN=new" in text
    assert "SLUICE_GITHUB_OWNER=alexseymer" in text
    assert "old" not in text


def test_synapse_registration_mac_stable() -> None:
    mac = synapse_registration_mac(
        shared_secret="secret",
        nonce="nonce",
        username="bot",
        password="pw",
        admin=False,
    )
    assert len(mac) == 40
    assert mac == synapse_registration_mac(
        shared_secret="secret",
        nonce="nonce",
        username="bot",
        password="pw",
        admin=False,
    )


@pytest.mark.asyncio
async def test_verify_github_token_reuses_valid_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/user"):
            return httpx.Response(200, json={"login": "alexseymer"})
        if "/repos/alexseymer/sluice" in url:
            return httpx.Response(200, json={"full_name": "alexseymer/sluice"})
        return httpx.Response(404, json={"message": "not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await verify_github_token(
            token="gho_existing",
            owner="alexseymer",
            repo="sluice",
            client=client,
        )
    assert result is not None
    assert result.login == "alexseymer"
    assert result.token == "gho_existing"


@pytest.mark.asyncio
async def test_verify_github_token_rejects_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await verify_github_token(
            token="gho_bad",
            owner="alexseymer",
            repo="sluice",
            client=client,
        )
    assert result is None


@pytest.mark.asyncio
async def test_authorize_github_device_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sluice.setup.github_oauth.asyncio.sleep", AsyncMock())

    calls = {"token": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/login/device/code"):
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://github.com/login/device",
                    "interval": 1,
                    "expires_in": 30,
                },
            )
        if url.endswith("/login/oauth/access_token"):
            calls["token"] += 1
            if calls["token"] == 1:
                return httpx.Response(200, json={"error": "authorization_pending"})
            return httpx.Response(200, json={"access_token": "gho_test"})
        if url.endswith("/user"):
            return httpx.Response(200, json={"login": "alexseymer"})
        if "/repos/alexseymer/sluice" in url:
            return httpx.Response(200, json={"full_name": "alexseymer/sluice"})
        return httpx.Response(404, json={"message": "not found"})

    transport = httpx.MockTransport(handler)
    seen: list[str] = []
    async with httpx.AsyncClient(transport=transport) as client:
        result = await authorize_github(
            client_id="client",
            owner="alexseymer",
            repo="sluice",
            on_user_code=lambda d: seen.append(d.user_code),
            client=client,
        )
    assert result.token == "gho_test"
    assert result.login == "alexseymer"
    assert seen == ["ABCD-1234"]


@pytest.mark.asyncio
async def test_provision_matrix_shared_secret() -> None:
    hs = "https://matrix.example.com"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/_matrix/client/v3/login"):
            return httpx.Response(
                200,
                json={"user_id": "@you:example.com", "access_token": "user_token"},
            )
        if url.endswith("/_synapse/admin/v1/register") and request.method == "GET":
            return httpx.Response(200, json={"nonce": "n1"})
        if url.endswith("/_synapse/admin/v1/register") and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "user_id": "@sluice-bot:example.com",
                    "access_token": "bot_token",
                },
            )
        if url.endswith("/_matrix/client/v3/createRoom"):
            return httpx.Response(200, json={"room_id": "!abc:example.com"})
        if "/send/m.room.message" in url:
            return httpx.Response(200, json={"event_id": "$1"})
        return httpx.Response(404, json={"errcode": "M_NOT_FOUND"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await provision_matrix(
            homeserver=hs,
            operator_user="@you:example.com",
            operator_password="secret",
            shared_secret="shared",
            bot_localpart="sluice-bot",
            client=client,
        )
    assert result.bot_user_id == "@sluice-bot:example.com"
    assert result.bot_access_token == "bot_token"
    assert result.room_id == "!abc:example.com"
    assert result.allowed_sender == "@you:example.com"
    assert result.bot_password is not None


@pytest.mark.asyncio
async def test_provision_matrix_reuses_existing_bot_via_password() -> None:
    hs = "https://matrix.example.com"
    logins: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/_matrix/client/v3/login"):
            body = request.read().decode()
            logins.append(body)
            if '"user": "bot"' in body or '"user":"bot"' in body:
                return httpx.Response(
                    200,
                    json={"user_id": "@bot:example.com", "access_token": "bot_token"},
                )
            return httpx.Response(
                200,
                json={"user_id": "@you:example.com", "access_token": "user_token"},
            )
        if url.endswith("/_matrix/client/v3/register"):
            return httpx.Response(
                400,
                json={"errcode": "M_USER_IN_USE", "error": "User ID already taken."},
            )
        if url.endswith("/_matrix/client/v3/createRoom"):
            return httpx.Response(200, json={"room_id": "!xyz:example.com"})
        if "/send/m.room.message" in url:
            return httpx.Response(200, json={"event_id": "$1"})
        return httpx.Response(404, json={"errcode": "M_NOT_FOUND"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await provision_matrix(
            homeserver=hs,
            operator_user="@you:example.com",
            operator_password="secret",
            bot_localpart="bot",
            bot_password="bot-pass",
            client=client,
        )
    assert result.bot_user_id == "@bot:example.com"
    assert result.bot_access_token == "bot_token"
    assert result.room_id == "!xyz:example.com"
    assert any("bot-pass" in entry for entry in logins)
