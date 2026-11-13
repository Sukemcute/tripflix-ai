import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from app.clients.core_api import CoreApiClient, SampleUnavailableError
from app.services.summary.schemas import SaveSummaryRequest

NOW = datetime(2026, 11, 5, tzinfo=UTC)
POST_ID = "018d9f20-0000-7000-8000-000000000001"


def _comment(i: int) -> dict[str, object]:
    return {
        "id": f"c-{i}",
        "postId": POST_ID,
        "authorId": f"u-{i}",
        "parentCommentId": None,
        "body": f"bình luận {i}",
        "likeCount": i,
        "isEdited": False,
        "createdAt": "2026-11-05T08:00:00.000Z",
        "updatedAt": "2026-11-05T08:00:00.000Z",
    }


class FakeCore:
    def __init__(self, has_sample_route: bool = True, checked_status: int = 204) -> None:
        self.requests: list[httpx.Request] = []
        self.now = 0.0
        self.has_sample_route = has_sample_route
        self.checked_status = checked_status

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/auth/service-token":
            return httpx.Response(
                200, json={"accessToken": "tok", "tokenType": "Bearer", "expiresIn": 300}
            )
        if path.endswith("/comments/sample"):
            if not self.has_sample_route:
                return httpx.Response(404, json={"message": "Cannot GET"})
            # the shape of PR be #128 (SampleCommentsResponseDto)
            item = _comment(1) | {
                "parentCommentId": "c-0",
                "parentCommentBody": "Có ai ở đây chưa?",
                "editedAt": None,
            }
            stats = {"visibleCommentCount": 125_000, "uniqueAuthorCount": 48_200}
            return httpx.Response(200, json={"stats": stats, "items": [item]})
        if path == "/api/v1/internal/ai-summary/reconciliation":
            first_page = "cursor" not in request.url.params
            ids = ["p1", "p2"] if first_page else ["p3"]
            return httpx.Response(
                200,
                json={"postIds": ids, "nextCursor": "p2" if first_page else None, "total": 2},
            )
        if path.endswith("/comments"):
            first_page = "cursor" not in request.url.params
            items = [_comment(1), _comment(2)] if first_page else [_comment(3)]
            return httpx.Response(
                200, json={"items": items, "nextCursor": "n1" if first_page else None, "total": 3}
            )
        if path == "/api/v1/posts":
            first_page = "cursor" not in request.url.params
            items = [{"id": "p1", "commentCount": 6}] if first_page else [{"id": "p2"}]
            return httpx.Response(
                200,
                json={
                    "items": items,
                    "nextCursor": "n1" if first_page else None,
                    "hasMore": first_page,
                },
            )
        if path.endswith("/ai-summary/checked"):
            return httpx.Response(self.checked_status)
        if path.endswith("/ai-summary") and request.method == "GET":
            return httpx.Response(404, json={"message": "chưa có"})
        if path.endswith("/ai-summary"):
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json={
                "post": {
                    "id": POST_ID,
                    "authorId": "u-0",
                    "title": "T",
                    "body": "B",
                    "tripAttachment": {"hotelName": "Vinpearl"},
                },
                "viewerContext": {},
                "shareUrl": "",
            },
        )

    def client(self) -> CoreApiClient:
        http = httpx.Client(base_url="http://core", transport=httpx.MockTransport(self.handle))
        return CoreApiClient(
            "http://core", "ai-service", SecretStr("s3cret"), http, clock=lambda: self.now
        )


def test_comments_are_read_page_by_page_in_flat_mode() -> None:
    core = FakeCore()

    comments = core.client().fetch_comments(POST_ID)

    assert [c.id for c in comments] == ["c-1", "c-2", "c-3"]
    assert [c.like_count for c in comments] == [1, 2, 3]
    assert core.requests[0].url.params["flat"] == "true"
    assert core.requests[0].url.params["limit"] == "200"
    assert core.requests[1].url.params["cursor"] == "n1"


def test_missing_summary_is_none_and_post_is_parsed() -> None:
    client = FakeCore().client()

    assert client.fetch_summary(POST_ID) is None
    post = client.fetch_post(POST_ID)
    assert post is not None and post.trip_attachment is not None
    assert post.trip_attachment.hotel_name == "Vinpearl"


def test_put_sends_camel_case_with_a_reused_service_token() -> None:
    core = FakeCore()
    client = core.client()

    client.save_summary(POST_ID, SaveSummaryRequest(status="no_comments", generated_at=NOW))
    core.now = 200  # still more than 30 s before the 300 s expiry
    client.save_summary(POST_ID, SaveSummaryRequest(status="no_comments", generated_at=NOW))
    core.now = 280  # inside the 30 s margin: ask again
    client.save_summary(POST_ID, SaveSummaryRequest(status="no_comments", generated_at=NOW))

    token_calls = [r for r in core.requests if r.url.path == "/api/auth/service-token"]
    puts = [r for r in core.requests if r.method == "PUT"]
    assert len(token_calls) == 2
    assert json.loads(token_calls[0].content)["audience"] == "core-api"
    assert puts[0].headers["Authorization"] == "Bearer tok"
    body = json.loads(puts[0].content)
    assert body["status"] == "no_comments" and "commentCount" in body


def test_public_posts_are_listed_page_by_page() -> None:
    core = FakeCore()

    posts = list(core.client().iter_public_posts())

    assert [(p.id, p.comment_count) for p in posts] == [("p1", 6), ("p2", 0)]
    assert core.requests[0].url.params["limit"] == "50"
    assert core.requests[1].url.params["cursor"] == "n1"


def test_the_sample_is_asked_with_a_service_token_size_and_seed() -> None:
    core = FakeCore()

    sample = core.client().fetch_comment_sample(POST_ID, 3_000, seed=POST_ID)

    request = next(r for r in core.requests if r.url.path.endswith("/sample"))
    assert request.headers["Authorization"] == "Bearer tok"
    assert request.url.params["size"] == "3000" and request.url.params["seed"] == POST_ID
    assert sample.stats.visible_comment_count == 125_000
    assert sample.stats.unique_author_count == 48_200
    [item] = sample.items
    assert item.parent_comment_body == "Có ai ở đây chưa?" and item.edited_at is None


def test_an_older_core_without_the_sample_route_says_so() -> None:
    with pytest.raises(SampleUnavailableError):
        FakeCore(has_sample_route=False).client().fetch_comment_sample(POST_ID, 3_000, "s")


def test_held_summaries_are_read_until_the_cursor_ends() -> None:
    core = FakeCore()

    assert list(core.client().iter_held_summaries()) == ["p1", "p2", "p3"]
    pages = [r for r in core.requests if "reconciliation" in r.url.path]
    assert [r.url.params.get("cursor") for r in pages] == [None, "p2"]
    assert pages[0].url.params["limit"] == "200"
    assert all(r.headers["Authorization"] == "Bearer tok" for r in pages)


def test_checked_sends_hash_time_and_count_with_the_service_token() -> None:
    core = FakeCore()

    assert core.client().mark_checked(POST_ID, "h1", NOW, 125_000) is True

    put = core.requests[-1]
    assert put.method == "PUT" and put.url.path == f"/api/v1/posts/{POST_ID}/ai-summary/checked"
    assert put.headers["Authorization"] == "Bearer tok"
    assert json.loads(put.content) == {
        "inputHash": "h1",
        "checkedAt": "2026-11-05T00:00:00Z",
        "commentCount": 125_000,
    }


@pytest.mark.parametrize("status", [404, 405, 409])
def test_checked_is_false_on_an_older_core_or_a_newer_row(status: int) -> None:
    assert FakeCore(checked_status=status).client().mark_checked(POST_ID, "h", NOW, 1) is False


def test_checked_raises_on_a_server_error() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        FakeCore(checked_status=500).client().mark_checked(POST_ID, "h", NOW, 1)
