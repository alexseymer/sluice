"""Tests for chat loop command handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sluice.adapters.chat import IncomingMessage
from sluice.core.chat_loop import handle_message, is_natural_close
from sluice.core.jour_fixe import JourFixeManager, JourFixeSession
from sluice.core.plan_approval import PlanApprovalManager
from sluice.models.budget import BudgetSnapshot, BudgetWindow
from sluice.models.plan import Plan, PlanTask, TaskStatus


def _budget_snapshot(
    backend_id: str,
    *,
    used: int,
    cautious: int,
    observed: int | None = None,
    exhausted: bool = False,
) -> BudgetSnapshot:
    return BudgetSnapshot(
        backend_id=backend_id,
        used_units=used,
        window=BudgetWindow(
            backend_id=backend_id,
            window_seconds=3600,
            cautious_limit=cautious,
            observed_limit=observed,
        ),
        is_exhausted=exhausted,
    )


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
    mock.jour_fixe.next_scheduled_at = MagicMock(return_value=MagicMock(isoformat=lambda: "soon"))
    mock.casual_chat = MagicMock()
    mock.casual_chat.handle_message = AsyncMock()
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
    mock.backends = {}
    mock.budget_manager = None
    mock.settings = MagicMock()
    mock.settings.plan_auto_approve = False
    mock.settings.enabled_backend_ids = MagicMock(return_value=["cursor", "agy"])
    return mock


def _attach_budgets(app: MagicMock, snapshots: dict[str, BudgetSnapshot]) -> None:
    app.backends = {backend_id: MagicMock() for backend_id in snapshots}
    app.budget_manager = MagicMock()
    app.budget_manager.snapshot = AsyncMock(side_effect=lambda bid: snapshots[bid])


@pytest.mark.asyncio
async def test_help_command(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/help", sender="@you:example.com"))
    app.chat.send.assert_awaited_once()
    assert "/jour-fixe" in app.chat.send.await_args.args[0].text
    assert "/backend" in app.chat.send.await_args.args[0].text


@pytest.mark.asyncio
async def test_backend_command_sets_and_clears(app: MagicMock) -> None:
    plan = Plan(
        tasks=[
            PlanTask(title="Schema", backend_id=None),
            PlanTask(title="API", backend_id="cursor"),
        ]
    )
    app.plan_approval.has_pending_plan = True
    app.plan_approval.pending_plan = plan
    app.plan_approval.format_plan = MagicMock(return_value="Updated plan")

    await handle_message(
        app, IncomingMessage(text="/backend 1 cursor", sender="@you:example.com")
    )
    assert plan.tasks[0].backend_id == "cursor"
    app.store.save_plan.assert_awaited_once_with(plan)
    assert app.chat.send.await_args.args[0].text == "Updated plan"

    app.chat.send.reset_mock()
    app.store.save_plan.reset_mock()
    await handle_message(app, IncomingMessage(text="/assign 2 auto", sender="@you:example.com"))
    assert plan.tasks[1].backend_id is None
    app.store.save_plan.assert_awaited_once_with(plan)


@pytest.mark.asyncio
async def test_backend_command_rejects_unknown(app: MagicMock) -> None:
    plan = Plan(tasks=[PlanTask(title="Schema")])
    app.plan_approval.has_pending_plan = True
    app.plan_approval.pending_plan = plan

    await handle_message(
        app, IncomingMessage(text="/backend 1 codex", sender="@you:example.com")
    )

    assert plan.tasks[0].backend_id is None
    app.store.save_plan.assert_not_awaited()
    text = app.chat.send.await_args.args[0].text
    assert "Unknown backend" in text
    assert "cursor" in text


@pytest.mark.asyncio
async def test_backend_command_without_pending_plan(app: MagicMock) -> None:
    await handle_message(
        app, IncomingMessage(text="/backend 1 cursor", sender="@you:example.com")
    )
    assert "No plan is waiting" in app.chat.send.await_args.args[0].text
    app.store.save_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_jour_fixe(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/jour-fixe", sender="@you:example.com"))
    app.jour_fixe.start_session.assert_awaited_once()
    # Opener is sent inside start_session; chat_loop should not double-announce.
    app.chat.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_jour_fixe_alias_without_hyphen(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/jourfixe", sender="@you:example.com"))
    app.jour_fixe.start_session.assert_awaited_once()
    app.chat.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_done_without_session(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/done", sender="@you:example.com"))
    app.jour_fixe.close_session.assert_not_awaited()
    assert "No jour fixe" in app.chat.send.await_args.args[0].text


@pytest.mark.asyncio
async def test_done_submits_plan_for_approval(app: MagicMock) -> None:
    plan = Plan(tasks=[PlanTask(title="Ship feature")])
    app.jour_fixe.active_session = JourFixeSession()
    app.jour_fixe.close_session = AsyncMock(return_value=plan)

    await handle_message(app, IncomingMessage(text="/done", sender="@you:example.com"))

    app.plan_approval.submit.assert_awaited_once_with(plan)
    assert any(
        call.args[0].text == "Plan summary" for call in app.chat.send.await_args_list
    )


@pytest.mark.asyncio
async def test_natural_close_finalizes_session(app: MagicMock) -> None:
    plan = Plan(tasks=[PlanTask(title="Ship feature")])
    app.jour_fixe.active_session = JourFixeSession()
    app.jour_fixe.close_session = AsyncMock(return_value=plan)

    await handle_message(app, IncomingMessage(text="that's all", sender="@you:example.com"))

    app.plan_approval.submit.assert_awaited_once_with(plan)
    assert is_natural_close("that's all")


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
    app.jour_fixe.active_session = JourFixeSession()
    message = IncomingMessage(text="Build auth module", sender="@you:example.com")
    await handle_message(app, message)
    app.jour_fixe.handle_message.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_plain_message_outside_session_uses_casual_chat(app: MagicMock) -> None:
    message = IncomingMessage(text="Build auth module", sender="@you:example.com")
    await handle_message(app, message)
    app.jour_fixe.handle_message.assert_not_awaited()
    app.casual_chat.handle_message.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_natural_close_outside_session_uses_casual_chat(app: MagicMock) -> None:
    message = IncomingMessage(text="that's all", sender="@you:example.com")
    await handle_message(app, message)
    app.jour_fixe.close_session.assert_not_awaited()
    app.casual_chat.handle_message.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_status_idle_includes_budgets(app: MagicMock) -> None:
    _attach_budgets(
        app,
        {
            "cursor": _budget_snapshot("cursor", used=3, cautious=10),
            "agy": _budget_snapshot(
                "agy", used=5, cautious=5, observed=5, exhausted=True
            ),
        },
    )

    await handle_message(app, IncomingMessage(text="/status", sender="@you:example.com"))

    text = app.chat.send.await_args.args[0].text
    assert "Nothing active right now" in text
    assert "cursor: 3/10" in text
    assert "agy: 5/5 exhausted" in text


@pytest.mark.asyncio
async def test_status_pending_plan_includes_budgets(app: MagicMock) -> None:
    app.plan_approval.has_pending_plan = True
    app.plan_approval.pending_plan = Plan(tasks=[PlanTask(title="Schema")])
    _attach_budgets(
        app,
        {
            "cursor": _budget_snapshot("cursor", used=10, cautious=10),
        },
    )

    await handle_message(app, IncomingMessage(text="/status", sender="@you:example.com"))

    text = app.chat.send.await_args.args[0].text
    assert "waiting for `/approve`" in text
    assert "cursor: 10/10 probing" in text


@pytest.mark.asyncio
async def test_status_active_plan_includes_budgets(app: MagicMock) -> None:
    app.active_plan = Plan(
        tasks=[
            PlanTask(title="Done", status=TaskStatus.COMPLETED),
            PlanTask(title="WIP", status=TaskStatus.IN_PROGRESS),
        ]
    )
    _attach_budgets(
        app,
        {"cursor": _budget_snapshot("cursor", used=1, cautious=20)},
    )

    await handle_message(app, IncomingMessage(text="/status", sender="@you:example.com"))

    text = app.chat.send.await_args.args[0].text
    assert "Working an approved plan: 1/2 issue(s) complete." in text
    assert "cursor: 1/20" in text


@pytest.mark.asyncio
async def test_status_without_backends_omits_budget_lines(app: MagicMock) -> None:
    await handle_message(app, IncomingMessage(text="/status", sender="@you:example.com"))
    text = app.chat.send.await_args.args[0].text
    assert "Nothing active right now" in text
    assert "exhausted" not in text
    assert "probing" not in text
    assert not any(
        line.startswith(("cursor:", "agy:", "claude_code:", "codex:"))
        for line in text.splitlines()
    )
