"""Incoming chat message dispatch and jour fixe commands."""

from __future__ import annotations

import structlog

from sluice.adapters.chat import IncomingMessage, OutgoingMessage
from sluice.core.app import SluiceApp

log = structlog.get_logger()

HELP_TEXT = """Sluice commands:
  /jour-fixe  — start a jour fixe session
  /done       — finish the session and generate a plan
  /status     — show current session status
  /help       — show this message"""


async def run_chat_loop(app: SluiceApp) -> None:
    """Run until cancelled, processing chat messages when configured."""
    if not app.chat.is_configured:
        log.warning("chat_disabled", reason="Matrix credentials not configured")
        return

    log.info("chat_loop_started")
    async for message in app.chat.listen():
        await handle_message(app, message)


async def handle_message(app: SluiceApp, message: IncomingMessage) -> None:
    command = message.text.strip().lower()

    if command in {"/help", "help"}:
        await app.chat.send(OutgoingMessage(text=HELP_TEXT))
        return

    if command in {"/jour-fixe", "/start", "jour fixe"}:
        session = await app.jour_fixe.start_session()
        await app.chat.send(
            OutgoingMessage(
                text=f"Jour fixe started (session {session.id}). What should we work on today?"
            )
        )
        return

    if command == "/status":
        session = app.jour_fixe.active_session
        if session is None or not session.is_active:
            await app.chat.send(OutgoingMessage(text="No active jour fixe session."))
            return
        await app.chat.send(
            OutgoingMessage(
                text=(
                    f"Active jour fixe since {session.started_at.isoformat()} "
                    f"with {len(session.messages)} message(s) collected."
                )
            )
        )
        return

    if command == "/done":
        if app.jour_fixe.active_session is None or not app.jour_fixe.active_session.is_active:
            await app.chat.send(OutgoingMessage(text="No active jour fixe session to close."))
            return
        plan = await app.jour_fixe.close_session()
        log.info("jour_fixe_closed", plan_id=str(plan.id), tasks=len(plan.tasks))
        return

    await app.jour_fixe.handle_message(message)
