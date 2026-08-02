"""GitHub Issues adapter via REST API."""

from __future__ import annotations

import re

import httpx

from sluice.adapters.forge import ForgeAdapter
from sluice.models.issue import ForgeIssue, IssueStatus
from sluice.models.plan import PlanTask

_BLOCKED_BY_HEADER = "## Blocked by"
_GITHUB_API = "https://api.github.com"


class GitHubForgeError(RuntimeError):
    """Raised when a GitHub API request fails."""


class GitHubForgeAdapter(ForgeAdapter):
    """GitHub Issues adapter backed by the REST API."""

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str,
        *,
        default_labels: list[str] | None = None,
    ) -> None:
        self._owner = owner
        self._repo = repo
        self._token = token
        self._default_labels = default_labels or ["sluice"]
        self._client: httpx.AsyncClient | None = None

    @property
    def adapter_id(self) -> str:
        return "github"

    @property
    def is_configured(self) -> bool:
        return bool(self._owner and self._repo and self._token)

    async def start(self) -> None:
        if not self.is_configured:
            return
        self._client = httpx.AsyncClient(
            base_url=_GITHUB_API,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def create_issue(self, task: PlanTask) -> ForgeIssue:
        client = self._require_client()
        body_parts = [task.description or ""]
        if task.acceptance_criteria:
            body_parts.extend(["", "## Acceptance criteria", task.acceptance_criteria])
        body = "\n".join(part for part in body_parts if part).strip()
        if task.estimated_complexity:
            body = f"{body}\n\n_Estimated complexity: {task.estimated_complexity}_".strip()

        response = await client.post(
            f"/repos/{self._owner}/{self._repo}/issues",
            json={
                "title": task.title,
                "body": body,
                "labels": self._default_labels,
            },
        )
        self._raise_for_status(response, "create issue")
        return self._issue_from_json(response.json())

    async def update_issue(
        self, issue_id: str, *, title: str | None = None, body: str | None = None
    ) -> ForgeIssue:
        client = self._require_client()
        payload: dict[str, str] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body

        response = await client.patch(
            f"/repos/{self._owner}/{self._repo}/issues/{issue_id}",
            json=payload,
        )
        self._raise_for_status(response, "update issue")
        return self._issue_from_json(response.json())

    async def set_status(self, issue_id: str, status: IssueStatus) -> ForgeIssue:
        client = self._require_client()
        state = "closed" if status == IssueStatus.CLOSED else "open"
        response = await client.patch(
            f"/repos/{self._owner}/{self._repo}/issues/{issue_id}",
            json={"state": state},
        )
        self._raise_for_status(response, "set issue status")
        return self._issue_from_json(response.json())

    async def add_labels(self, issue_id: str, labels: list[str]) -> ForgeIssue:
        client = self._require_client()
        response = await client.post(
            f"/repos/{self._owner}/{self._repo}/issues/{issue_id}/labels",
            json={"labels": labels},
        )
        self._raise_for_status(response, "add labels")
        issue = await self.get_issue(issue_id)
        return issue

    async def link_dependency(self, issue_id: str, blocked_by_issue_id: str) -> None:
        issue = await self.get_issue(issue_id)
        blocker = await self.get_issue(blocked_by_issue_id)
        body = self._append_blocked_by(issue.body, blocker.number)
        await self.update_issue(issue_id, body=body)

    async def get_issue(self, issue_id: str) -> ForgeIssue:
        client = self._require_client()
        response = await client.get(f"/repos/{self._owner}/{self._repo}/issues/{issue_id}")
        self._raise_for_status(response, "get issue")
        return self._issue_from_json(response.json())

    async def list_open_issues(self) -> list[ForgeIssue]:
        client = self._require_client()
        response = await client.get(
            f"/repos/{self._owner}/{self._repo}/issues",
            params={"state": "open", "labels": ",".join(self._default_labels), "per_page": 100},
        )
        self._raise_for_status(response, "list issues")
        return [self._issue_from_json(item) for item in response.json()]

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self.is_configured:
                raise RuntimeError("GitHub forge is not configured")
            raise RuntimeError("GitHub forge client is not started")
        return self._client

    @staticmethod
    def _issue_from_json(data: dict) -> ForgeIssue:
        labels = [
            label["name"] if isinstance(label, dict) else str(label) for label in data["labels"]
        ]
        status = IssueStatus.CLOSED if data.get("state") == "closed" else IssueStatus.OPEN
        blocked_by = [
            match.group(1)
            for match in re.finditer(r"^-\s*#(\d+)\s*$", data.get("body") or "", flags=re.MULTILINE)
            if _BLOCKED_BY_HEADER in (data.get("body") or "")
        ]
        return ForgeIssue(
            id=str(data["number"]),
            number=data["number"],
            title=data["title"],
            body=data.get("body") or "",
            status=status,
            labels=labels,
            blocked_by=blocked_by,
            url=data.get("html_url"),
        )

    @staticmethod
    def _append_blocked_by(body: str, blocker_number: int) -> str:
        line = f"- #{blocker_number}"
        if _BLOCKED_BY_HEADER in body:
            if line in body:
                return body
            return f"{body.rstrip()}\n{line}"
        section = f"\n\n{_BLOCKED_BY_HEADER}\n{line}"
        return f"{body.rstrip()}{section}"

    @staticmethod
    def _raise_for_status(response: httpx.Response, action: str) -> None:
        if response.is_success:
            return
        detail = response.text.strip() or response.reason_phrase
        raise GitHubForgeError(f"Failed to {action}: HTTP {response.status_code} — {detail}")
