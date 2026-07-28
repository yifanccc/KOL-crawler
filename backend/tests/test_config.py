import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_startup_backfill_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("STARTUP_BACKFILL_ENABLED", raising=False)

    settings = Settings(_env_file=None)

    assert settings.startup_backfill_enabled is False


def test_model_defaults_to_deepseek_chat_completions(monkeypatch) -> None:
    for key in (
        "MODEL_API_STYLE",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "MODEL_REASONING_EFFORT",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.model_api_style == "chat_completions"
    assert settings.openai_base_url == "https://api.deepseek.com"
    assert settings.openai_model == "deepseek-v4-pro"
    assert settings.model_reasoning_effort == "high"


def test_model_provider_keeps_deepseek_and_openai_keys_separate(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("OPENAI_MODEL", "deepseek-v4-pro")

    settings = Settings(_env_file=None)

    assert settings.deepseek_api_key == "deepseek-key"
    assert settings.openai_api_key == "legacy-key"
    assert settings.model_api_key == "deepseek-key"

    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.5")
    settings = Settings(_env_file=None)

    assert settings.deepseek_api_key == "deepseek-key"
    assert settings.openai_api_key == "legacy-key"
    assert settings.model_api_key == "legacy-key"


def test_model_api_style_accepts_chat_completions(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_API_STYLE", "chat_completions")

    settings = Settings(_env_file=None)

    assert settings.model_api_style == "chat_completions"


def test_model_api_style_rejects_unknown_protocol(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_API_STYLE", "unknown")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
