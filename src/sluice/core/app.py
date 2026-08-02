"""Top-level application orchestrator."""

from __future__ import annotations

import structlog

from sluice.adapters.backend_factory import build_backends
from sluice.adapters.github_forge import GitHubForgeAdapter
from sluice.adapters.matrix_chat import MatrixChatAdapter
from sluice.config import SluiceSettings
from sluice.core.budget import BudgetManager
from sluice.core.jour_fixe import JourFixeManager
from sluice.core.plan_approval import PlanApprovalManager
from sluice.core.planner import Planner
from sluice.core.scheduler import Scheduler
from sluice.models.plan import Plan
from sluice.store.sqlite import SQLiteStateStore

log = structlog.get_logger()


class SluiceApp:
    """Wires adapters, core components, and persistence together."""

    def __init__(self, settings: SluiceSettings) -> None:
        self.settings = settings
        self.store = SQLiteStateStore(settings.sqlite_path)
        self.chat = self._build_chat(settings)
        self.forge = self._build_forge(settings)
        self.backends = build_backends(settings, self.store)
        self.budget_manager = BudgetManager(self.backends)
        self.planner = Planner()
        self.jour_fixe = JourFixeManager(
            chat=self.chat,
            planner=self.planner,
            cron_expression=settings.jour_fixe_cron,
            timeout_minutes=settings.jour_fixe_timeout_minutes,
        )
        self.scheduler = Scheduler(
            backends=self.backends,
            budget_manager=self.budget_manager,
            worktree_base=settings.worktree_base_dir,
            default_backend=settings.default_backend,
        )
        self.plan_approval = PlanApprovalManager(
            forge=self.forge,
            store=self.store,
            auto_approve=settings.plan_auto_approve,
        )
        self.active_plan: Plan | None = None

    async def start(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.worktree_base_dir.mkdir(parents=True, exist_ok=True)
        await self.store.initialize()
        for backend in self.backends.values():
            initialize = getattr(backend, "initialize", None)
            if callable(initialize):
                await initialize()
        await self.chat.start()
        await self.forge.start()
        await self._restore_active_plan()
        log.info("sluice_started", version="0.1.0")

    async def _restore_active_plan(self) -> None:
        plan = await self.store.load_latest_incomplete_approved_plan()
        if plan is None:
            return

        self.active_plan = plan
        slots = await self.scheduler.schedule_ready_tasks(plan)
        log.info(
            "active_plan_restored",
            plan_id=str(plan.id),
            tasks=len(plan.tasks),
            queued_slots=len(slots),
        )

    async def stop(self) -> None:
        await self.chat.stop()
        await self.forge.close()
        log.info("sluice_stopped")

    @staticmethod
    def _build_chat(settings: SluiceSettings) -> MatrixChatAdapter:
        if settings.chat_backend == "matrix":
            return MatrixChatAdapter(
                homeserver=settings.matrix_homeserver or "",
                room_id=settings.matrix_room_id or "",
                access_token=settings.matrix_access_token or "",
                user_id=settings.matrix_user_id,
                allowed_sender=settings.matrix_allowed_sender,
                store_path=settings.data_dir / "matrix-store",
                sync_timeout_ms=settings.matrix_sync_timeout_ms,
            )
        raise NotImplementedError(f"Chat backend {settings.chat_backend!r} not yet supported")

    @staticmethod
    def _build_forge(settings: SluiceSettings) -> GitHubForgeAdapter:
        if settings.forge_backend == "github":
            return GitHubForgeAdapter(
                owner=settings.github_owner or "",
                repo=settings.github_repo or "",
                token=settings.github_token or "",
            )
        raise NotImplementedError(f"Forge backend {settings.forge_backend!r} not yet supported")
