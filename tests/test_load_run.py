import asyncio
import json

import httpx

from evals.load.run import (
    Conversation,
    TurnResult,
    load_sessions,
    parse_stages,
    peak_inflight,
    percentile,
    play_turn,
    summarize,
)


def sse(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


STREAM = (
    sse("status", {"step": "llm", "outcome": "calling"})
    + sse("status", {"step": "llm", "outcome": "ok"})
    + sse("text", {"delta": "Vũng Tàu nè. "})
    + sse("text", {"delta": "Bạn ở mấy đêm?"})
    + sse("trip", {"place": "Vũng Tàu"})
    + sse("done", {"kind": "answer", "usage": {"costUsd": 0.0012}, "degraded": ["responder"]})
)


def test_play_turn_reads_the_stream_and_carries_memory():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((json.loads(request.content), request.headers["X-Forwarded-For"]))
        return httpx.Response(200, content=STREAM.encode())

    async def go():
        chat = Conversation(ip="10.0.0.1", messages=[])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await play_turn(client, "http://ai/chat", chat, "đi vũng tàu", stage="1", t0=0)
            await play_turn(client, "http://ai/chat", chat, "2 đêm", stage="1", t0=0)
        return first

    first = asyncio.run(go())
    assert (first.outcome, first.llm, first.kind) == ("done", "ok", "answer")
    assert first.degraded == ["responder"] and first.cost_usd == 0.0012
    assert first.first_text is not None and first.first_text <= first.total
    body, ip = seen[1]
    assert ip == "10.0.0.1"
    assert body["trip"] == {"place": "Vũng Tàu"}
    assert body["history"] == [
        {"role": "user", "text": "đi vũng tàu"},
        {"role": "assistant", "text": "Vũng Tàu nè. Bạn ở mấy đêm?", "kind": "answer"},
    ]


def test_play_turn_counts_a_refusal_by_status():
    async def go():
        transport = httpx.MockTransport(lambda _: httpx.Response(503, json={"code": "CHAT_BUSY"}))
        async with httpx.AsyncClient(transport=transport) as client:
            chat = Conversation(ip="10.0.0.2", messages=[])
            return await play_turn(client, "http://ai/chat", chat, "hi", stage="2", t0=0)

    result = asyncio.run(go())
    assert (result.status, result.outcome, result.first_text) == (503, "http_503", None)


def test_load_sessions_skips_reel_chains(tmp_path):
    path = tmp_path / "chains.v1.jsonl"
    path.write_text(
        '{"inReel": false, "turns": [{"message": "a"}, {"message": "b"}]}\n'
        '{"inReel": true, "turns": [{"message": "reel"}]}\n',
        encoding="utf-8",
    )
    assert load_sessions([path]) == [["a", "b"]]


def test_parse_stages():
    assert parse_stages("0.5:120,1:60") == [(0.5, 120.0), (1.0, 60.0)]


def test_percentile_is_nearest_rank():
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 50) == 50.0
    assert percentile(values, 95) == 95.0
    assert percentile([3.0], 99) == 3.0
    assert percentile([], 50) is None


def turn(started: float, total: float, **kw) -> TurnResult:
    base = {"stage": "1", "status": 200, "outcome": "done", "llm": "ok", "first_text": total / 2}
    return TurnResult(started=started, total=total, **(base | kw))


def test_peak_inflight_counts_overlap_only():
    # 0-2 and 1-3 overlap; 3-4 starts as the second ends.
    assert peak_inflight([turn(0, 2), turn(1, 2), turn(3, 1)]) == 2


def test_summarize_splits_done_full_and_failures():
    results = [
        turn(0, 4, cost_usd=0.001),
        turn(1, 6, degraded=["responder"]),
        turn(2, 1, outcome="http_503", status=503, llm="", first_text=None),
        turn(70, 5, stage="tail"),
    ]
    first, tail = summarize(results, [(0.05, 60)])
    counts = (first["turns"], first["rate"], first["donePct"], first["fullPct"])
    assert counts == (3, 0.05, 66.7, 33.3)
    assert first["failures"] == {"http_503": 1}
    assert first["degraded"] == {"responder": 1}
    assert first["totalP95"] == 6
    assert (tail["stage"], tail["rate"]) == ("tail", None)


def test_summarize_counts_a_code_decided_turn_as_full():
    results = [turn(0, 1, llm="rules"), turn(1, 4), turn(2, 5, llm="http_429")]
    (row,) = summarize(results, [(0.05, 60)])
    assert row["fullPct"] == 66.7
    assert row["llm"] == {"http_429": 1}
