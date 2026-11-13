"""HTTP client for core-api: the only way tripflix-ai reads business data (RULES §10).

Endpoints agreed with content (Thành, PR be #49 and #54):
- GET  /api/v1/posts                             public published posts, cursor, max 50 per page
- GET  /api/v1/posts/:id                          public post detail (trip already PII-masked)
- GET  /api/v1/posts/:id/comments?flat=true       every level, cursor paging, max 200 per page
- GET  /api/v1/posts/:id/ai-summary               last summary with inputHash, 404 if none
- PUT  /api/v1/posts/:id/ai-summary               service token, @ServiceOnly('ai-service')
- PUT  /api/v1/posts/:id/ai-summary/checked       service token; same input as the saved row:
                                                  core moves its staleness mark, 200 {updated}
- GET  /api/v1/posts/:id/comments/sample          service token; seeded sample of visible
                                                  comments, max 5,000, with whole-post stats
- GET  /api/v1/internal/ai-summary/reconciliation service token; posts whose summary core holds
                                                  back for a hidden source, cursor, max 200
(sample and reconciliation: Thành, PR be #128, 2026-11-11)
Service token: POST /api/auth/service-token, lives 300 s; reused until 30 s before expiry,
as in the access module README. Responses are validated here, at the trust boundary.
"""

import time
from collections.abc import Callable, Iterator
from datetime import datetime

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, SecretStr
from pydantic.alias_generators import to_camel

from app.services.summary.schemas import SaveSummaryRequest

PAGE_SIZE = 200  # flat mode cap in core
POST_PAGE_SIZE = 50  # public post list cap in core
HELD_PAGE_SIZE = 200  # reconciliation cap in core
# shortcut: newest 50 pages (10k comments) per run; comments older than a year are filtered
# out anyway (L2). Raise if a post ever has more fresh comments than that.
MAX_PAGES = 50
TOKEN_MARGIN_SECONDS = 30
TIMEOUT_SECONDS = 10.0


class _CoreModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class CoreItineraryItem(_CoreModel):
    title: str = ""
    location: str | None = None


class CoreTripAttachment(_CoreModel):
    hotel_name: str | None = None
    destination_name: str | None = None
    items: list[CoreItineraryItem] = []


class CorePost(_CoreModel):
    id: str
    author_id: str
    title: str = ""
    body: str = ""
    trip_attachment: CoreTripAttachment | None = None


class _PostDetail(_CoreModel):
    post: CorePost


class CorePostListItem(_CoreModel):
    id: str
    comment_count: int = 0


class _PostPage(_CoreModel):
    items: list[CorePostListItem]
    next_cursor: str | None = None


class CoreComment(_CoreModel):
    id: str
    author_id: str
    parent_comment_id: str | None = None
    body: str
    like_count: int = 0  # likeCount, added by be PR #58 (comment reactions)
    is_edited: bool = False
    created_at: AwareDatetime
    updated_at: AwareDatetime


class _CommentPage(_CoreModel):
    items: list[CoreComment]
    next_cursor: str | None = None


class CoreSampleComment(_CoreModel):
    id: str
    author_id: str
    parent_comment_id: str | None = None
    parent_comment_body: str | None = None  # null when the parent is hidden or deleted
    body: str
    like_count: int = 0
    created_at: AwareDatetime
    edited_at: AwareDatetime | None = None


class CoreCommentStats(_CoreModel):
    visible_comment_count: int  # every visible comment, the post author's included
    unique_author_count: int


class CoreCommentSample(_CoreModel):
    stats: CoreCommentStats
    items: list[CoreSampleComment]


class _HeldPage(_CoreModel):
    post_ids: list[str]
    next_cursor: str | None = None


class _CheckedBody(_CoreModel):
    input_hash: str
    checked_at: datetime
    comment_count: int


class _CheckedResult(_CoreModel):
    updated: bool


class SampleUnavailableError(Exception):
    """Core has no sample route (older core): read the newest pages instead."""


class CoreSummary(_CoreModel):
    status: str
    input_hash: str | None = None
    source_comment_ids: list[str] | None = None  # missing on rows saved before the field
    updated_at: datetime | None = None


class CoreApiClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: SecretStr,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http = http or httpx.Client(base_url=base_url, timeout=TIMEOUT_SECONDS)
        self.client_id = client_id
        self.client_secret = client_secret
        self.clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    def fetch_post(self, post_id: str) -> CorePost | None:
        """None when the post is gone, hidden or private (core answers 404)."""
        response = self.http.get(f"/api/v1/posts/{post_id}")
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()
        return _PostDetail.model_validate(response.json()).post

    def iter_public_posts(self) -> Iterator[CorePostListItem]:
        """Every published public post, newest first (what users can open)."""
        cursor: str | None = None
        while True:
            params: dict[str, str | int] = {"limit": POST_PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            response = self.http.get("/api/v1/posts", params=params)
            response.raise_for_status()
            page = _PostPage.model_validate(response.json())
            yield from page.items
            cursor = page.next_cursor
            if not cursor:
                return

    def fetch_comments(self, post_id: str) -> list[CoreComment]:
        comments: list[CoreComment] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, str | int] = {"flat": "true", "limit": PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            response = self.http.get(f"/api/v1/posts/{post_id}/comments", params=params)
            response.raise_for_status()
            page = _CommentPage.model_validate(response.json())
            comments += page.items
            cursor = page.next_cursor
            if not cursor:
                break
        return comments

    def fetch_comment_sample(self, post_id: str, size: int, seed: str) -> CoreCommentSample:
        """Same seed and same comments give the same sample (core orders by hashtext(id||seed)).
        Called after fetch_post found the post, so a 404 here means the route is missing."""
        response = self.http.get(
            f"/api/v1/posts/{post_id}/comments/sample",
            params={"size": size, "seed": seed},
            headers=self._auth(),
        )
        if response.status_code in (httpx.codes.NOT_FOUND, httpx.codes.METHOD_NOT_ALLOWED):
            raise SampleUnavailableError(f"core answered {response.status_code}")
        response.raise_for_status()
        return CoreCommentSample.model_validate(response.json())

    def iter_held_summaries(self) -> Iterator[str]:
        """Posts whose summary core holds back because a source comment is hidden or gone."""
        cursor: str | None = None
        while True:
            params: dict[str, str | int] = {"limit": HELD_PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            response = self.http.get(
                "/api/v1/internal/ai-summary/reconciliation", params=params, headers=self._auth()
            )
            response.raise_for_status()
            page = _HeldPage.model_validate(response.json())
            yield from page.post_ids
            cursor = page.next_cursor
            if not cursor:
                return

    def fetch_summary(self, post_id: str) -> CoreSummary | None:
        response = self.http.get(f"/api/v1/posts/{post_id}/ai-summary")
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()
        return CoreSummary.model_validate(response.json())

    def save_summary(self, post_id: str, request: SaveSummaryRequest) -> None:
        response = self.http.put(
            f"/api/v1/posts/{post_id}/ai-summary",
            json=request.model_dump(mode="json", by_alias=True),
            headers=self._auth(),
        )
        response.raise_for_status()

    def mark_checked(
        self, post_id: str, input_hash: str, checked_at: datetime, comment_count: int
    ) -> bool:
        """Tell core the saved summary still matches the input as of checked_at. Core applies it
        only when input_hash matches its row and checked_at is newer than generatedAt and the
        last check, and answers 200 {updated} either way. False when it did not apply it, the
        post is gone (404) or core has no such route yet (an older core: 404/405)."""
        body = _CheckedBody(
            input_hash=input_hash, checked_at=checked_at, comment_count=comment_count
        )
        response = self.http.put(
            f"/api/v1/posts/{post_id}/ai-summary/checked",
            json=body.model_dump(mode="json", by_alias=True),
            headers=self._auth(),
        )
        if response.status_code in (httpx.codes.NOT_FOUND, httpx.codes.METHOD_NOT_ALLOWED):
            return False
        response.raise_for_status()
        return _CheckedResult.model_validate_json(response.content).updated

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._service_token()}"}

    def _service_token(self) -> str:
        if self._token and self.clock() < self._token_expires_at - TOKEN_MARGIN_SECONDS:
            return self._token
        response = self.http.post(
            "/api/auth/service-token",
            json={
                "clientId": self.client_id,
                "clientSecret": self.client_secret.get_secret_value(),
                "audience": "core-api",
            },
        )
        response.raise_for_status()
        data = response.json()
        self._token = str(data["accessToken"])
        self._token_expires_at = self.clock() + float(data["expiresIn"])
        return self._token
