import asyncio
import base64
import logging
import time
from collections.abc import Iterator, Sequence
from typing import Any
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.api import moderation as moderation_api
from app.api.auth import ServiceTokenVerifier, get_service_verifier
from app.api.moderation import get_moderation_client, get_visobert_client
from app.clients.moderation.base import ModerationResult, ModerationUpstreamError
from app.clients.moderation.fake import FAKE_MODEL, FakeModerationClient
from app.clients.moderation.visobert import VisobertModeration
from app.core.config import ModerationSettings, get_moderation_settings
from app.main import app
from app.services.usage_events import UsageEvent

KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())
ISSUER, AUDIENCE = "tripflix-core", "ai-service"


def token(key: Any = KEY, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": "core-api",
        "typ": "service",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
    } | overrides
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "k1"})


def auth(t: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {t or token()}"}


class SlowClient:
    async def moderate(self, text: str, image_urls: Sequence[str]) -> ModerationResult:
        await asyncio.sleep(1)
        raise AssertionError("should have timed out")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeModerationClient]:
    client = FakeModerationClient()
    monkeypatch.setattr(moderation_api, "publish_usage", AsyncMock())
    app.dependency_overrides[get_service_verifier] = lambda: ServiceTokenVerifier(
        lambda _t: KEY.public_key(), issuer=ISSUER, audience=AUDIENCE, callers=("core-api",)
    )
    app.dependency_overrides[get_moderation_client] = lambda: client
    app.dependency_overrides[get_visobert_client] = lambda: None
    app.dependency_overrides[get_moderation_settings] = lambda: ModerationSettings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        moderation_timeout_seconds=0.2,
    )
    yield client
    app.dependency_overrides.clear()


http = TestClient(app)
BODY = {"items": [{"id": "post:1", "text": "Phòng đẹp"}, {"id": "cmt:2", "text": "đồ FLAG"}]}


def test_cover_ocr_scans_only_extracted_poster_text(
    fake: FakeModerationClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.clients.moderation.cover_ocr import CoverOcrTokens

    events: list[UsageEvent] = []

    async def publish(batch: list[UsageEvent]) -> None:
        events.extend(batch)

    monkeypatch.setattr(moderation_api, "publish_usage", publish)

    class Ocr:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.called = False
            self.usage = None

        async def read(self, jpeg: bytes) -> str:
            assert jpeg == b"\xff\xd8\xff\xd9"
            self.called = True
            self.usage = CoverOcrTokens(1000, 200, 20, "gpt-4.1-mini")
            return "FLAG trên ảnh bìa"

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(moderation_api, "OpenAICoverOcr", Ocr)
    response = http.post(
        "/moderate/cover-ocr",
        json={"imageBase64": base64.b64encode(b"\xff\xd8\xff\xd9").decode()},
        headers=auth(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "flagged"
    assert response.json()["extractedText"] == "FLAG trên ảnh bìa"
    assert response.json()["categories"]
    assert len(events) == 1
    assert events[0].payload.model_dump(by_alias=True) == {
        "feature": "cover_ocr",
        "model": "gpt-4.1-mini",
        "step": "completed",
        "inputTokens": 1000,
        "outputTokens": 20,
        "costUsd": pytest.approx(0.000372),
        "estimated": True,
    }


def test_cover_ocr_requires_core_and_jpeg(fake: FakeModerationClient) -> None:
    body = {"imageBase64": base64.b64encode(b"plain text").decode()}
    assert http.post("/moderate/cover-ocr", json=body).status_code == 401
    assert http.post("/moderate/cover-ocr", json=body, headers=auth()).status_code == 422


def test_cover_ocr_records_unpriced_provider_attempt(
    fake: FakeModerationClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.clients.moderation.cover_ocr import CoverOcrError

    events: list[UsageEvent] = []

    async def publish(batch: list[UsageEvent]) -> None:
        events.extend(batch)

    monkeypatch.setattr(moderation_api, "publish_usage", publish)

    class Ocr:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.called = False
            self.usage = None

        async def read(self, jpeg: bytes) -> str:
            self.called = True
            raise CoverOcrError("provider failed")

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(moderation_api, "OpenAICoverOcr", Ocr)
    response = http.post(
        "/moderate/cover-ocr",
        json={"imageBase64": base64.b64encode(b"\xff\xd8\xff\xd9").decode()},
        headers=auth(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert len(events) == 1
    assert events[0].payload.model_dump(by_alias=True) == {
        "feature": "cover_ocr",
        "model": "gpt-4.1-mini",
        "step": "usage_missing",
        "inputTokens": None,
        "outputTokens": None,
        "costUsd": 0,
        "estimated": True,
    }


def test_core_gets_one_result_per_item_in_order_in_camel_case(fake: FakeModerationClient) -> None:
    response = http.post("/moderate", json=BODY, headers=auth())

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "id": "post:1",
                "flagged": False,
                "categories": {"harassment": False},
                "scores": {"harassment": 0.01},
            },
            {
                "id": "cmt:2",
                "flagged": True,
                "categories": {"harassment": True},
                "scores": {"harassment": 0.9},
            },
        ],
        "model": FAKE_MODEL,
    }


def test_images_are_passed_and_pii_is_masked_before_the_provider(
    fake: FakeModerationClient,
) -> None:
    item = {
        "id": "post:1",
        "text": "Gọi 0912345678, hỏi anh Cường",
        "imageUrls": ["https://cdn.example/a.jpg"],
    }

    assert http.post("/moderate", json={"items": [item]}, headers=auth()).status_code == 200
    [(sent_text, sent_images)] = fake.calls
    assert "0912345678" not in sent_text and "Cường" not in sent_text
    assert sent_images == ("https://cdn.example/a.jpg",)


def test_successful_moderation_publishes_counts_without_item_data(
    fake: FakeModerationClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[UsageEvent] = []

    async def publish(batch: list[UsageEvent]) -> None:
        events.extend(batch)

    monkeypatch.setattr(moderation_api, "publish_usage", publish)
    body = {"items": [*BODY["items"], {"id": "p", "imageUrls": ["https://cdn.example/a.jpg"]}]}
    assert http.post("/moderate", json=body, headers=auth()).status_code == 200
    [event] = events
    assert event.user_id is None
    assert event.model_dump(mode="json", by_alias=True)["payload"] == {
        "feature": "moderation",
        "model": FAKE_MODEL,
        "inputTokens": None,
        "outputTokens": None,
        "costUsd": 0,
        "estimated": False,
        "items": 3,
        "images": 1,
    }


@pytest.mark.parametrize(
    "bad",
    [
        None,  # no token
        token(key=OTHER_KEY),  # signed by someone else
        token(aud="core-api"),
        token(iss="someone"),
        token(exp=int(time.time()) - 10),
        token(typ="access"),  # a user token never passes
        token(typ=None),
    ],
)
def test_bad_tokens_are_401(fake: FakeModerationClient, bad: str | None) -> None:
    headers = auth(bad) if bad else {}

    response = http.post("/moderate", json=BODY, headers=headers)

    assert response.status_code == 401
    assert fake.calls == []


def test_another_service_is_403(fake: FakeModerationClient) -> None:
    response = http.post("/moderate", json=BODY, headers=auth(token(sub="ai-service")))

    assert response.status_code == 403


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"id": f"x{i}", "text": "a"} for i in range(21)],
        [{"id": "x", "text": "a", "imageUrls": [f"https://c/{i}.jpg" for i in range(5)]}],
        [{"id": "x", "imageUrls": ["http://c/a.jpg"]}],  # not https
        [{"id": "x", "text": "   "}],  # nothing to check
        [{"id": "x", "text": "a" * 10_001}],
        [{"id": "", "text": "a"}],
    ],
)
def test_requests_out_of_bounds_are_422(fake: FakeModerationClient, items: list[Any]) -> None:
    assert http.post("/moderate", json={"items": items}, headers=auth()).status_code == 422


def test_provider_error_is_502_and_slow_provider_is_504(fake: FakeModerationClient) -> None:
    fake.error = ModerationUpstreamError("boom")
    assert http.post("/moderate", json=BODY, headers=auth()).status_code == 502

    app.dependency_overrides[get_moderation_client] = SlowClient
    assert http.post("/moderate", json=BODY, headers=auth()).status_code == 504


def test_missing_key_is_503_but_only_after_auth(fake: FakeModerationClient) -> None:
    app.dependency_overrides[get_moderation_client] = lambda: None

    assert http.post("/moderate", json=BODY).status_code == 401
    assert http.post("/moderate", json=BODY, headers=auth()).status_code == 503


def test_jwks_url_follows_core_api_url() -> None:
    settings = ModerationSettings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        core_api_url="http://core-api:3000/",
    )

    assert settings.resolved_jwks_url == "http://core-api:3000/.well-known/jwks.json"


def test_safety_shadow_logs_without_changing_response(
    fake: FakeModerationClient, caplog: pytest.LogCaptureFixture
) -> None:
    app.dependency_overrides[get_moderation_settings] = lambda: ModerationSettings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        is_moderation_safety_shadow_enabled=True,
    )
    body = {"items": [{"id": "cmt:2", "text": "Tôi bị ngộ độc thức ăn 0912345678"}]}
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        response = http.post("/moderate", json=body, headers=auth())
    assert response.status_code == 200
    assert response.json()["results"][0]["flagged"] is False
    assert "moderation.shadow" in caplog.text
    assert '"version": 6' in caplog.text
    assert "0912345678" not in caplog.text


def test_visobert_adds_review_signal_without_overwriting_openai_categories(
    fake: FakeModerationClient,
) -> None:
    from tests.clients.test_visobert_moderation import local

    model = local()
    app.dependency_overrides[get_visobert_client] = lambda: model
    try:
        response = http.post(
            "/moderate", json={"items": [{"id": "c:1", "text": "test"}]}, headers=auth()
        )
        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["flagged"] is True
        assert result["categories"]["harassment"] is False
        assert result["categories"]["visobert/toxic"] is True
        assert result["scores"]["harassment"] == 0.01
        assert "+visobert-" in response.json()["model"]
    finally:
        model.close()


def test_unavailable_visobert_keeps_openai_result(fake: FakeModerationClient) -> None:
    class Unavailable(VisobertModeration):
        async def moderate_batch(self, texts: list[str]):
            return None

    app.dependency_overrides[get_visobert_client] = lambda: Unavailable(
        None,
        None,
        threshold=0.97,
        pad_id=1,
        batch_size=4,
        timeout_seconds=0.1,
    )
    response = http.post("/moderate", json=BODY, headers=auth())
    assert response.status_code == 200
    assert response.json()["results"][0]["flagged"] is False
    assert response.json()["results"][1]["flagged"] is True
    assert response.json()["model"] == FAKE_MODEL


def test_parts_are_independent_and_keep_partial_results(fake: FakeModerationClient) -> None:
    class PartialClient:
        async def moderate(self, text: str, image_urls: Sequence[str]) -> ModerationResult:
            if image_urls and "broken" in image_urls[0]:
                raise ModerationUpstreamError("private URL must not leak")
            if image_urls:
                assert not text
                assert len(image_urls) == 1
                return ModerationResult(True, {"violence": True}, {"violence": 0.95}, FAKE_MODEL)
            return await fake.moderate(text, image_urls)

    app.dependency_overrides[get_moderation_client] = PartialClient
    body = {
        "items": [
            {"id": "caption", "kind": "caption", "text": "Phòng đẹp"},
            {"id": "image:1", "kind": "image", "imageUrl": "https://cdn.example/a.jpg"},
            {"id": "image:2", "kind": "image", "imageUrl": "https://cdn.example/broken.jpg"},
        ]
    }
    assert http.post("/moderate/parts", json=body).status_code == 401
    response = http.post("/moderate/parts", json=body, headers=auth())
    assert response.status_code == 200
    results = response.json()["results"]
    assert [r["status"] for r in results] == ["passed", "flagged", "error"]
    assert results[2]["errorCode"] == "provider_error"
    assert "private" not in response.text
    assert fake.calls == [("Phòng đẹp", ())]


@pytest.mark.parametrize(
    "items",
    [
        [{"id": "x", "kind": "caption", "text": ""}],
        [{"id": "x", "kind": "image", "imageUrl": "http://cdn.example/a.jpg"}],
        [{"id": "x", "kind": "image", "text": "mixed", "imageUrl": "https://cdn.example/a.jpg"}],
        [{"id": "x", "kind": "caption", "text": "a"}] * 2,
    ],
)
def test_parts_validate_input(fake: FakeModerationClient, items: list[Any]) -> None:
    assert http.post("/moderate/parts", json={"items": items}, headers=auth()).status_code == 422


def test_part_timeout_is_retryable_error(fake: FakeModerationClient) -> None:
    app.dependency_overrides[get_moderation_client] = SlowClient
    response = http.post(
        "/moderate/parts",
        json={
            "items": [
                {"id": "x", "kind": "image", "imageUrl": "https://cdn.example/a.jpg"},
            ]
        },
        headers=auth(),
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["errorCode"] == "provider_timeout"
