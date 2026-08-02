"""Tests for chat loop command handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sluice.adapters.chat import IncomingMessage
from sluice.core.chat_loop import handle_message
from sluice.core.jour_fixe import JourFixeManager, JourFixeSession
from sluice.core.plan_approval import PlanApprovalManager
from sluice.models.plan import Plan, PlanTask


@pytest.fixture
def app() -> MagicMock:
    mock = MagicMock()
    mock.chat = AsyncMock()
    mock.chat.send = AsyncMock()
    mock.jour_fixe = MagicMock(spec=JourFixeManager)
    mock.jour_fixe.active_session = None
    mock.jour_fixe.start_session = AsyncMock(return_value=JourFixeSession())
    mock.jour_fixe.handle_message = AsyncMock()
    mock.jour_fixe.close_session = AsyncMock()
    mock.plan_approval = MagicMock(spec=PlanApprovalManager)
    mock.plan_approval.has_pending_plan = False
    mock.plan_approval.pending_plan = None
    mock.plan_approval.submit = AsyncMock()
    mock.plan_approval.approve = AsyncMock()
    mock.plan_approval.reject = AsyncMock()
    mock.plan_approval.format_plan = MagicMock(return_value="Plan summary")
    mock.plan_approval.format_filed_summary = MagicMock(return_value="Issues created")
    mock.scheduler = MagicMock()
    mock.scheduler.schedule_plan = AsyncMock(return_value=[])
    mock.store = AsyncMock()
    mock.store.save_plan = AsyncMock()
    mock.chat.is_configured = True
    mock.active_plan = None
    mock.settings = MagicMock()
    mock.settings.plan_auto_approve = False
    return mock


@pytest.mark.asyncio
async def test_help_command(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/help", sender="@you:example.com"))
    app.chat.send.assert_awaited_once()
    assert "/jour-fixe" in app.chat.send.await_args.args[0].text


@pytest.mark.asyncio
async def test_start_jour_fixe(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/jour-fixe", sender="@you:example.com"))
    app.jour_fixe.start_session.assert_awaited_once()
    app.chat.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_jour_fixe_alias_without_hyphen(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/jourfixe", sender="@you:example.com"))
    app.jour_fixe.start_session.assert_awaited_once()
    app.chat.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_done_without_session(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/done", sender="@you:example.com"))
    app.jour_fixe.close_session.assert_not_awaited()
    assert "No active jour fixe" in app.chat.send.await_args.args[0].text


@pytest.mark.asyncio
async def test_done_submits_plan_for_approval(app: MagicMock) -> None:
    plan = Plan(tasks=[PlanTask(title="Ship feature")])
    app.jour_fixe.active_session = JourFixeSession()
    app.jour_fixe.close_session = AsyncMock(return_value=plan)

    await handle_message(app, IncomingMessage(text="/done", sender="@you:example.com"))

    app.plan_approval.submit.assert_awaited_once_with(plan)
    app.chat.send.assert_awaited()
    assert app.chat.send.await_args.args[0].text == "Plan summary"


@pytest.mark.asyncio
async def test_approve_files_plan(app: MagicMock) -> None:
    plan = Plan(tasks=[PlanTask(title="Ship feature")])
    app.plan_approval.approve = AsyncMock(return_value=plan)

    await handle_message(app, IncomingMessage(text="/approve", sender="@you:example.com"))

    app.plan_approval.approve.assert_awaited_once()
    app.scheduler.schedule_plan.assert_awaited_once_with(plan)
    assert app.active_plan is plan
    assert app.chat.send.await_args.args[0].text == "Issues created"


@pytest.mark.asyncio
async def test_plain_message_forwarded_to_jour_fixe(app: MagicMock) -> None:
    message = IncomingMessage(text="Build auth module", sender="@you:example.com")
    await handle_message(app, message)
    app.jour_fixe.handle_message.assert_awaited_once_with(message)
