"""Evals for Tripi, the chat assistant (RULES §10: run before and after a prompt or agent change).

    uv run python -m evals.assistant.run                 # ci: fixed plans, fake Core, free
    uv run python -m evals.assistant.run --mode live     # Controller from .env, 3 runs a case

ci   checks the code after the Controller (planner, Skills, cards, clarify-once) against the
     40 labelled cases in cases.v1.jsonl, with a fake Core and fake weather.
live asks the real Controller three times per case and scores the intent (a case may accept
     other intents in "alsoOk" when the code still ends the same way): accuracy over all
     runs and pass^3 (all three right; tau-bench, Yao et al. 2024), plus tokens and cost.
     It costs money: run it only when a prompt or model changes.
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from uuid import UUID

import httpx

from app.clients.weather import DayWeather, Place
from app.services.assistant.schemas import ChatRequest, Understanding
from app.services.assistant.turn import Turn

CASES = Path(__file__).with_name("cases.v1.jsonl")
REEL = UUID("018d9f20-0000-7000-8000-00000000000a")
TODAY = date(2026, 11, 16)  # a Monday: fixed so relative days give the same answer


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line]


def request_of(case: dict) -> ChatRequest:
    return ChatRequest.model_validate(
        {
            "conversationId": "00000000-0000-4000-8000-000000000000",
            "message": case["message"],
            "history": case["history"],
            "contextPostId": str(REEL) if case["inReel"] else None,
        }
    )


# ---- ci: a fake Core shaped like the real responses (contracts/openapi of core-api)

VIDEO = {"id": "post:1", "refId": "1", "kind": "video", "title": "Săn mây 4h sáng"}
POST = {
    "post": {
        "id": str(REEL),
        "authorId": "a1",
        "title": "Nha Trang 3N2Đ",
        "tripAttachment": {
            "hotelId": "h1",
            "hotelName": "Vinpearl Beach Nha Trang",
            "destinationName": "Nha Trang",
            "daysCount": 3,
            "items": [{"day": 1, "title": "Cáp treo", "location": "Hòn Tre"}],
        },
    }
}
CORE = {
    "/api/search/posts": {"items": [VIDEO]},
    "/api/search": {"sections": [{"items": [VIDEO]}]},
    "/api/suggest": {"items": [{"type": "place", "refId": "place-1"}]},
    "/api/stays": {
        "items": [{"hotelId": "h1", "name": "Khách sạn", "unitPrice": 1, "totalPrice": 2}]
    },
    "/api/flights": {
        "flights": [
            {
                "productId": "f1",
                "name": "VN 123",
                "isAvailable": True,
                "priceFrom": 1,
                "fares": [{"code": "ECO", "pricePerPerson": 1, "totalPrice": 2}],
            }
        ]
    },
    "/api/hotels/": {
        "id": "h1",
        "name": "Vinpearl Beach Nha Trang",
        "rooms": [{"isAvailable": True, "ratePlans": [{"totalPrice": 2, "pricePerNight": 1}]}],
    },
    f"/api/v1/posts/{REEL}/ai-summary": None,  # no summary yet: core answers 404
    f"/api/v1/posts/{REEL}": POST,
}


def fake_core() -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        for prefix, body in CORE.items():
            if request.url.path.startswith(prefix):
                return httpx.Response(404) if body is None else httpx.Response(200, json=body)
        return httpx.Response(404)

    return httpx.AsyncClient(base_url="https://core.test", transport=httpx.MockTransport(handle))


class FakeWeather:
    async def find_place(self, name: str) -> Place | None:
        return Place(name, 10.0, 107.0)

    async def forecast(self, place: Place, start: date, end: date) -> list[DayWeather]:
        return [DayWeather(start, 26, 31, 60, "mưa rào")]


async def run_ci(cases: list[dict]) -> int:
    failures = []
    async with fake_core() as core:
        for case in cases:
            expect = case["expect"]
            turn = Turn(
                request_of(case),
                Understanding.model_validate(expect["plan"]),
                core=core,
                weather=FakeWeather(),
                today=TODAY,
            )
            answer = await turn.answer()
            card = answer.cards[0].kind if answer.cards else None
            if answer.kind != expect["kind"] or card != expect["card"] or turn.degraded:
                failures.append((case["id"], expect["kind"], expect["card"], answer.kind, card))
    print(f"ci: {len(cases) - len(failures)}/{len(cases)} cases match kind and first card")
    for case_id, kind, card, got_kind, got_card in failures:
        print(f"  FAIL {case_id}: want {kind}/{card}, got {got_kind}/{got_card}")
    return 1 if failures else 0


async def run_live(cases: list[dict], runs: int) -> int:
    from app.services.assistant.understand import understand  # noqa: PLC0415  # needs .env

    by_case: dict[str, list[bool]] = {}
    answers: dict[str, list[str]] = {}
    latencies, tokens, cost = [], 0, 0.0
    by_tag: Counter[str] = Counter()
    wrong_by_tag: Counter[str] = Counter()
    for case in cases:
        for _ in range(runs):
            started = time.perf_counter()
            try:
                parsed, result = await understand(request_of(case), max_turns=6)
                tokens += result.input_tokens + result.output_tokens
                cost += result.cost_usd
                expect = case["expect"]
                is_right = parsed.intent in [expect["intent"], *expect.get("alsoOk", [])]
                got = parsed.intent
            except Exception as error:  # noqa: BLE001  # an eval run reports, never stops
                got = f"{type(error).__name__}: {str(error).splitlines()[:3]}"
                is_right = False
            answers.setdefault(case["id"], []).append(got)
            latencies.append(time.perf_counter() - started)
            by_case.setdefault(case["id"], []).append(is_right)
            for tag in case["tags"]:
                by_tag[tag] += 1
                wrong_by_tag[tag] += not is_right
    total = sum(len(v) for v in by_case.values())
    right = sum(sum(v) for v in by_case.values())
    stable = sum(all(v) for v in by_case.values())
    latencies.sort()
    print(f"live intent accuracy: {right}/{total} = {right / total:.1%}")
    print(f"pass^{runs}: {stable}/{len(by_case)} = {stable / len(by_case):.1%}")
    print(
        f"latency p50 {latencies[len(latencies) // 2]:.2f} s, "
        f"p95 {latencies[int(len(latencies) * 0.95) - 1]:.2f} s"
    )
    print(f"tokens {tokens}, cost {cost:.5f} USD ({cost / total:.6f} per call)")
    for tag in sorted(by_tag):
        print(f"  {tag}: {by_tag[tag] - wrong_by_tag[tag]}/{by_tag[tag]}")
    for case_id, results in by_case.items():
        if not all(results):
            want = next(c["expect"]["intent"] for c in cases if c["id"] == case_id)
            print(f"  UNSTABLE {case_id}: want {want}, got {answers[case_id]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["ci", "live"], default="ci")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    cases = load_cases()
    if args.mode == "ci":
        return asyncio.run(run_ci(cases))
    return asyncio.run(run_live(cases, args.runs))


if __name__ == "__main__":
    sys.exit(main())
