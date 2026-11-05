"""HTTP client for core-api: the only way tripflix-ai reads business data (RULES §10).

Endpoints agreed with content (Thành, PR be #49 and #54):
- GET  /api/v1/posts                             public published posts, cursor, max 50 per page
- GET  /api/v1/posts/:id                          public post detail (trip already PII-masked)
- GET  /api/v1/posts/:id/comments?flat=true       every level, cursor paging, max 200 per page
- GET  /api/v1/posts/:id/ai-summary               last summary with inputHash, 404 if none
- PUT  /api/v1/posts/:id/ai-summary               service token, @ServiceOnly('ai-service')
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
# shortcut: newest 50 pages (10k comments) per run; comments older than a year are filtered
# out anyway (L3). Raise if a post ever has more fresh comments than that.
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


class CoreSummary(_CoreModel):
    status: str
    input_hash: str | None = None
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
            headers={"Authorization": f"Bearer {self._service_token()}"},
        )
        response.raise_for_status()

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
