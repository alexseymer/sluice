"""Tests for GitHub forge adapter."""

from __future__ import annotations

import json

import httpx
import pytest

from sluice.adapters.github_forge import GitHubForgeAdapter, GitHubForgeError
from sluice.models.issue import IssueStatus
from sluice.models.plan import PlanTask


@pytest.fixture
def adapter() -> GitHubForgeAdapter:
    return GitHubForgeAdapter(owner="acme", repo="sluice", token="ghp_test")


def test_is_configured(adapter: GitHubForgeAdapter) -> None:
    assert adapter.is_configured is True
    assert GitHubForgeAdapter("", "repo", "token").is_configured is False


@pytest.mark.asyncio
async def test_create_issue(adapter: GitHubForgeAdapter) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/repos/acme/sluice/issues"
        return httpx.Response(
            201,
            json={
                "id": 999,
                "number": 42,
                "title": "Build auth",
                "body": "Build auth",
                "state": "open",
                "labels": [{"name": "sluice"}],
                "html_url": "https://github.com/acme/sluice/issues/42",
            },
        )

    adapter._client = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )

    issue = await adapter.create_issue(PlanTask(title="Build auth", description="Build auth"))

    assert issue.number == 42
    assert issue.id == "42"
    assert issue.status == IssueStatus.OPEN
    assert issue.url.endswith("/issues/42")


@pytest.mark.asyncio
async def test_link_dependency_appends_blocked_by(adapter: GitHubForgeAdapter) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/issues/2"):
            return httpx.Response(
                200,
                json={
                    "id": 2,
                    "number": 2,
                    "title": "API client",
                    "body": "Needs schema",
                    "state": "open",
                    "labels": [],
                    "html_url": "https://github.com/acme/sluice/issues/2",
                },
            )
        if request.method == "GET" and request.url.path.endswith("/issues/1"):
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "number": 1,
                    "title": "Schema",
                    "body": "",
                    "state": "open",
                    "labels": [],
                    "html_url": "https://github.com/acme/sluice/issues/1",
                },
            )
        if request.method == "PATCH" and request.url.path.endswith("/issues/2"):
            payload = json.loads(request.content)
            calls.append(("patch", payload["body"]))
            return httpx.Response(
                200,
                json={
                    "id": 2,
                    "number": 2,
                    "title": "API client",
                    "body": "Needs schema\n\n## Blocked by\n- #1",
                    "state": "open",
                    "labels": [],
                    "html_url": "https://github.com/acme/sluice/issues/2",
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    adapter._client = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )

    await adapter.link_dependency("2", "1")

    assert calls
    assert "## Blocked by" in calls[0][1]
    assert "#1" in calls[0][1]


@pytest.mark.asyncio
async def test_create_issue_raises_on_error(adapter: GitHubForgeAdapter) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    adapter._client = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GitHubForgeError, match="create issue"):
        await adapter.create_issue(PlanTask(title="Nope"))
