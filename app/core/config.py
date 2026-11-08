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
    llm_provider: Literal["fake", "deepseek", "openai", "anthropic"]
    llm_model: str = ""
    llm_timeout_seconds: float = 30.0
    llm_max_output_tokens: int = 3000  # 1500 cut big posts mid-JSON (real LLM trial 2026-11-05)
    # env name kept (SUMMARY_LLM_KILL); field named as a question (RULES §4.1)
    is_summary_llm_killed: bool = Field(default=False, validation_alias="SUMMARY_LLM_KILL")
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"

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


@cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  # required fields come from env
