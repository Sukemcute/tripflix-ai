"""Evals for Tripi, the chat assistant (RULES §10: run before and after a prompt or agent change).

    uv run python -m evals.assistant.run                 # ci: fixed plans, fake Core, free
    uv run python -m evals.assistant.run --mode live     # Controller from .env, 3 runs a case
    uv run python -m evals.assistant.run --mode chain    # multi-turn chains, real Controller

ci    checks the code after the Controller (planner, Skills, cards, clarify-once) against the
      labelled cases with a fake Core and fake weather: cases.v1.jsonl (40),
      cases.v2.jsonl (30 defects of the Expo Web report) and cases.v3.jsonl (30 more so the
      set reaches the 100 scenarios of the PRD). v2 and v3 cases give the Controller's own
      output (day and month, no year) and the requests Core must, or must never, get.
search the 50 search messages of the PRD (search.v1.jsonl) through the real Controller and
      the real Core at CORE_API_URL: right on the first try when one of the first 3 results
      names the place the user meant (title, subtitle or location). PRD target: 80%.
live  asks the real Controller three times per case and scores the intent (a case may accept
      other intents in "alsoOk" when the code still ends the same way) and, in v2, the slots:
      accuracy over all runs and pass^3 (all three right; tau-bench, Yao et al. 2024), plus
      tokens and cost. It costs money: run it only when a prompt or model changes.
chain plays the turns of chains.v1.jsonl in order, each with the history and trip memory the
      previous turn returned, as the app does (Expo Web report §6.1, §7.6). It costs money.
ab    the TF14 comparison: the same fixed plans written by A (one agent: fixed text, what
      CHAT_RESPONDER_ENABLED=false serves) and by B (the real Responder through the Verifier).
      Reports how often B is used, sentences the Verifier drops by rule, latency and cost.
      Judging tone is left to people reading the printed answers. It costs money.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from uuid import UUID

import httpx

from app.clients.weather import DayWeather, Place
from app.services.assistant.controller import ControllerOutput, to_understanding
from app.services.assistant.planner import today_in_vietnam
from app.services.assistant.schemas import ChatRequest, TripContext, Understanding
from app.services.assistant.schemas import Turn as HistoryTurn
from app.services.assistant.turn import Turn
from app.services.summary.vi_text import normalize_text

HERE = Path(__file__).parent
REEL = UUID("018d9f20-0000-7000-8000-00000000000a")
TODAY = date(2026, 11, 16)  # a Monday: fixed so relative days give the same answer
EMPTY_PLAN = {
    "intent": "search",
    "query": "",
    "missing": "none",
    "place": "",
    "start": None,
    "end": None,
    "day_ref": "none",
    "nights": None,
    "adults": None,
    "children": None,
    "infants": None,
    "from_airport": None,
    "to_airport": None,
    "from_city": "",
    "to_city": "",
    "cheapest_only": False,
    "round_trip": False,
    "price_max_per_night": None,
    "depart_after": None,
    "depart_before": None,
    "hotel_name": "",
    "card_ordinal": None,
    "reel_query": "",
    "uses_context_post": False,
    "itinerary_day": None,
    "asks_days_count": False,
    "packing_have": [],
    "packing_only": [],
    "packing_limit": None,
    "is_beach_trip": None,
    "interests": [],
    "stop_name": "",
    "pace": None,
    "meals_only": False,
    "is_rude": False,
}


def read_jsonl(name: str) -> list[dict]:
    lines = (HERE / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


def load_cases(version: str = "v1") -> list[dict]:
    return read_jsonl(f"cases.{version}.jsonl")


def controller_plan(**fields) -> ControllerOutput:
    """A Controller output with every field null or empty except the ones given."""
    return ControllerOutput.model_validate(EMPTY_PLAN | fields)


def request_of(case: dict) -> ChatRequest:
    return ChatRequest.model_validate(
        {
            "conversationId": "00000000-0000-4000-8000-000000000000",
            "message": case["message"],
            "history": case["history"],
            "contextPostId": str(REEL) if case["inReel"] else None,
            "trip": case.get("trip"),
            "action": case.get("action"),
        }
    )


def plan_of(case: dict, request: ChatRequest) -> Understanding:
    expect = case["expect"]
    if "controller" in expect:
        return to_understanding(
            controller_plan(**expect["controller"]), request.trip, TODAY, message=request.message
        )
    return Understanding.model_validate(expect["plan"])


def slots_match(parsed: Understanding, slots: dict) -> bool:
    """Strings compare without accents; a list must hold every expected item."""
    got = parsed.model_dump(mode="json")
    for name, want in slots.items():
        value = got.get(name)
        if isinstance(want, str) and isinstance(value, str):
            if normalize_text(want) != normalize_text(value):
                return False
        elif isinstance(want, list) and isinstance(value, list):
            folded = [normalize_text(v) for v in value]
            if not all(any(normalize_text(w) in v for v in folded) for w in want):
                return False
        elif value != want:
            return False
    return True


# ---- ci: a fake Core shaped like the real responses (contracts/openapi of core-api)

VIDEO = {"id": f"post:{REEL}", "refId": str(REEL), "kind": "video", "title": "Săn mây 4h sáng"}
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
            "items": [
                {"day": 1, "title": "Cáp treo", "location": "Hòn Tre"},
                {"day": 2, "title": "Lặn ngắm san hô", "location": "Hòn Mun"},
                {"day": 3, "title": "Chợ đêm", "location": "Trần Phú"},
            ],
        },
    }
}
CORE = {
    "/api/search/posts": {"items": [VIDEO]},
    "/api/search": {"sections": [{"items": [VIDEO]}]},
    "/api/stays": {
        "items": [{"hotelId": "h1", "name": "Khách sạn", "unitPrice": 1, "totalPrice": 2}]
    },
    "/api/flights": {
        "flights": [
            {
                "productId": f"f{hour}",
                "name": f"VN {hour}",
                "flightKey": f"VN{hour}",
                "departTime": f"{hour:02d}:30",
                "isAvailable": True,
                "priceFrom": 1,
                "fares": [{"code": "ECO", "pricePerPerson": 1, "totalPrice": 2}],
            }
            for hour in (6, 8, 11, 17)
        ]
    },
    "/api/hotels/": {
        "id": "h1",
        "name": "Vinpearl Beach Nha Trang",
        "location": {"lat": 10.01, "lng": 107.01},
        "rooms": [{"isAvailable": True, "ratePlans": [{"totalPrice": 2, "pricePerNight": 1}]}],
    },
    # Simulated points around the fake town centre (10, 107): Stage B plans need coordinates.
    "/api/places": {
        "items": [
            {
                "id": f"osm:{i}",
                "name": name,
                "kind": kind,
                "lat": 10 + dy,
                "lng": 107 + dx,
                "city": "Demo",
                "tags": tags,
                "popularity": pop,
            }
            for i, (name, kind, dy, dx, tags, pop) in enumerate(
                [
                    ("Hải Đăng", "see", -0.013, -0.007, ["viewpoint"], 0.9),
                    ("Mũi Nghinh Phong", "see", -0.022, 0.0, ["sunset"], 0.8),
                    ("Tượng Chúa Kitô", "see", -0.019, 0.002, ["viewpoint"], 0.85),
                    ("Bãi Sau", "see", 0.003, 0.009, ["beach"], 0.9),
                    ("Bạch Dinh", "see", 0.007, -0.016, ["museum"], 0.6),
                    ("Hồ Mây", "see", 0.0, -0.013, ["park"], 0.7),
                    ("Quán hải sản", "food", -0.001, -0.012, [], 0.7),
                    ("Cafe biển", "cafe", -0.013, -0.001, [], 0.6),
                    ("Nhà nghỉ Biển Xanh", "lodging", 0.003, 0.011, [], 0.5),
                ]
            )
        ],
        "attribution": "© OpenStreetMap contributors (ODbL)",
    },
    f"/api/v1/posts/{REEL}/ai-summary": None,  # no summary yet: core answers 404
    f"/api/v1/posts/{REEL}": POST,
}
SUGGEST = {
    "place": {"items": [{"type": "place", "refId": "place-1"}]},
    "hotel": {"items": [{"type": "hotel", "refId": "h2", "name": "Vinpearl Luxury Nha Trang"}]},
}
# Like Core's suggest index: one airport per city that has one; Vũng Tàu has none.
AIRPORT_BY_CITY = {"TP.HCM": "SGN", "Hà Nội": "HAN", "Đà Nẵng": "DAD", "Đà Lạt": "DLI"}


def fake_core(
    calls: list[tuple[str, dict]] | None = None, *, overrides: dict | None = None
) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if calls is not None:
            calls.append((request.url.path, params))
        if request.url.path == "/api/suggest" and params.get("types") == "airport":
            code = AIRPORT_BY_CITY.get(params.get("q", ""))
            items = [{"type": "airport", "refId": code, "name": f"Sân bay {code}"}] if code else []
            return httpx.Response(200, json={"items": items})
        if request.url.path == "/api/suggest":
            return httpx.Response(200, json=SUGGEST.get(params.get("types", ""), {"items": []}))
        for prefix, body in (CORE | (overrides or {})).items():
            if request.url.path.startswith(prefix):
                return httpx.Response(404) if body is None else httpx.Response(200, json=body)
        return httpx.Response(404)

    return httpx.AsyncClient(base_url="https://core.test", transport=httpx.MockTransport(handle))


class FakeWeather:
    async def find_place(self, name: str) -> Place | None:
        return Place(name, 10.0, 107.0)

    async def forecast(self, place: Place, start: date, end: date) -> list[DayWeather]:
        return [DayWeather(start, 26, 31, 60, "mưa rào")]


def core_problem(expect: dict, calls: list[tuple[str, dict]]) -> str | None:
    """The first expected Core request that was not sent, or a forbidden one that was."""
    for want in expect.get("core", []):
        if not any(
            path == want["path"] and want["params"].items() <= params.items()
            for path, params in calls
        ):
            return f"no {want['path']} {want['params']}"
    for prefix in expect.get("neverCalls", []):
        if any(path.startswith(prefix) for path, _ in calls):
            return f"called {prefix}"
    return None


def actions_match(answer, expect: dict) -> bool:
    actions = [a for card in answer.cards for a in card.actions or []]
    return all(
        any(
            all(action.model_dump().get(key) == value for key, value in wanted.items())
            for action in actions
        )
        for wanted in expect.get("actions", [])
    )


def response_matches(answer, parsed: Understanding, expect: dict) -> bool:
    card = answer.cards[0].kind if answer.cards else None
    if "acceptedAnswers" in expect:
        return parsed.intent in [expect["intent"], *expect.get("alsoOk", [])] and any(
            parsed.intent == option["intent"]
            and answer.kind == option["kind"]
            and card == option["card"]
            for option in expect["acceptedAnswers"]
        )
    return answer.kind == expect["kind"] and card == expect["card"]


def answer_matches(answer, trip: TripContext, expect: dict) -> bool:
    return (
        ("acceptedAnswers" in expect or "kind" not in expect or answer.kind == expect["kind"])
        and (
            "stopOrder" not in expect
            or [s.id for day in trip.days for s in day] == expect["stopOrder"]
        )
        and all(text in answer.text for text in expect.get("textContains", []))
    )


async def run_ci(cases: list[dict]) -> int:
    failures = []
    for case in cases:
        expect = case["expect"]
        calls: list[tuple[str, dict]] = []
        async with fake_core(calls, overrides=case.get("core")) as core:
            request = request_of(case)
            turn = Turn(
                request, plan_of(case, request), core=core, weather=FakeWeather(), today=TODAY
            )
            answer = await turn.answer()
        card = answer.cards[0].kind if answer.cards else None
        problem = core_problem(expect, calls)
        if (
            not response_matches(answer, turn.parsed, expect)
            or turn.degraded
            or problem
            or not actions_match(answer, expect)
            or (
                "offTopic" in expect
                and not any(f.get("offTopic") == expect["offTopic"] for f in answer.facts)
            )
            or any(text in answer.text for text in expect.get("neverContains", []))
            or not answer_matches(answer, turn.next_trip(answer), expect)
            or ("fixedIntent" in expect and turn.parsed.intent != expect["fixedIntent"])
        ):
            got = f"{answer.kind}/{card}" + (f", {problem}" if problem else "")
            failures.append((case["id"], f"{expect['kind']}/{expect['card']}", got))
    print(f"ci: {len(cases) - len(failures)}/{len(cases)} cases match kind, card and Core calls")
    for case_id, want, got in failures:
        print(f"  FAIL {case_id}: want {want}, got {got}")
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
                is_right = is_right and slots_match(parsed, expect.get("slots", {}))
                got = parsed.intent if is_right else parsed.model_dump_json(exclude_defaults=True)
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
    print(f"live intent+slots accuracy: {right}/{total} = {right / total:.1%}")
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


def distinct_replies_match(replies: list[str], minimum: int) -> bool:
    return len({normalize_text(text) for text in replies}) >= minimum


async def run_chain(chains: list[dict], runs: int) -> int:
    """Each turn gets the history and trip of the turn before, as the app sends them."""
    from app.services.assistant.understand import understand  # noqa: PLC0415  # needs .env

    today = today_in_vietnam()
    turns_right = turns_total = chains_stable = 0
    for chain in chains:
        is_stable = True
        for _ in range(runs):
            history: list[HistoryTurn] = []
            replies: list[str] = []
            trip = TripContext.model_validate(chain["trip"]) if chain.get("trip") else None
            async with fake_core(overrides=chain.get("core")) as core:
                for step in chain["turns"]:
                    request = ChatRequest.model_validate(
                        {
                            "conversationId": "00000000-0000-4000-8000-000000000000",
                            "message": step["message"],
                            "contextPostId": str(REEL) if chain["inReel"] else None,
                        }
                    )
                    request.history, request.trip = history[-12:], trip
                    expect = step["expect"]
                    answer = None
                    try:
                        parsed, _ = await understand(request, max_turns=6)
                        turn = Turn(request, parsed, core=core, weather=FakeWeather(), today=today)
                        answer = await turn.answer()
                        next_trip = turn.next_trip(answer)
                        card = answer.cards[0].kind if answer.cards else None
                        is_right = (
                            parsed.intent in [expect["intent"], *expect.get("alsoOk", [])]
                            and slots_match(parsed, expect.get("slots", {}))
                            and ("card" not in expect or card == expect["card"])
                            and actions_match(answer, expect)
                            and answer_matches(answer, next_trip, expect)
                        )
                        got = f"{parsed.intent}/{card}"
                        if not is_right:
                            got += " " + json.dumps(
                                {
                                    "slots": parsed.model_dump(mode="json", exclude_defaults=True),
                                    "kind": answer.kind,
                                    "stopOrder": [s.id for day in next_trip.days for s in day],
                                    "text": answer.text,
                                },
                                ensure_ascii=False,
                            )
                    except Exception as error:  # noqa: BLE001  # an eval run reports, never stops
                        is_right, got = False, type(error).__name__
                    turns_total += 1
                    turns_right += is_right
                    if not is_right:
                        is_stable = False
                        print(f"  MISS {chain['id']} «{step['message']}»: got {got}")
                    if answer is None:
                        break
                    trip = next_trip
                    replies.append(answer.text)
                    history += [
                        HistoryTurn(role="user", text=step["message"]),
                        HistoryTurn(role="assistant", text=answer.text[:500], kind=answer.kind),
                    ]
            if not distinct_replies_match(replies, chain.get("distinctReplies", 0)):
                is_stable = False
                print(f"  MISS {chain['id']}: too few distinct replies")
        chains_stable += is_stable
    print(f"chain turns right: {turns_right}/{turns_total} = {turns_right / turns_total:.1%}")
    print(f"chains right in all {runs} runs: {chains_stable}/{len(chains)}")
    return 0


TOP_RESULTS = 3


async def run_search(queries: list[dict]) -> int:
    """PRD: search right on the first try >= 80%. Needs .env (Controller) and a running Core."""
    from app.api.chat import get_core_client  # noqa: PLC0415  # needs .env
    from app.services.assistant.understand import understand  # noqa: PLC0415

    misses = []
    async with get_core_client() as core:
        for query in queries:
            request = ChatRequest.model_validate(
                {
                    "conversationId": "00000000-0000-4000-8000-000000000000",
                    "message": query["message"],
                }
            )
            try:
                parsed, _ = await understand(request, max_turns=6)
                q = parsed.query or query["message"]
                response = await core.post("/api/search", json={"q": q})
                response.raise_for_status()
                items = [i for s in response.json().get("sections") or [] for i in s["items"]]
            except Exception as error:  # noqa: BLE001  # an eval run reports, never stops
                misses.append((query["id"], query["message"], type(error).__name__))
                continue
            top = [
                normalize_text(
                    " ".join(str(i.get(k) or "") for k in ("title", "subtitle", "location"))
                )
                for i in items[:TOP_RESULTS]
            ]
            if not any(word in text for word in query["anyOf"] for text in top):
                misses.append((query["id"], query["message"], f"q={q!r} top={top}"))
    right = len(queries) - len(misses)
    print(f"search right on the first try: {right}/{len(queries)} = {right / len(queries):.0%}")
    for query_id, message, why in misses:
        print(f"  MISS {query_id} «{message}»: {why[:200]}")
    return 0


class _DroppedRules(logging.Handler):
    """Collects the Verifier's dropped-sentence counts that respond() logs."""

    def __init__(self) -> None:
        super().__init__()
        self.rules: Counter[str] = Counter()

    def emit(self, record: logging.LogRecord) -> None:
        self.rules.update(getattr(record, "rules", {}))


async def run_ab(cases: list[dict]) -> int:
    from app.services.assistant.responder import respond  # noqa: PLC0415  # needs .env

    dropped = _DroppedRules()
    logging.getLogger("app.services.assistant.responder").addHandler(dropped)
    logging.getLogger("app.services.assistant.responder").setLevel(logging.INFO)
    written = fallback = errors = 0
    latencies, cost = [], 0.0
    shown: list[tuple[str, str, str]] = []
    for case in cases:
        request = request_of(case)
        async with fake_core() as core:
            turn = Turn(
                request, plan_of(case, request), core=core, weather=FakeWeather(), today=TODAY
            )
            answer = await turn.answer()
        if answer.kind not in {"answer", "no_result"} or not (answer.cards or answer.facts):
            continue  # A and B say the same: the Responder never runs on these turns
        started = time.perf_counter()
        try:
            sentences, result = await respond(request, answer, today=TODAY)
            cost += result.cost_usd
        except Exception:  # noqa: BLE001  # an eval run reports, never stops
            sentences, errors = None, errors + 1
        latencies.append(time.perf_counter() - started)
        if sentences:
            written += 1
            shown.append((case["id"], answer.text, " ".join(sentences)))
        else:
            fallback += 1
    total = written + fallback
    latencies.sort()
    print(f"ab: {total} turns where the Responder runs (others are identical in A and B)")
    print(
        f"  B written: {written}/{total}; "
        f"B fell back to A's fixed text: {fallback} ({errors} errors)"
    )
    print(f"  Verifier dropped sentences by rule: {dict(dropped.rules) or 'none'}")
    if latencies:
        print(
            f"  B extra latency p50 {latencies[len(latencies) // 2]:.2f} s, "
            f"p95 {latencies[max(0, int(len(latencies) * 0.95) - 1)]:.2f} s; "
            f"cost {cost:.5f} USD ({cost / total:.6f} per turn)"
        )
    for case_id, fixed, voiced in shown:
        print(f"  {case_id}\n    A: {fixed}\n    B: {voiced}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["ci", "live", "chain", "search", "ab"], default="ci")
    parser.add_argument(
        "--cases",
        choices=["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10", "all"],
        default="all",
    )
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if args.mode == "chain":
        chains = [read_jsonl(f"chains.v{n}.jsonl") for n in (1, 2, 3, 4, 5, 6, 7, 8)]
        chains = [chain for group in chains for chain in group]
        return asyncio.run(run_chain(chains, args.runs))
    if args.mode == "search":
        return asyncio.run(run_search(read_jsonl("search.v1.jsonl")))
    versions = (
        ["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10"]
        if args.cases == "all"
        else [args.cases]
    )
    cases = [case for version in versions for case in load_cases(version)]
    if args.mode == "ci":
        return asyncio.run(run_ci(cases))
    if args.mode == "ab":
        return asyncio.run(run_ab(cases))
    return asyncio.run(run_live(cases, args.runs))


if __name__ == "__main__":
    sys.exit(main())
