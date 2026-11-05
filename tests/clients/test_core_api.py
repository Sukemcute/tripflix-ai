import json

import httpx
from pydantic import SecretStr

from app.clients.core_api import CoreApiClient
from app.services.summary.schemas import SaveSummaryRequest

POST_ID = "018d9f20-0000-7000-8000-000000000001"


def _comment(i: int) -> dict[str, object]:
    return {
        "id": f"c-{i}",
        "postId": POST_ID,
        "authorId": f"u-{i}",
        "parentCommentId": None,
        "body": f"bình luận {i}",
        "isEdited": False,
        "createdAt": "2026-11-05T08:00:00.000Z",
        "updatedAt": "2026-11-05T08:00:00.000Z",
    }


class FakeCore:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.now = 0.0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/auth/service-token":
            return httpx.Response(
                200, json={"accessToken": "tok", "tokenType": "Bearer", "expiresIn": 300}
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

    client.save_summary(POST_ID, SaveSummaryRequest(status="no_comments"))
    core.now = 200  # still more than 30 s before the 300 s expiry
    client.save_summary(POST_ID, SaveSummaryRequest(status="no_comments"))
    core.now = 280  # inside the 30 s margin: ask again
    client.save_summary(POST_ID, SaveSummaryRequest(status="no_comments"))

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
