"""GitHub forge adapter (Phase 1 stub)."""

from __future__ import annotations

from sluice.adapters.forge import ForgeAdapter
from sluice.models.issue import ForgeIssue, IssueStatus
from sluice.models.plan import PlanTask


class GitHubForgeAdapter(ForgeAdapter):
    """GitHub Issues adapter — not yet implemented."""

    def __init__(self, owner: str, repo: str, token: str) -> None:
        self._owner = owner
        self._repo = repo
        self._token = token

    @property
    def adapter_id(self) -> str:
        return "github"

    async def create_issue(self, task: PlanTask) -> ForgeIssue:
        raise NotImplementedError("GitHub adapter not yet implemented")

    async def update_issue(
        self, issue_id: str, *, title: str | None = None, body: str | None = None
    ) -> ForgeIssue:
        raise NotImplementedError("GitHub adapter not yet implemented")

    async def set_status(self, issue_id: str, status: IssueStatus) -> ForgeIssue:
        raise NotImplementedError("GitHub adapter not yet implemented")

    async def add_labels(self, issue_id: str, labels: list[str]) -> ForgeIssue:
        raise NotImplementedError("GitHub adapter not yet implemented")

    async def link_dependency(self, issue_id: str, blocked_by_issue_id: str) -> None:
        raise NotImplementedError("GitHub adapter not yet implemented")

    async def get_issue(self, issue_id: str) -> ForgeIssue:
        raise NotImplementedError("GitHub adapter not yet implemented")

    async def list_open_issues(self) -> list[ForgeIssue]:
        raise NotImplementedError("GitHub adapter not yet implemented")
