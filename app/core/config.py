from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    core_api_url: str = "http://localhost:3000"
    jwks_url: str = "http://localhost:3000/.well-known/jwks.json"
    log_level: str = "INFO"

    # No default: a missing or misspelled LLM_PROVIDER must stop startup, never fall back to fake.
    # Only providers with an adapter: a new one is a new LlmClient class plus its name here.
    llm_provider: Literal["fake", "deepseek", "openai", "anthropic"]
    llm_model: str = ""  # empty: the adapter's default (openai has none and requires it)
    llm_timeout_seconds: float = 30.0
    llm_max_output_tokens: int = 3000  # 1500 cut big posts mid-JSON (real LLM trial 2026-11-05)
    # env name kept (SUMMARY_LLM_KILL); field named as a question (RULES §4.1)
    is_summary_llm_killed: bool = Field(default=False, validation_alias="SUMMARY_LLM_KILL")
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    openai_api_key: SecretStr = SecretStr("")  # same variable as /moderate uses
    openai_base_url: str = "https://api.openai.com/v1"
    # Reasoning models (gpt-5 family, o-series) need it or spend the output cap on thinking;
    # empty for models without reasoning, which reject the field.
    openai_reasoning_effort: str = "minimal"
    anthropic_api_key: SecretStr = SecretStr("")
    # USD per 1M tokens for LLM_MODEL; required for openai, optional elsewhere (the adapter
    # knows its default model's price). Every LLM call records its cost (RULES §10).
    llm_price_input: float | None = None
    llm_price_cached_input: float | None = None
    llm_price_output: float | None = None

    # Service client created with core's auth:create-service-client (secret printed once).
    service_client_id: str = "ai-service"
    service_client_secret: SecretStr = SecretStr("")
    redis_url: str = "redis://localhost:6379/0"

    # Comment classifier bundle, baked into the image (scripts/fetch_classifier.py); missing
    # means rules. Threads set explicitly: onnxruntime defaults to the host's physical cores,
    # not the container's CPU limit. 2 threads, batch 8: ~19 comments/s (BAO_CAO benchmark).
    classifier_dir: Path = Path(__file__).resolve().parents[1] / "models" / "comment_classifier"
    classifier_threads: int = Field(default=2, ge=1)
    classifier_batch: int = Field(default=8, ge=1)
    # Unplug the classifier without a rebuild: false means rules only.
    is_classifier_enabled: bool = Field(default=True, validation_alias="CLASSIFIER_ENABLED")
    # ~25 s at ~19 comments/s, so one big post cannot hold the worker; the rest use rules.
    classifier_max_comments: int = Field(default=500, ge=1)  # [HIỆU CHỈNH]


@cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  # required fields come from env


class ModerationSettings(BaseSettings):
    """Settings of the API process's POST /moderate (TF32).

    Separate from Settings: the ai-service container gets no LLM_PROVIDER (core's compose sets
    only CORE_API_URL, REDIS_URL, OPENAI_API_KEY), and moderation must not need it.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr = SecretStr("")  # empty: /moderate answers 503
    openai_base_url: str = "https://api.openai.com/v1"
    moderation_model: str = "omni-moderation-latest"
    # Core waits 3 s, then falls back to its regex: answer (or give up) before that.
    moderation_timeout_seconds: float = Field(default=2.5, gt=0)

    # Core's service tokens (libs/auth/src/service-token.ts): ES256, typ "service".
    core_api_url: str = "http://localhost:3000"
    jwks_url: str = ""  # empty: {core_api_url}/.well-known/jwks.json
    auth_jwt_issuer: str = "tripflix-core"
    service_audience: str = "ai-service"
    moderation_callers: tuple[str, ...] = ("core-api",)

    @property
    def resolved_jwks_url(self) -> str:
        return self.jwks_url or f"{self.core_api_url.rstrip('/')}/.well-known/jwks.json"


@cache
def get_moderation_settings() -> ModerationSettings:
    return ModerationSettings()
