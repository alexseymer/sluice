"""Tests for application configuration."""

from pathlib import Path

from sluice.config import SluiceSettings


def test_default_settings() -> None:
    settings = SluiceSettings()
    assert settings.chat_backend == "matrix"
    assert settings.forge_backend == "github"
    assert settings.enabled_backend_ids() == ["cursor", "agy"]
    assert settings.budget_safety_margin == 0.85


def test_enabled_backend_ids_falls_back_to_legacy_ai_backend() -> None:
    settings = SluiceSettings(ai_backends="", ai_backend="cursor")
    assert settings.enabled_backend_ids() == ["cursor"]


def test_sqlite_path_from_absolute_aiosqlite_url() -> None:
    settings = SluiceSettings(database_url="sqlite+aiosqlite:////data/sluice.db")
    assert settings.sqlite_path == Path("/data/sluice.db")


def test_sqlite_path_from_relative_aiosqlite_url() -> None:
    settings = SluiceSettings(database_url="sqlite+aiosqlite:///.sluice-data/sluice.db")
    assert settings.sqlite_path == Path(".sluice-data/sluice.db")


def test_sqlite_path_falls_back_to_data_dir() -> None:
    settings = SluiceSettings(
        data_dir=Path("/tmp/sluice-data"),
        database_url="postgres://example",
    )
    assert settings.sqlite_path == Path("/tmp/sluice-data/sluice.db")
