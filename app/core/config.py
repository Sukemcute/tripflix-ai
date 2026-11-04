from functools import cache
from typing import Literal

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
    llm_max_output_tokens: int = 1500
    summary_llm_kill: bool = False


@cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  # required fields come from env
