from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def load() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  # required fields come from env


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Run from an empty dir so a developer's local .env cannot leak into the assertions.
    monkeypatch.chdir(tmp_path)
    for name in ("LLM_MODEL", "LLM_TIMEOUT_SECONDS", "SUMMARY_LLM_KILL", "LLM_MAX_OUTPUT_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "fake")


def test_missing_provider_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER")

    with pytest.raises(ValidationError):
        load()


def test_defaults() -> None:
    settings = load()

    assert settings.llm_timeout_seconds == 30.0
    assert settings.llm_max_output_tokens == 3000
    assert settings.summary_llm_kill is False


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("SUMMARY_LLM_KILL", "true")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "2000")

    settings = load()

    assert settings.llm_provider == "openai"
    assert settings.summary_llm_kill is True
    assert settings.llm_max_output_tokens == 2000


def test_unknown_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    with pytest.raises(ValidationError):
        load()
