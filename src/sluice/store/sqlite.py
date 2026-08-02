"""SQLite-backed state persistence."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import aiosqlite

from sluice.models.budget_state import BudgetState
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
                CREATE TABLE IF NOT EXISTS budget_state (
                    backend_id TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    used_units INTEGER NOT NULL DEFAULT 0,
                    cautious_limit INTEGER NOT NULL,
                    observed_limit INTEGER,
                    exhausted INTEGER NOT NULL DEFAULT 0,
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

    async def get_budget_state(
        self,
        backend_id: str,
        window_start: str,
        cautious_limit: int,
    ) -> BudgetState:
        async with (
            aiosqlite.connect(self._db_path) as db,
            db.execute(
                """
                SELECT used_units, cautious_limit, observed_limit, exhausted
                FROM budget_state
                WHERE backend_id = ? AND window_start = ?
                """,
                (backend_id, window_start),
            ) as cursor,
        ):
            row = await cursor.fetchone()
            if row is None:
                return BudgetState(
                    backend_id=backend_id,
                    window_start=window_start,
                    used_units=0,
                    cautious_limit=cautious_limit,
                )
            return BudgetState(
                backend_id=backend_id,
                window_start=window_start,
                used_units=int(row[0]),
                cautious_limit=int(row[1]),
                observed_limit=int(row[2]) if row[2] is not None else None,
                exhausted=bool(row[3]),
            )

    async def record_budget_attempt(
        self,
        backend_id: str,
        window_start: str,
        cautious_limit: int,
    ) -> BudgetState:
        state = await self.get_budget_state(backend_id, window_start, cautious_limit)
        state.used_units += 1
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO budget_state (
                    backend_id, window_start, used_units, cautious_limit,
                    observed_limit, exhausted
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(backend_id, window_start)
                DO UPDATE SET used_units = excluded.used_units
                """,
                (
                    backend_id,
                    window_start,
                    state.used_units,
                    cautious_limit,
                    state.observed_limit,
                    int(state.exhausted),
                ),
            )
            await db.commit()
        return state

    async def record_quota_limit(
        self,
        backend_id: str,
        window_start: str,
        cautious_limit: int,
        *,
        failed_attempt: int,
    ) -> BudgetState:
        observed_limit = max(0, failed_attempt - 1)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO budget_state (
                    backend_id, window_start, used_units, cautious_limit,
                    observed_limit, exhausted
                )
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(backend_id, window_start)
                DO UPDATE SET
                    observed_limit = excluded.observed_limit,
                    exhausted = 1,
                    cautious_limit = excluded.cautious_limit
                """,
                (
                    backend_id,
                    window_start,
                    failed_attempt,
                    cautious_limit,
                    observed_limit,
                ),
            )
            await db.commit()
        return await self.get_budget_state(backend_id, window_start, cautious_limit)

    # Legacy helpers kept for compatibility with older tests/code paths.
    async def record_budget_usage(
        self, backend_id: str, window_start: str, used_units: int
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO budget_state (backend_id, window_start, used_units, cautious_limit)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(backend_id, window_start)
                DO UPDATE SET used_units = excluded.used_units
                """,
                (backend_id, window_start, used_units),
            )
            await db.commit()

    async def get_budget_usage(self, backend_id: str, window_start: str) -> int:
        state = await self.get_budget_state(backend_id, window_start, cautious_limit=0)
        return state.used_units
