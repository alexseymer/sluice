"""Plan and task models produced by the jour fixe planner."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class PlanTask(BaseModel):
    """A single unit of work within a plan."""

    id: UUID = Field(default_factory=uuid4)
    title: str
    description: str = ""
    backend_id: str | None = None
    depends_on: list[UUID] = Field(default_factory=list)
    estimated_complexity: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    forge_issue_id: str | None = None


class Plan(BaseModel):
    """Dependency-ordered breakdown of jour-fixe discussion."""

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_at: datetime | None = None
    tasks: list[PlanTask] = Field(default_factory=list)
    jour_fixe_session_id: UUID | None = None

    @property
    def is_approved(self) -> bool:
        return self.approved_at is not None


def plan_is_complete(plan: Plan) -> bool:
    terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    return all(task.status in terminal for task in plan.tasks)
