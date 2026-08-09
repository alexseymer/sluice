"""Top-level application orchestrator."""

from __future__ import annotations

import structlog

from sluice.adapters.backend import BackendAdapter
from sluice.adapters.backend_factory import build_backends
from sluice.adapters.chat import OutgoingMessage
from sluice.adapters.github_forge import GitHubForgeAdapter
from sluice.adapters.matrix_chat import MatrixChatAdapter
from sluice.config import SluiceSettings
from sluice.core.budget import BudgetManager
from sluice.core.casual_chat import CasualChatManager
from sluice.core.escalation import find_pending_escalation, format_escalation_message
from sluice.core.jour_fixe import JourFixeManager
from sluice.core.jour_fixe_chat import JourFixeLlmSettings
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
        conversation_backend = self._resolve_backend(
            settings,
            self.backends,
            preferred=(
                settings.planner_backend,
                settings.default_backend,
            ),
        )
        orchestrator_backend = self._resolve_backend(
            settings,
            self.backends,
            preferred=(
                settings.orchestrator_backend,
                settings.planner_backend,
                settings.default_backend,
            ),
        )
        reviewer_backend = self._resolve_backend(
            settings,
            self.backends,
            preferred=(settings.reviewer_backend,),
        )
        self.planner = Planner(
            orchestrator=orchestrator_backend,
            worktree_base=settings.data_dir / "planner",
            enabled_backends=settings.enabled_backend_ids(),
        )
        self.jour_fixe = JourFixeManager(
            chat=self.chat,
            planner=self.planner,
            cron_expression=settings.jour_fixe_cron,
            timeout_minutes=settings.jour_fixe_timeout_minutes,
            conversation_backend=conversation_backend,
            worktree_base=settings.data_dir / "planner",
            llm=JourFixeLlmSettings(
                base_url=settings.jour_fixe_llm_base_url,
                api_key=settings.jour_fixe_llm_api_key,
                model=settings.jour_fixe_llm_model,
            ),
        )
        self.casual_chat = CasualChatManager(
            chat=self.chat,
            conversation_backend=conversation_backend,
            worktree_base=settings.data_dir / "casual-chat",
        )
        self.scheduler = Scheduler(
            backends=self.backends,
            budget_manager=self.budget_manager,
            worktree_base=settings.worktree_base_dir,
            default_backend=settings.default_backend,
            reviewer_backend=reviewer_backend,
            max_review_iterations=settings.max_review_iterations,
            dispatch_poll_seconds=settings.dispatch_poll_seconds,
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
        escalation = find_pending_escalation(plan)
        if escalation is not None and self.chat.is_configured:
            await self.chat.send(OutgoingMessage(text=format_escalation_message(escalation)))

    async def stop(self) -> None:
        await self.chat.stop()
        await self.forge.close()
        log.info("sluice_stopped")

    @staticmethod
    def _resolve_backend(
        settings: SluiceSettings,
        backends: dict[str, BackendAdapter],
        *,
        preferred: tuple[str | None, ...],
    ) -> BackendAdapter | None:
        """Pick the first configured backend from preferred ids, then ai_backends."""
        candidates: list[str] = [name for name in preferred if name]
        candidates.extend(
            part.strip() for part in settings.ai_backends.split(",") if part.strip()
        )
        seen: set[str] = set()
        for name in candidates:
            if name in seen:
                continue
            seen.add(name)
            backend = backends.get(name)
            if backend is not None:
                return backend
        return None

    @staticmethod
    def _resolve_conversation_backend(
        settings: SluiceSettings,
        backends: dict[str, BackendAdapter],
    ) -> BackendAdapter | None:
        """Pick planner → default → first configured AI backend for jour fixe chat."""
        return SluiceApp._resolve_backend(
            settings,
            backends,
            preferred=(settings.planner_backend, settings.default_backend),
        )

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
