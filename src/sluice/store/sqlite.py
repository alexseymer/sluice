"""SQLite-backed state persistence."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import aiosqlite

from sluice.models.plan import Plan


class SQLiteStateStore:
    """Persists plans, schedules, and budget counters across restarts."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    approved_at TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS budget_usage (
                    backend_id TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    used_units INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (backend_id, window_start)
                )
                """
            )
            await db.commit()

    async def save_plan(self, plan: Plan) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO plans (id, data, created_at, approved_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(plan.id),
                    plan.model_dump_json(),
                    plan.created_at.isoformat(),
                    plan.approved_at.isoformat() if plan.approved_at else None,
                ),
            )
            await db.commit()

    async def load_plan(self, plan_id: UUID) -> Plan | None:
        async with (
            aiosqlite.connect(self._db_path) as db,
            db.execute(
                "SELECT data FROM plans WHERE id = ?",
                (str(plan_id),),
            ) as cursor,
        ):
            row = await cursor.fetchone()
            if row is None:
                return None
            return Plan.model_validate(json.loads(row[0]))

    async def record_budget_usage(
        self, backend_id: str, window_start: str, used_units: int
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO budget_usage (backend_id, window_start, used_units)
                VALUES (?, ?, ?)
                ON CONFLICT(backend_id, window_start)
                DO UPDATE SET used_units = excluded.used_units
                """,
                (backend_id, window_start, used_units),
            )
            await db.commit()

    async def get_budget_usage(self, backend_id: str, window_start: str) -> int:
        async with (
            aiosqlite.connect(self._db_path) as db,
            db.execute(
                """
                SELECT used_units FROM budget_usage
                WHERE backend_id = ? AND window_start = ?
                """,
                (backend_id, window_start),
            ) as cursor,
        ):
            row = await cursor.fetchone()
            if row is None:
                return 0
            return int(row[0])
