"""Incoming chat message dispatch and jour fixe commands."""

from __future__ import annotations

import structlog

from sluice.adapters.chat import IncomingMessage, OutgoingMessage
from sluice.core.app import SluiceApp
from sluice.core.dispatch_loop import on_plan_approved
from sluice.core.plan_approval import PlanApprovalError
from sluice.models.plan import Plan

log = structlog.get_logger()

HELP_TEXT = """Sluice commands:
  /jour-fixe  — start a jour fixe session
  /done       — finish the session and generate a plan
  /plan       — show the plan awaiting approval
  /approve    — approve the plan and create GitHub issues
  /reject     — discard the plan awaiting approval
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


async def finalize_jour_fixe(app: SluiceApp) -> Plan | None:
    """Close the active jour fixe session and submit the generated plan."""
    if app.jour_fixe.active_session is None or not app.jour_fixe.active_session.is_active:
        return None

    plan = await app.jour_fixe.close_session()
    await app.plan_approval.submit(plan)
    await app.chat.send(OutgoingMessage(text=app.plan_approval.format_plan(plan)))
    if app.settings.plan_auto_approve:
        approved = await app.plan_approval.approve()
        await app.chat.send(
            OutgoingMessage(text=app.plan_approval.format_filed_summary(approved))
        )
        await on_plan_approved(app, approved)
    log.info("jour_fixe_closed", plan_id=str(plan.id), tasks=len(plan.tasks))
    return plan


async def approve_plan(app: SluiceApp) -> Plan:
    """Approve the pending plan, file issues, and schedule dispatch."""
    plan = await app.plan_approval.approve()
    await on_plan_approved(app, plan)
    return plan


async def handle_message(app: SluiceApp, message: IncomingMessage) -> None:
    command = message.text.strip().lower()

    if command in {"/help", "help"}:
        await app.chat.send(OutgoingMessage(text=HELP_TEXT))
        return

    if command in {"/jour-fixe", "/start", "jour fixe"}:
        if app.plan_approval.has_pending_plan:
            await app.chat.send(
                OutgoingMessage(
                    text="A plan is already awaiting approval. `/approve` or `/reject` it first."
                )
            )
            return
        session = await app.jour_fixe.start_session()
        await app.chat.send(
            OutgoingMessage(
                text=f"Jour fixe started (session {session.id}). What should we work on today?"
            )
        )
        return

    if command == "/status":
        session = app.jour_fixe.active_session
        if session is not None and session.is_active:
            await app.chat.send(
                OutgoingMessage(
                    text=(
                        f"Active jour fixe since {session.started_at.isoformat()} "
                        f"with {len(session.messages)} message(s) collected."
                    )
                )
            )
            return
        if app.plan_approval.has_pending_plan and app.plan_approval.pending_plan is not None:
            plan = app.plan_approval.pending_plan
            await app.chat.send(
                OutgoingMessage(
                    text=(
                        f"No active jour fixe. Plan {plan.id} awaits approval "
                        f"({len(plan.tasks)} tasks)."
                    )
                )
            )
            return
        await app.chat.send(OutgoingMessage(text="No active jour fixe session or pending plan."))
        return

    if command == "/plan":
        if not app.plan_approval.has_pending_plan or app.plan_approval.pending_plan is None:
            await app.chat.send(OutgoingMessage(text="No plan is awaiting approval."))
            return
        await app.chat.send(
            OutgoingMessage(text=app.plan_approval.format_plan(app.plan_approval.pending_plan))
        )
        return

    if command == "/approve":
        try:
            plan = await approve_plan(app)
        except PlanApprovalError as exc:
            await app.chat.send(OutgoingMessage(text=str(exc)))
            return
        await app.chat.send(OutgoingMessage(text=app.plan_approval.format_filed_summary(plan)))
        return

    if command == "/reject":
        try:
            await app.plan_approval.reject()
        except PlanApprovalError as exc:
            await app.chat.send(OutgoingMessage(text=str(exc)))
            return
        await app.chat.send(OutgoingMessage(text="Plan rejected."))
        return

    if command == "/done":
        if app.jour_fixe.active_session is None or not app.jour_fixe.active_session.is_active:
            await app.chat.send(OutgoingMessage(text="No active jour fixe session to close."))
            return
        await finalize_jour_fixe(app)
        return

    await app.jour_fixe.handle_message(message)
