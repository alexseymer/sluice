"""Git forge adapter protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sluice.models.issue import ForgeIssue, IssueStatus
from sluice.models.plan import PlanTask


class ForgeAdapter(ABC):
    """Common interface for GitHub, GitLab, and OneDev."""

    @property
    @abstractmethod
    def adapter_id(self) -> str:
        """Unique identifier for this forge adapter."""

    @abstractmethod
    async def create_issue(self, task: PlanTask) -> ForgeIssue:
        """Create an issue from a plan task."""

    @abstractmethod
    async def update_issue(
        self, issue_id: str, *, title: str | None = None, body: str | None = None
    ) -> ForgeIssue:
        """Update issue fields."""

    @abstractmethod
    async def set_status(self, issue_id: str, status: IssueStatus) -> ForgeIssue:
        """Transition issue status."""

    @abstractmethod
    async def add_labels(self, issue_id: str, labels: list[str]) -> ForgeIssue:
        """Apply labels to an issue."""

    @abstractmethod
    async def link_dependency(self, issue_id: str, blocked_by_issue_id: str) -> None:
        """Declare that issue_id is blocked by blocked_by_issue_id."""

    @abstractmethod
    async def get_issue(self, issue_id: str) -> ForgeIssue:
        """Fetch current issue state from the forge."""

    @abstractmethod
    async def list_open_issues(self) -> list[ForgeIssue]:
        """List all open issues tracked by this forge."""
