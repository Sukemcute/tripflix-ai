"""POST /moderate: core sends post and comment text and images, gets flags back (TF32).

Contract agreed with Trang (content/moderation, 2026-11-09). Core calls with a 3 s timeout and
falls back to its regex step on any error, so errors are whole-request: 502 provider error,
504 too slow, 503 not configured.
"""

import base64
import binascii
from functools import cache
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.api.auth import require_core_caller
from app.clients.moderation.base import (
    ModerationClient,
    ModerationTimeoutError,
    ModerationUpstreamError,
)
from app.clients.moderation.cover_ocr import CoverOcrError, OpenAICoverOcr, estimate_cost
from app.clients.moderation.openai import OpenAIModerationClient
from app.clients.moderation.visobert import VisobertModeration, load_visobert
from app.core.config import ModerationSettings, get_moderation_settings
from app.services.moderation import ModerationItem, moderate_items
from app.services.moderation_parts import PartInput, moderate_parts
from app.services.moderation_shadow import log_safety_shadow
from app.services.usage_events import CoverOcrUsage, ModerationUsage, UsageEvent, publish_usage

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


class ModeratePart(_CamelModel):
    id: str = Field(min_length=1, max_length=200)
    kind: Literal["caption", "image"]
    text: str = Field(default="", max_length=20_000)
    image_url: HttpsUrl | None = None

    @model_validator(mode="after")
    def separate_inputs(self) -> "ModeratePart":
        if self.kind == "caption" and (not self.text.strip() or self.image_url):
            raise ValueError("caption requires text only")
        if self.kind == "image" and (self.text or not self.image_url):
            raise ValueError("image requires exactly one URL and no caption")
        return self


class ModeratePartsRequest(_CamelModel):
    items: list[ModeratePart] = Field(min_length=1, max_length=MAX_ITEMS)

    @model_validator(mode="after")
    def unique_ids(self) -> "ModeratePartsRequest":
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("part IDs must be unique")
        return self


class ModeratePartResult(_CamelModel):
    id: str
    status: Literal["passed", "flagged", "error"]
    categories: dict[str, bool]
    scores: dict[str, float]
    model: str | None
    error_code: str | None


class ModeratePartsResponse(_CamelModel):
    results: list[ModeratePartResult]


class CoverOcrRequest(_CamelModel):
    image_base64: str = Field(min_length=4, max_length=2_800_000)


class CoverOcrResponse(_CamelModel):
    status: Literal["passed", "flagged", "error"]
    extracted_text: str = Field(max_length=5000)
    categories: dict[str, bool]
    scores: dict[str, float]
    model: str | None
    error_code: str | None


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
    model = pairs[0][1].model
    usage = UsageEvent(
        payload=ModerationUsage(
            model=model, items=len(items), images=sum(len(item.image_urls) for item in items)
        )
    )
    background_tasks.add_task(publish_usage, [usage])
    if settings.is_moderation_safety_shadow_enabled:
        background_tasks.add_task(log_safety_shadow, items, pairs)
    return ModerateResponse(
        results=[
            ModerateResult(id=item_id, flagged=r.flagged, categories=r.categories, scores=r.scores)
            for item_id, r in pairs
        ],
        model=model,
    )


@router.post("/moderate/parts", response_model=ModeratePartsResponse)
async def moderate_separate_parts(
    body: ModeratePartsRequest,
    background_tasks: BackgroundTasks,
    _caller: Annotated[str, Depends(require_core_caller)],
    client: Annotated[ModerationClient | None, Depends(get_moderation_client)],
    settings: Annotated[ModerationSettings, Depends(get_moderation_settings)],
    visobert: Annotated[VisobertModeration | None, Depends(get_visobert_client)],
) -> ModeratePartsResponse:
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "moderation is not configured")
    results = await moderate_parts(
        [PartInput(item.id, item.kind, item.text, item.image_url) for item in body.items],
        client,
        settings.moderation_timeout_seconds,
        visobert,
    )
    background_tasks.add_task(
        publish_usage,
        [
            UsageEvent(
                payload=ModerationUsage(
                    model=settings.moderation_model,
                    items=len(body.items),
                    images=sum(item.kind == "image" for item in body.items),
                )
            )
        ],
    )
    return ModeratePartsResponse(
        results=[
            ModeratePartResult(
                id=result.id,
                status=result.status,
                categories=result.categories,
                scores=result.scores,
                model=result.model,
                error_code=result.error_code,
            )
            for result in results
        ]
    )


@router.post("/moderate/cover-ocr", response_model=CoverOcrResponse)
async def moderate_cover_ocr(
    body: CoverOcrRequest,
    background_tasks: BackgroundTasks,
    _caller: Annotated[str, Depends(require_core_caller)],
    client: Annotated[ModerationClient | None, Depends(get_moderation_client)],
    settings: Annotated[ModerationSettings, Depends(get_moderation_settings)],
) -> CoverOcrResponse:
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "moderation is not configured")
    try:
        jpeg = base64.b64decode(body.image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "invalid image") from exc
    if not 4 <= len(jpeg) <= 2_000_000 or not jpeg.startswith(b"\xff\xd8\xff"):
        raise HTTPException(422, "expected JPEG poster up to 2 MB")
    ocr = OpenAICoverOcr(
        settings.openai_api_key,
        model=settings.cover_ocr_model,
        base_url=settings.openai_base_url,
    )
    completed = False
    try:
        text = await ocr.read(jpeg)
        completed = True
        if not text:
            return CoverOcrResponse(
                status="passed",
                extracted_text="",
                categories={},
                scores={},
                model=settings.cover_ocr_model,
                error_code=None,
            )
        verdict = (
            await moderate_parts(
                [PartInput("cover", "caption", text, None)],
                client,
                settings.moderation_timeout_seconds,
            )
        )[0]
        return CoverOcrResponse(
            status=verdict.status,
            extracted_text=text,
            categories=verdict.categories,
            scores=verdict.scores,
            model=f"{settings.cover_ocr_model}+{verdict.model}" if verdict.model else None,
            error_code=verdict.error_code,
        )
    except CoverOcrError:
        return CoverOcrResponse(
            status="error",
            extracted_text="",
            categories={},
            scores={},
            model=None,
            error_code="ocr_unavailable",
        )
    finally:
        if ocr.called:
            tokens = ocr.usage
            background_tasks.add_task(
                publish_usage,
                [
                    UsageEvent(
                        payload=CoverOcrUsage(
                            model=tokens.model if tokens else settings.cover_ocr_model,
                            step=("completed" if completed else "error")
                            if tokens
                            else "usage_missing",
                            input_tokens=tokens.input_tokens if tokens else None,
                            output_tokens=tokens.output_tokens if tokens else None,
                            cost_usd=estimate_cost(
                                tokens,
                                input_price=settings.cover_ocr_price_input,
                                cached_price=settings.cover_ocr_price_cached_input,
                                output_price=settings.cover_ocr_price_output,
                            )
                            if tokens
                            else 0,
                        )
                    )
                ],
            )
        await ocr.aclose()
