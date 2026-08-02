"""Plan review, approval, and GitHub issue filing."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog

from sluice.adapters.forge import ForgeAdapter
from sluice.core.graph import DependencyGraph
from sluice.models.plan import Plan
from sluice.store.sqlite import SQLiteStateStore

log = structlog.get_logger()


class PlanApprovalError(RuntimeError):
    """Raised when a plan cannot be approved or filed."""


class PlanApprovalManager:
    """Holds a pending plan and files it on the forge after human approval."""

    def __init__(
        self,
        forge: ForgeAdapter,
        store: SQLiteStateStore,
        *,
        auto_approve: bool = False,
    ) -> None:
        self._forge = forge
        self._store = store
        self._auto_approve = auto_approve
        self._pending_plan: Plan | None = None

    @property
    def pending_plan(self) -> Plan | None:
        return self._pending_plan

    @property
    def has_pending_plan(self) -> bool:
        return self._pending_plan is not None and not self._pending_plan.is_approved

    async def submit(self, plan: Plan) -> Plan:
        """Store a draft plan awaiting approval."""
        if self.has_pending_plan:
            raise PlanApprovalError(
                "A plan is already awaiting approval. Approve or reject it first."
            )

        await self._store.save_plan(plan)
        self._pending_plan = plan
        log.info("plan_submitted", plan_id=str(plan.id), tasks=len(plan.tasks))
        return plan

    async def approve(self) -> Plan:
        """Approve the pending plan and create forge issues."""
        plan = self._require_pending_plan()
        if not self._forge_is_ready():
            raise PlanApprovalError("GitHub forge is not configured. Set SLUICE_GITHUB_* env vars.")

        filed = await self.file_plan(plan)
        filed.approved_at = datetime.now(UTC)
        await self._store.save_plan(filed)
        self._pending_plan = None
        log.info("plan_approved", plan_id=str(filed.id), tasks=len(filed.tasks))
        return filed

    async def reject(self) -> None:
        """Discard the pending plan without filing issues."""
        if self._pending_plan is None:
            raise PlanApprovalError("No plan is awaiting approval.")
        plan_id = self._pending_plan.id
        self._pending_plan = None
        log.info("plan_rejected", plan_id=str(plan_id))

    async def file_plan(self, plan: Plan) -> Plan:
        """Create forge issues for all tasks and link dependencies."""
        graph = DependencyGraph(plan)
        graph.validate()

        task_to_issue_number: dict[UUID, str] = {}
        for task in plan.tasks:
            issue = await self._forge.create_issue(task)
            task.forge_issue_id = issue.id
            task_to_issue_number[task.id] = issue.id

        for task in plan.tasks:
            if not task.depends_on:
                continue
            issue_id = task_to_issue_number[task.id]
            for dep_id in task.depends_on:
                blocker_id = task_to_issue_number[dep_id]
                await self._forge.link_dependency(issue_id, blocker_id)

        await self._store.save_plan(plan)
        return plan

    def format_plan(self, plan: Plan) -> str:
        """Render a human-readable plan summary for chat."""
        if not plan.tasks:
            return "Plan is empty — no tasks were captured."

        task_index = {task.id: index for index, task in enumerate(plan.tasks, start=1)}
        lines = [f"Plan {plan.id} — {len(plan.tasks)} task(s):"]
        for index, task in enumerate(plan.tasks, start=1):
            deps = ""
            if task.depends_on:
                dep_indexes = [str(task_index[dep_id]) for dep_id in task.depends_on]
                deps = f" (depends on task {', '.join(dep_indexes)})"
            lines.append(f"{index}. {task.title}{deps}")

        if plan.is_approved:
            lines.append("")
            lines.append("Status: approved")
            for task in plan.tasks:
                if task.forge_issue_id:
                    lines.append(f"- #{task.forge_issue_id}: {task.title}")
        else:
            lines.extend(
                [
                    "",
                    "Reply `/approve` to create GitHub issues, or `/reject` to discard.",
                ]
            )
        return "\n".join(lines)

    def format_filed_summary(self, plan: Plan) -> str:
        issues = [
            f"- #{task.forge_issue_id}: {task.title}" for task in plan.tasks if task.forge_issue_id
        ]
        if not issues:
            return "Plan approved, but no issues were created."
        return "Plan approved. Created issues:\n" + "\n".join(issues)

    def _require_pending_plan(self) -> Plan:
        if not self.has_pending_plan or self._pending_plan is None:
            raise PlanApprovalError("No plan is awaiting approval.")
        return self._pending_plan

    def _forge_is_ready(self) -> bool:
        is_configured = getattr(self._forge, "is_configured", None)
        if callable(is_configured):
            return bool(is_configured())
        return True
