"""Git forge issue models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class IssueStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class ForgeIssue(BaseModel):
    """Representation of an issue on a Git forge."""

    id: str
    number: int
    title: str
    body: str = ""
    status: IssueStatus = IssueStatus.OPEN
    labels: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    url: str | None = None
