"""POST /embed: core's recommend job turns post captions into unit vectors (TF28).

Core caches vectors by text hash and compares them with its own bin descriptions, so this
endpoint stays model-only. Core treats any error as "no vectors" and keeps tag-only bins.
"""

import threading
from functools import cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.api.auth import require_core_caller
from app.api.moderation import _CamelModel
from app.clients.embedding import E5Embedder, load_embedder
from app.core.config import get_moderation_settings

MAX_TEXTS = 64
MAX_TEXT_CHARS = 2_000  # 256 tokens are kept; longer text only costs tokenizer time

router = APIRouter(tags=["embedding"])


class EmbedRequest(_CamelModel):
    texts: list[Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARS)]] = Field(
        min_length=1, max_length=MAX_TEXTS
    )


class EmbedResponse(_CamelModel):
    model: str
    vectors: list[list[float]]


_LOAD_LOCK = threading.Lock()


@cache
def _load_embedder() -> E5Embedder:
    # One thread: the box has 2 vCPU shared with every other service.
    return load_embedder(get_moderation_settings().embedding_dir, threads=1, batch_size=16)


def get_embedder() -> E5Embedder:
    # Sync dependency runs in the thread pool and @cache does not lock while loading: two first
    # requests at once would load the model twice (~880 MB). The lock keeps it to one load.
    with _LOAD_LOCK:
        try:
            return _load_embedder()
        except (OSError, ValueError) as error:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "embedding bundle is unavailable"
            ) from error


@router.post("/embed", response_model=EmbedResponse)
def embed(  # sync: inference blocks, FastAPI runs it in its thread pool
    body: EmbedRequest,
    _caller: Annotated[str, Depends(require_core_caller)],  # first: no 503 hint before auth
    embedder: Annotated[E5Embedder, Depends(get_embedder)],
) -> EmbedResponse:
    vectors = embedder.embed(body.texts)
    return EmbedResponse(
        model=embedder.model, vectors=[[round(float(x), 6) for x in v] for v in vectors]
    )
