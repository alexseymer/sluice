"""Tests for application configuration."""

from sluice.config import SluiceSettings


def test_default_settings() -> None:
    settings = SluiceSettings()
    assert settings.chat_backend == "matrix"
    assert settings.forge_backend == "github"
    assert settings.enabled_backend_ids() == ["claude_code", "cursor", "agy"]
    assert settings.budget_safety_margin == 0.85


def test_enabled_backend_ids_falls_back_to_legacy_ai_backend() -> None:
    settings = SluiceSettings(ai_backends="", ai_backend="cursor")
    assert settings.enabled_backend_ids() == ["cursor"]
