"""Scheduling models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ScheduleSlot(BaseModel):
    """Time-boxed allocation for dispatching work to a backend."""

    backend_id: str
    task_id: UUID
    scheduled_at: datetime
    dispatched_at: datetime | None = None


class DispatchResult(BaseModel):
    """Outcome of dispatching a task to an AI backend."""

    task_id: UUID
    backend_id: str
    success: bool
    output: str = ""
    error: str | None = None
    fallback_detected: bool = False
    completed_at: datetime | None = None
