"""Tests for jour fixe scheduler and session timeout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from sluice.core.jour_fixe import JourFixeManager, JourFixeSession
from sluice.core.jour_fixe_scheduler import _maybe_start_scheduled_session
from sluice.core.planner import Planner


@pytest.fixture
def jour_fixe() -> JourFixeManager:
    chat = AsyncMock()
    chat.is_configured = True
    chat.start_jour_fixe_prompt = AsyncMock()
    return JourFixeManager(chat=chat, planner=Planner(), cron_expression="0 9 * * *")


def test_next_scheduled_at_is_utc_aware(jour_fixe: JourFixeManager) -> None:
    next_at = jour_fixe.next_scheduled_at()
    again = jour_fixe.next_scheduled_at()

    assert next_at.tzinfo is not None
    assert next_at.utcoffset() == timedelta(0)
    assert again == next_at
    # Peeks must not crash when subtracting from aware now (scheduler loop).
    assert (next_at - datetime.now(UTC)).total_seconds() > 0


def test_session_timeout_detected(jour_fixe: JourFixeManager) -> None:
    session = JourFixeSession()
    session.started_at = datetime.now(UTC) - timedelta(minutes=61)
    jour_fixe._session = session

    assert jour_fixe.is_session_timed_out() is True


def test_active_session_not_timed_out(jour_fixe: JourFixeManager) -> None:
    jour_fixe._session = JourFixeSession()
    assert jour_fixe.is_session_timed_out() is False


def test_can_start_scheduled_session_blocks_active_session(jour_fixe: JourFixeManager) -> None:
    jour_fixe._session = JourFixeSession()
    assert jour_fixe.can_start_scheduled_session(has_pending_plan=False) is False


def test_can_start_scheduled_session_blocks_pending_plan(jour_fixe: JourFixeManager) -> None:
    assert jour_fixe.can_start_scheduled_session(has_pending_plan=True) is False


@pytest.mark.asyncio
async def test_scheduled_start_skips_when_chat_unconfigured(jour_fixe: JourFixeManager) -> None:
    app = MagicMock()
    app.chat = jour_fixe._chat
    app.chat.is_configured = False
    app.jour_fixe = jour_fixe
    app.plan_approval = MagicMock()
    app.plan_approval.has_pending_plan = False

    await _maybe_start_scheduled_session(app)

    jour_fixe._chat.start_jour_fixe_prompt.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_start_opens_session(jour_fixe: JourFixeManager) -> None:
    app = MagicMock()
    app.chat = jour_fixe._chat
    app.chat.is_configured = True
    app.jour_fixe = jour_fixe
    app.plan_approval = MagicMock()
    app.plan_approval.has_pending_plan = False

    await _maybe_start_scheduled_session(app)

    jour_fixe._chat.start_jour_fixe_prompt.assert_awaited_once()
    assert jour_fixe.active_session is not None
