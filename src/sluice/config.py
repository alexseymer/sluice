"""Application configuration via environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SluiceSettings(BaseSettings):
    """All configuration is supplied via env vars or a mounted .env file."""

    model_config = SettingsConfigDict(
        env_prefix="SLUICE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    data_dir: Path = Field(default=Path(".sluice-data"))
    database_url: str = Field(default="sqlite+aiosqlite:///.sluice-data/sluice.db")
    log_level: str = Field(default="INFO")

    # Jour fixe
    jour_fixe_cron: str = Field(default="0 9 * * *")
    jour_fixe_timeout_minutes: int = Field(default=60)
    jour_fixe_scheduler_enabled: bool = Field(default=True)
    plan_auto_approve: bool = Field(default=False)
    planner_backend: str | None = None
    dispatch_poll_seconds: int = Field(default=30)
    forge_sync_poll_seconds: int = Field(default=60)

    # Chat (Phase 1: matrix or signal)
    chat_backend: str = Field(default="matrix")
    matrix_homeserver: str | None = None
    matrix_room_id: str | None = None
    matrix_access_token: str | None = None
    matrix_user_id: str | None = None
    matrix_allowed_sender: str | None = None
    matrix_sync_timeout_ms: int = Field(default=30_000)
    signal_phone_number: str | None = None
    signal_recipient: str | None = None

    # Forge (Phase 1: github)
    forge_backend: str = Field(default="github")
    github_owner: str | None = None
    github_repo: str | None = None
    github_token: str | None = None
    # Public OAuth App client ID used by `sluice setup` device flow (not a secret).
    github_oauth_client_id: str | None = None

    # AI backends — comma-separated list: claude_code,cursor,agy
    ai_backends: str = Field(default="claude_code,cursor,agy")
    default_backend: str | None = None
    budget_safety_margin: float = Field(default=0.85)  # legacy; probing ignores this
    backend_dispatch_timeout_seconds: int = Field(default=3600)

    # Claude Code
    claude_code_cli_path: str = Field(default="claude")
    claude_code_max_requests: int = Field(default=50)  # cautious starting point; probed empirically
    claude_code_window_seconds: int = Field(default=5 * 60 * 60)
    claude_code_skip_permissions: bool = Field(default=True)

    # Cursor Agent CLI
    cursor_cli_path: str = Field(default="agent")
    cursor_max_requests: int = Field(default=200)
    cursor_window_seconds: int = Field(default=30 * 24 * 60 * 60)
    cursor_output_format: str = Field(default="text")
    cursor_force: bool = Field(default=True)
    cursor_trust_workspace: bool = Field(default=True)

    # Antigravity CLI (agy)
    agy_cli_path: str = Field(default="agy")
    agy_max_requests: int = Field(default=20)
    agy_window_seconds: int = Field(default=24 * 60 * 60)
    agy_mode: str = Field(default="accept-edits")
    agy_skip_permissions: bool = Field(default=True)

    # OpenAI Codex CLI
    codex_cli_path: str = Field(default="codex")
    codex_max_requests: int = Field(default=50)
    codex_window_seconds: int = Field(default=5 * 60 * 60)
    codex_sandbox: str = Field(default="workspace-write")
    codex_ephemeral: bool = Field(default=True)
    codex_skip_git_repo_check: bool = Field(default=True)

    # Deprecated: use ai_backends instead
    ai_backend: str = Field(default="claude_code")

    # Worktrees
    worktree_base_dir: Path = Field(default=Path(".sluice-data/worktrees"))

    @property
    def sqlite_path(self) -> Path:
        if self.database_url.startswith("sqlite"):
            # sqlite+aiosqlite:////data/sluice.db -> /data/sluice.db
            return Path(self.database_url.rsplit("/", maxsplit=1)[-1])
        return self.data_dir / "sluice.db"

    def enabled_backend_ids(self) -> list[str]:
        raw = self.ai_backends.strip()
        if not raw:
            return [self.ai_backend]
        return [backend.strip() for backend in raw.split(",") if backend.strip()]


def load_settings() -> SluiceSettings:
    return SluiceSettings()
