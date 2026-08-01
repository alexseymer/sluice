"""Tests for application configuration."""

from sluice.config import SluiceSettings


def test_default_settings() -> None:
    settings = SluiceSettings()
    assert settings.chat_backend == "matrix"
    assert settings.forge_backend == "github"
    assert settings.ai_backend == "claude_code"
    assert settings.budget_safety_margin == 0.85
