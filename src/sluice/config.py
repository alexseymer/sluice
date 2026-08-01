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
    plan_auto_approve: bool = Field(default=False)

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

    # AI backend (Phase 1: claude_code)
    ai_backend: str = Field(default="claude_code")
    claude_code_cli_path: str = Field(default="claude")
    claude_code_max_requests: int = Field(default=50)
    claude_code_window_seconds: int = Field(default=5 * 60 * 60)
    budget_safety_margin: float = Field(default=0.85)

    # Worktrees
    worktree_base_dir: Path = Field(default=Path(".sluice-data/worktrees"))

    @property
    def sqlite_path(self) -> Path:
        if self.database_url.startswith("sqlite"):
            # sqlite+aiosqlite:////data/sluice.db -> /data/sluice.db
            return Path(self.database_url.rsplit("/", maxsplit=1)[-1])
        return self.data_dir / "sluice.db"


def load_settings() -> SluiceSettings:
    return SluiceSettings()
