"""Cron-triggered jour fixe sessions and session timeout handling."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog

from sluice.adapters.chat import OutgoingMessage
from sluice.core.app import SluiceApp
from sluice.core.chat_loop import finalize_jour_fixe

log = structlog.get_logger()

_TIMEOUT_CHECK_SECONDS = 30


async def run_jour_fixe_scheduler(app: SluiceApp) -> None:
    """Start sessions on cron and auto-close them after the configured timeout."""
    if not app.settings.jour_fixe_scheduler_enabled:
        log.info("jour_fixe_scheduler_disabled")
        return

    log.info(
        "jour_fixe_scheduler_started",
        cron=app.settings.jour_fixe_cron,
        timeout_minutes=app.settings.jour_fixe_timeout_minutes,
        next_at=str(app.jour_fixe.next_scheduled_at()),
    )

    await asyncio.gather(
        _cron_loop(app),
        _timeout_loop(app),
    )


async def _cron_loop(app: SluiceApp) -> None:
    while True:
        next_at = app.jour_fixe.next_scheduled_at()
        delay = (next_at - datetime.now(UTC)).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)

        await _maybe_start_scheduled_session(app)
        await asyncio.sleep(1)


async def _timeout_loop(app: SluiceApp) -> None:
    while True:
        await asyncio.sleep(_TIMEOUT_CHECK_SECONDS)
        if not app.jour_fixe.is_session_timed_out():
            continue

        log.info(
            "jour_fixe_timeout",
            timeout_minutes=app.settings.jour_fixe_timeout_minutes,
        )
        if app.chat.is_configured:
            await app.chat.send(
                OutgoingMessage(
                    text=(
                        "Jour fixe timed out — closing the session and generating a plan "
                        "from collected messages."
                    )
                )
            )
        await finalize_jour_fixe(app)


async def _maybe_start_scheduled_session(app: SluiceApp) -> None:
    if not app.chat.is_configured:
        return

    if not app.jour_fixe.can_start_scheduled_session(
        has_pending_plan=app.plan_approval.has_pending_plan
    ):
        return

    session = await app.jour_fixe.start_session()
    log.info("jour_fixe_scheduled_start", session_id=str(session.id))
