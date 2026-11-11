"""POST /moderate: core sends post and comment text and images, gets flags back (TF32).

Contract agreed with Trang (content/moderation, 2026-11-09). Core calls with a 3 s timeout and
falls back to its regex step on any error, so errors are whole-request: 502 provider error,
504 too slow, 503 not configured.
"""

from functools import cache
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.api.auth import require_core_caller
from app.clients.moderation.base import (
    ModerationClient,
    ModerationTimeoutError,
    ModerationUpstreamError,
)
from app.clients.moderation.openai import OpenAIModerationClient
from app.clients.moderation.visobert import VisobertModeration, load_visobert
from app.core.config import ModerationSettings, get_moderation_settings
from app.services.moderation import ModerationItem, moderate_items
from app.services.moderation_shadow import log_safety_shadow

MAX_ITEMS = 20
MAX_TEXT_CHARS = 10_000  # core caps comments at 2,000; posts are longer
MAX_IMAGES = 4

router = APIRouter(tags=["moderation"])


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


HttpsUrl = Annotated[str, Field(pattern=r"^https://\S+$", max_length=2048)]


class ModerateItem(_CamelModel):
    id: str = Field(min_length=1, max_length=200)  # opaque to AI, e.g. "post:<uuid>"
    text: str = Field(default="", max_length=MAX_TEXT_CHARS)
    image_urls: list[HttpsUrl] = Field(default_factory=list, max_length=MAX_IMAGES)

    @model_validator(mode="after")
    def check_not_empty(self) -> "ModerateItem":
        if not self.text.strip() and not self.image_urls:
            raise ValueError("an item needs text or at least one image")
        return self


class ModerateRequest(_CamelModel):
    items: list[ModerateItem] = Field(min_length=1, max_length=MAX_ITEMS)


class ModerateResult(_CamelModel):
    id: str
    flagged: bool
    categories: dict[str, bool]
    scores: dict[str, float]


class ModerateResponse(_CamelModel):
    results: list[ModerateResult]
    model: str


@cache
def get_moderation_client() -> ModerationClient | None:
    settings = get_moderation_settings()
    if not settings.openai_api_key.get_secret_value():
        return None
    return OpenAIModerationClient(
        settings.openai_api_key,
        model=settings.moderation_model,
        base_url=settings.openai_base_url,
        timeout_seconds=settings.moderation_timeout_seconds,
    )


@cache
def get_visobert_client() -> VisobertModeration | None:
    settings = get_moderation_settings()
    if not settings.is_visobert_enabled or not settings.openai_api_key.get_secret_value():
        return None
    try:
        return load_visobert(
            settings.visobert_dir,
            threshold=settings.visobert_threshold,
            threads=settings.visobert_threads,
            batch_size=settings.visobert_batch_size,
            timeout_seconds=min(
                settings.visobert_timeout_seconds, settings.moderation_timeout_seconds * 0.8
            ),
        )
    except (OSError, ValueError) as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "ViSoBERT bundle is unavailable"
        ) from error


@router.post("/moderate", response_model=ModerateResponse)
async def moderate(
    body: ModerateRequest,
    background_tasks: BackgroundTasks,
    _caller: Annotated[str, Depends(require_core_caller)],  # first: no 503 hint before auth
    client: Annotated[ModerationClient | None, Depends(get_moderation_client)],
    settings: Annotated[ModerationSettings, Depends(get_moderation_settings)],
    visobert: Annotated[VisobertModeration | None, Depends(get_visobert_client)],
) -> ModerateResponse:
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "moderation is not configured")
    items = [ModerationItem(i.id, i.text, tuple(i.image_urls)) for i in body.items]
    try:
        pairs = await moderate_items(
            items, client, settings.moderation_timeout_seconds, visobert=visobert
        )
    except ModerationTimeoutError as e:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "moderation timed out") from e
    except ModerationUpstreamError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "moderation provider failed") from e
    if settings.is_moderation_safety_shadow_enabled:
        background_tasks.add_task(log_safety_shadow, items, pairs)
    return ModerateResponse(
        results=[
            ModerateResult(id=item_id, flagged=r.flagged, categories=r.categories, scores=r.scores)
            for item_id, r in pairs
        ],
        model=pairs[0][1].model,
    )
