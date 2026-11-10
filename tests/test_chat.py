import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.api.chat import ChatSettings, get_chat_settings, require_chat_user, verify_user_token
from app.main import app
from app.services.assistant import ChatRequest, search


def test_chat_requires_login():
    with TestClient(app) as client:
        response = client.post("/chat", json={"conversationId": str(uuid4()), "message": "Đà Lạt"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "change",
    [
        {"aud": "ai-service"},
        {"iss": "other"},
        {"typ": "service"},
        {"role": "guest"},
        {"sid": ""},
        {"exp": 1},
    ],
)
def test_rejects_invalid_user_claims(monkeypatch, change):
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    claims = {
        "sub": str(uuid4()),
        "sid": str(uuid4()),
        "role": "member",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "aud": "tripflix",
        "iss": "tripflix-core",
    } | change

    class Keys:
        def get_signing_key_from_jwt(self, token):
            class SigningKey:
                def __init__(self):
                    self.key = key.public_key()

            result = SigningKey()
            return result

    monkeypatch.setattr(chat_api, "get_jwks", lambda url: Keys())
    token = jwt.encode(claims, key, algorithm="ES256")
    with pytest.raises(jwt.InvalidTokenError):
        verify_user_token(token, ChatSettings.model_construct())


def test_search_maps_core_cards_and_never_uses_relaxed_suggestions():
    async def run():
        payload = {
            "sections": [
                {
                    "items": [
                        {
                            "id": "plan:1",
                            "refId": "1",
                            "kind": "plan",
                            "title": "Đà Lạt",
                            "priceFrom": 500000,
                        },
                    ]
                }
            ],
            "suggest": [{"title": "unrelated"}],
        }
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(base_url="https://core.test", transport=transport) as core:
            answer = await search(core, "Đà Lạt")
        assert answer.kind == "answer"
        assert len(answer.cards) == 1
        assert answer.cards[0].id == "1"
        assert answer.cards[0].price_basis == "estimated_per_person"
        assert answer.cards[0].price_from == 500000

    asyncio.run(run())


def test_search_puts_at_most_three_videos_first():
    async def run():
        videos = [
            {"id": f"post:{i}", "refId": str(i), "kind": "video", "title": f"Video {i}"}
            for i in range(4)
        ]
        stay = {"id": "hotel:9", "refId": "9", "kind": "stay", "title": "Khách sạn"}
        payload = {"sections": [{"items": [stay]}, {"items": videos}]}
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(base_url="https://core.test", transport=transport) as core:
            answer = await search(core, "săn mây Đà Lạt")
        assert [card.id for card in answer.cards] == ["0", "1", "2", "9"]

        payload = {"sections": [{"items": videos[:2]}]}
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(base_url="https://core.test", transport=transport) as core:
            answer = await search(core, "săn mây Đà Lạt")
        assert answer.text.startswith("Tripi tìm được 2 video")

    asyncio.run(run())


def test_search_failure_is_not_empty_results():
    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(503))
        async with httpx.AsyncClient(base_url="https://core.test", transport=transport) as core:
            with pytest.raises(httpx.HTTPStatusError):
                await search(core, "Đà Lạt")

    asyncio.run(run())


def test_reel_search_returns_only_video_cards():
    async def run():
        def respond(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/search/posts"
            assert json.loads(request.content)["postType"] == "video"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "post:1", "refId": "1", "kind": "video", "title": "Săn mây"},
                        {"id": "hotel:2", "refId": "2", "kind": "stay", "title": "Khách sạn"},
                    ]
                },
            )

        async with httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(respond)
        ) as core:
            answer = await search(core, "Săn mây Đà Lạt", reels_only=True)
        assert [card.kind for card in answer.cards] == ["video"]

    asyncio.run(run())


def test_long_fallback_asks_without_truncating():
    async def run():
        def unexpected(request):
            pytest.fail("must not call Core with truncated constraints")

        async with httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(unexpected)
        ) as core:
            answer = await search(core, "a" * 201)
        assert answer.kind == "clarify"

    asyncio.run(run())


def test_sse_refusal_uses_fixed_text(monkeypatch):
    from app.services.assistant import Understanding

    async def refuse(request, settings, usage):
        return Understanding(intent="refusal")

    monkeypatch.setattr(chat_api, "understand", refuse)
    app.dependency_overrides[require_chat_user] = lambda: "user"
    from pydantic import SecretStr

    app.dependency_overrides[get_chat_settings] = lambda: ChatSettings.model_construct(
        chat_llm_enabled=True, deepseek_api_key=SecretStr("test")
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/chat",
                json={
                    "conversationId": str(uuid4()),
                    "message": "outside travel",
                },
            )
        assert response.status_code == 200
        events = response.text.strip().split("\n\n")
        assert [part.splitlines()[0] for part in events] == [
            "event: status",
            "event: status",
            "event: status",
            "event: text",
            "event: cards",
            "event: done",
        ]
        assert json.loads(events[-1].split("data: ")[1])["kind"] == "refusal"
    finally:
        app.dependency_overrides.clear()


def test_blank_message_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ChatRequest(conversation_id=uuid4(), message="   ")


def test_flight_search_uses_core_price_and_excludes_sold_out():
    from app.services.assistant import Understanding, search_flights

    async def run():
        travel_date = (datetime.now(UTC) + timedelta(days=7)).date()

        def respond(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/flights"
            assert dict(request.url.params) == {
                "from": "SGN",
                "to": "HAN",
                "date": travel_date.isoformat(),
                "passengers": "2",
            }
            return httpx.Response(
                200,
                json={
                    "flights": [
                        {
                            "productId": "sold",
                            "name": "Hết chỗ",
                            "isAvailable": False,
                            "priceFrom": 10,
                        },
                        {
                            "productId": "open",
                            "name": "Còn chỗ",
                            "isAvailable": True,
                            "priceFrom": 1200000,
                        },
                    ]
                },
            )

        async with httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(respond)
        ) as core:
            result = await search_flights(
                core,
                Understanding(
                    intent="find_flight",
                    from_airport="SGN",
                    to_airport="HAN",
                    flight_date=travel_date,
                ),
            )
        assert result.kind == "answer"
        assert [(card.id, card.price_from) for card in result.cards] == [("open", 1200000)]
        assert result.cards[0].price_basis == "per_ticket"

    asyncio.run(run())


def test_stay_search_keeps_dates_and_server_prices():
    from app.services.assistant import Understanding, search_stays

    async def run():
        start = (datetime.now(UTC) + timedelta(days=10)).date()
        end = start + timedelta(days=2)

        def respond(request):
            if request.url.path == "/api/suggest":
                return httpx.Response(200, json={"items": [{"type": "place", "refId": "da-lat"}]})
            assert request.url.params["checkIn"] == start.isoformat()
            assert request.url.params["checkOut"] == end.isoformat()
            assert request.url.params["adults"] == "3"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "hotelId": "hotel-1",
                            "name": "Khách sạn",
                            "unitPrice": 1200000,
                            "totalPrice": 4800000,
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(respond)
        ) as core:
            answer = await search_stays(
                core,
                Understanding(
                    intent="find_stay",
                    place="Đà Lạt",
                    check_in=start,
                    check_out=end,
                    adults=3,
                ),
            )
        assert answer.kind == "answer"
        assert answer.cards[0].total_price == 4800000
        assert answer.cards[0].check_in == start
        assert answer.cards[0].price_basis == "per_night_per_room"

    asyncio.run(run())


def test_missing_dates_never_invents_availability():
    from app.services.assistant import Understanding, search_stays

    async def run():
        def unexpected(request):
            pytest.fail("dates must be supplied before searching availability")

        async with httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(unexpected)
        ) as core:
            answer = await search_stays(core, Understanding(intent="find_stay", place="Đà Lạt"))
        assert answer.kind == "clarify"
        assert answer.cards == []

    asyncio.run(run())
