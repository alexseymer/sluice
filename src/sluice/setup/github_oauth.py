"""GitHub OAuth device-flow helpers for CLI setup."""

from __future__ import annotations

import asyncio
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

_GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_DEFAULT_SCOPES = "repo read:user"


class GitHubAuthError(RuntimeError):
    """Raised when GitHub authorization fails."""


@dataclass(frozen=True)
class GitHubAuthResult:
    token: str
    owner: str
    repo: str
    login: str | None = None


@dataclass(frozen=True)
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


def parse_github_repo(value: str) -> tuple[str, str]:
    """Parse `owner/repo` or a GitHub remote URL into (owner, repo)."""
    raw = value.strip()
    if not raw:
        raise GitHubAuthError("Repository is required (owner/repo)")

    if "github.com" in raw:
        path = raw
        if raw.startswith("git@"):
            # git@github.com:owner/repo.git
            path = raw.split(":", maxsplit=1)[-1]
        else:
            path = urlparse(raw if "://" in raw else f"https://{raw}").path
        path = path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            return parts[0], parts[1]
        raise GitHubAuthError(f"Could not parse GitHub repo from URL: {value}")

    match = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", raw)
    if not match:
        raise GitHubAuthError("Expected owner/repo (e.g. alexseymer/sluice)")
    return match.group(1), match.group(2)


def detect_github_repo_from_git() -> str | None:
    """Best-effort `owner/repo` from `git remote get-url origin`."""
    try:
        completed = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    url = completed.stdout.strip()
    if "github.com" not in url:
        return None
    try:
        owner, repo = parse_github_repo(url)
    except GitHubAuthError:
        return None
    return f"{owner}/{repo}"


async def request_device_code(client: httpx.AsyncClient, client_id: str) -> DeviceCode:
    response = await client.post(
        _GITHUB_DEVICE_CODE_URL,
        data={"client_id": client_id, "scope": _DEFAULT_SCOPES},
        headers={"Accept": "application/json"},
    )
    if response.status_code >= 400:
        detail = response.text
        raise GitHubAuthError(
            "Device-flow request failed. Enable Device Flow on the OAuth App "
            f"and check the client ID. GitHub said: {detail}"
        )
    payload = response.json()
    if "error" in payload:
        raise GitHubAuthError(payload.get("error_description") or payload["error"])
    return DeviceCode(
        device_code=payload["device_code"],
        user_code=payload["user_code"],
        verification_uri=payload.get("verification_uri", "https://github.com/login/device"),
        interval=int(payload.get("interval", 5)),
        expires_in=int(payload.get("expires_in", 900)),
    )


async def poll_for_access_token(
    client: httpx.AsyncClient,
    *,
    client_id: str,
    device_code: str,
    interval: int,
    expires_in: int,
) -> str:
    elapsed = 0
    poll_every = max(interval, 1)
    while elapsed < expires_in:
        await asyncio.sleep(poll_every)
        elapsed += poll_every
        response = await client.post(
            _GITHUB_TOKEN_URL,
            data={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
        )
        payload = response.json()
        if access_token := payload.get("access_token"):
            return str(access_token)
        error = payload.get("error")
        if error in {"authorization_pending", "slow_down"}:
            if error == "slow_down":
                poll_every += 5
            continue
        if error == "expired_token":
            raise GitHubAuthError("Device code expired — re-run setup.")
        if error == "access_denied":
            raise GitHubAuthError("Authorization denied in the browser.")
        raise GitHubAuthError(payload.get("error_description") or error or "token exchange failed")
    raise GitHubAuthError("Timed out waiting for GitHub authorization.")


async def fetch_login(client: httpx.AsyncClient, token: str) -> str:
    response = await client.get(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if response.status_code >= 400:
        raise GitHubAuthError(f"Could not verify token: HTTP {response.status_code}")
    return str(response.json()["login"])


async def verify_github_token(
    *,
    token: str,
    owner: str,
    repo: str,
    client: httpx.AsyncClient | None = None,
) -> GitHubAuthResult | None:
    """Return auth result if `token` can access the repo; otherwise None."""
    if not token.strip():
        return None

    async def _run(http: httpx.AsyncClient) -> GitHubAuthResult | None:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        user_response = await http.get("https://api.github.com/user", headers=headers)
        if user_response.status_code >= 400:
            return None
        repo_response = await http.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=headers,
        )
        if repo_response.status_code >= 400:
            return None
        return GitHubAuthResult(
            token=token,
            owner=owner,
            repo=repo,
            login=str(user_response.json()["login"]),
        )

    if client is not None:
        return await _run(client)
    async with httpx.AsyncClient(timeout=30.0) as http:
        return await _run(http)


async def authorize_github(
    *,
    client_id: str,
    owner: str,
    repo: str,
    on_user_code: Callable[[DeviceCode], None] | None = None,
    client: httpx.AsyncClient | None = None,
) -> GitHubAuthResult:
    """Run device flow and return a token scoped for the given repo target."""

    async def _run(http: httpx.AsyncClient) -> GitHubAuthResult:
        device = await request_device_code(http, client_id)
        if on_user_code is not None:
            on_user_code(device)
        token = await poll_for_access_token(
            http,
            client_id=client_id,
            device_code=device.device_code,
            interval=device.interval,
            expires_in=device.expires_in,
        )
        login = await fetch_login(http, token)
        response = await http.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if response.status_code == 404:
            raise GitHubAuthError(
                f"Token works, but {owner}/{repo} was not found (or is inaccessible)."
            )
        if response.status_code >= 400:
            raise GitHubAuthError(
                f"Could not access {owner}/{repo}: HTTP {response.status_code}"
            )
        return GitHubAuthResult(token=token, owner=owner, repo=repo, login=login)

    if client is not None:
        return await _run(client)
    async with httpx.AsyncClient(timeout=30.0) as http:
        return await _run(http)
