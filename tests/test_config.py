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
    for name in (
        "LLM_MODEL",
        "LLM_TIMEOUT_SECONDS",
        "SUMMARY_LLM_KILL",
        "LLM_MAX_OUTPUT_TOKENS",
        "CLASSIFIER_THREADS",
        "CLASSIFIER_BATCH",
    ):
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
    assert settings.is_summary_llm_killed is False
    assert settings.classifier_threads == 2 and settings.classifier_batch == 8
    assert settings.classifier_dir.parts[-3:] == ("app", "models", "comment_classifier")


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("SUMMARY_LLM_KILL", "true")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "2000")
    monkeypatch.setenv("CLASSIFIER_ENABLED", "false")
    monkeypatch.setenv("CLASSIFIER_MAX_COMMENTS", "200")

    settings = load()

    assert settings.llm_provider == "deepseek"
    assert settings.is_summary_llm_killed is True
    assert settings.llm_max_output_tokens == 2000
    assert settings.is_classifier_enabled is False
    assert settings.classifier_max_comments == 200


@pytest.mark.parametrize("provider", ["fake", "deepseek", "openai", "anthropic"])
def test_every_provider_with_an_adapter_is_accepted(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", provider)

    assert load().llm_provider == provider


def test_provider_without_an_adapter_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    with pytest.raises(ValidationError):
        load()


def test_deepseek_provider_reads_its_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    settings = load()

    assert settings.llm_provider == "deepseek"
    assert settings.deepseek_api_key.get_secret_value() == "sk-test"
    assert "sk-test" not in repr(settings)  # SecretStr keeps it out of logs
