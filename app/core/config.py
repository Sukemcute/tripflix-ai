from functools import cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    core_api_url: str = "http://localhost:3000"
    jwks_url: str = "http://localhost:3000/.well-known/jwks.json"
    log_level: str = "INFO"

    # No default: a missing or misspelled LLM_PROVIDER must stop startup, never fall back to fake.
    llm_provider: Literal["fake", "openai", "anthropic"]
    llm_model: str = ""
    llm_timeout_seconds: float = 30.0
    llm_max_output_tokens: int = 3000  # 1500 cut big posts mid-JSON (real LLM trial 2026-11-05)
    summary_llm_kill: bool = False

    # Service client created with core's auth:create-service-client (secret printed once).
    service_client_id: str = "ai-service"
    service_client_secret: SecretStr = SecretStr("")
    redis_url: str = "redis://localhost:6379/0"


@cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  # required fields come from env
