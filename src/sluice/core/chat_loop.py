"""Incoming chat message dispatch and jour fixe commands."""

from __future__ import annotations

import re

import structlog

from sluice.adapters.chat import IncomingMessage, OutgoingMessage
from sluice.core.app import SluiceApp
from sluice.core.dispatch_loop import on_plan_approved
from sluice.core.plan_approval import PlanApprovalError
from sluice.models.plan import Plan
from sluice.setup.cli_runtime import bootstrap_ai_clis

log = structlog.get_logger()

HELP_TEXT = """We're here to talk through the work — status quo, how to handle problems,
then a concrete plan I'll coordinate afterward.

When you want to meet, say `/jour-fixe` (or just "jour fixe").
When you're ready to wrap up, say you're done (or `/done`) and I'll summarize the plan.
Then `/approve` to file issues, or `/reject` to discard.

Other: `/status`, `/plan`, `/cli-auth`, `/help`"""

_NATURAL_CLOSE = frozenset(
    {
        "done",
        "that's all",
        "thats all",
        "that is all",
        "wrap up",
        "wrap-up",
        "let's wrap up",
        "lets wrap up",
        "finished",
        "i'm done",
        "im done",
        "i am done",
        "we're done",
        "we are done",
        "end session",
        "close session",
        "close",
        "all done",
        "that'll do",
        "thatll do",
    }
)

_START_COMMANDS = frozenset({"/jour-fixe", "/jourfixe", "/start", "jour fixe"})


def is_natural_close(text: str) -> bool:
    """Return True when the human is wrapping up the jour fixe in plain language."""
    normalized = re.sub(r"[.!?,;:]+$", "", text.strip().lower())
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized in _NATURAL_CLOSE


async def run_chat_loop(app: SluiceApp) -> None:
    """Run until cancelled, processing chat messages when configured."""
    if not app.chat.is_configured:
        log.warning("chat_disabled", reason="Matrix credentials not configured")
        return

    log.info("chat_loop_started")
    async for message in app.chat.listen():
        try:
            await handle_message(app, message)
        except Exception:
            log.exception("chat_message_failed", sender=message.sender)
            try:
                await app.chat.send(
                    OutgoingMessage(
                        text=(
                            "Something went wrong handling that message. "
                            "The session should still be open — try again."
                        )
                    )
                )
            except Exception:
                log.exception("chat_error_notice_failed")


async def finalize_jour_fixe(app: SluiceApp) -> Plan | None:
    """Close the active jour fixe session and submit the generated plan."""
    if app.jour_fixe.active_session is None or not app.jour_fixe.active_session.is_active:
        return None

    await app.chat.send(
        OutgoingMessage(text="Alright — I'll shape what we agreed into issues for your review…")
    )
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
    log.info("chat_command", sender=message.sender, command=command[:80])

    if command in {"/help", "help"}:
        await app.chat.send(OutgoingMessage(text=HELP_TEXT))
        return

    if command in {"/cli-auth", "/auth-cli", "/cli-login"}:
        drain = getattr(app.chat, "drain_pending_messages", None)
        if callable(drain):
            drain()
        await bootstrap_ai_clis(
            settings=app.settings,
            chat=app.chat,
            home=app.settings.resolved_cli_home_dir,
        )
        return

    if command in _START_COMMANDS:
        if app.plan_approval.has_pending_plan:
            await app.chat.send(
                OutgoingMessage(
                    text=(
                        "There's still a plan waiting on your say-so. "
                        "`/approve` to file it, or `/reject` to throw it out, "
                        "then we can meet again."
                    )
                )
            )
            return
        await app.jour_fixe.start_session()
        return

    if command == "/status":
        session = app.jour_fixe.active_session
        if session is not None and session.is_active:
            human_turns = sum(1 for t in session.turns if t.role == "human")
            await app.chat.send(
                OutgoingMessage(
                    text=(
                        f"We're in a jour fixe right now "
                        f"({human_turns} note(s) from you so far). "
                        "Keep talking, or say you're done when you want the plan."
                    )
                )
            )
            return
        if app.plan_approval.has_pending_plan and app.plan_approval.pending_plan is not None:
            plan = app.plan_approval.pending_plan
            await app.chat.send(
                OutgoingMessage(
                    text=(
                        f"No meeting running. A plan with {len(plan.tasks)} task(s) "
                        "is waiting for `/approve` or `/reject`."
                    )
                )
            )
            return
        next_at = app.jour_fixe.next_scheduled_at()
        await app.chat.send(
            OutgoingMessage(
                text=(
                    "Nothing active right now. "
                    f"Next scheduled jour fixe: {next_at.isoformat()}. "
                    "Or say `/jour-fixe` to start one now."
                )
            )
        )
        return

    if command == "/plan":
        if not app.plan_approval.has_pending_plan or app.plan_approval.pending_plan is None:
            await app.chat.send(OutgoingMessage(text="No plan is waiting for approval."))
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
        await app.chat.send(
            OutgoingMessage(text="Okay — plan discarded. We can start a fresh jour fixe whenever.")
        )
        return

    session = app.jour_fixe.active_session
    session_active = session is not None and session.is_active

    if command == "/done" or is_natural_close(command):
        if not session_active:
            await app.chat.send(
                OutgoingMessage(text="No jour fixe is running to close.")
            )
            return
        await finalize_jour_fixe(app)
        return

    if not session_active:
        await app.chat.send(
            OutgoingMessage(
                text=(
                    "No jour fixe running — say `/jour-fixe` when you want to meet "
                    "and we'll start with where things stand."
                )
            )
        )
        return

    await app.jour_fixe.handle_message(message)
