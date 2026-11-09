import asyncio
import time
from collections.abc import Iterator, Sequence
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.api.auth import ServiceTokenVerifier, get_service_verifier
from app.api.moderation import get_moderation_client
from app.clients.moderation.base import ModerationResult, ModerationUpstreamError
from app.clients.moderation.fake import FAKE_MODEL, FakeModerationClient
from app.core.config import ModerationSettings, get_moderation_settings
from app.main import app

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
def fake() -> Iterator[FakeModerationClient]:
    client = FakeModerationClient()
    app.dependency_overrides[get_service_verifier] = lambda: ServiceTokenVerifier(
        lambda _t: KEY.public_key(), issuer=ISSUER, audience=AUDIENCE, callers=("core-api",)
    )
    app.dependency_overrides[get_moderation_client] = lambda: client
    app.dependency_overrides[get_moderation_settings] = lambda: ModerationSettings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        moderation_timeout_seconds=0.2,
    )
    yield client
    app.dependency_overrides.clear()


http = TestClient(app)
BODY = {"items": [{"id": "post:1", "text": "Phòng đẹp"}, {"id": "cmt:2", "text": "đồ FLAG"}]}


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
