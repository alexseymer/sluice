"""Tests for plan persistence helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sluice.models.plan import Plan, PlanTask, TaskStatus
from sluice.store.sqlite import SQLiteStateStore


@pytest.mark.asyncio
async def test_load_latest_incomplete_approved_plan(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "sluice.db")
    await store.initialize()

    complete = Plan(
        tasks=[PlanTask(title="Done", status=TaskStatus.COMPLETED)],
        approved_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    incomplete = Plan(
        tasks=[
            PlanTask(title="Done", status=TaskStatus.COMPLETED),
            PlanTask(title="Waiting", status=TaskStatus.PENDING),
        ],
        approved_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    await store.save_plan(complete)
    await store.save_plan(incomplete)

    loaded = await store.load_latest_incomplete_approved_plan()

    assert loaded is not None
    assert loaded.id == incomplete.id
    assert loaded.tasks[1].title == "Waiting"
