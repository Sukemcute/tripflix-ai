"""Load test for POST /chat (Tripi) with the real LLMs. It costs money.

    uv run python -m evals.load.run --stages 0.2:60 --budget-usd 0.3            # smoke
    uv run python -m evals.load.run --stages 0.5:120,1:120,2:120 --budget-usd 3 # step up

Open workload: conversations start at random (Poisson) times whatever the server's speed, so a
slow server meets the same arrival rate instead of a client that politely waits (no coordinated
omission). Each conversation plays one chain of evals/assistant (not the reel ones) turn by
turn, carrying history and trip memory as the app does, with a short think time between turns.
A stage "R:S" aims at R turns a second for S seconds; turns are counted in the stage they
start in, and turns that start after the last stage (conversations finishing) under "tail".

Each conversation sends its own X-Forwarded-For so the server sees separate guests: that only
works where ai-service trusts the header (evals/load/compose.load.yaml), never through Traefik.
The chains are written for 16/11/2026 while the server runs on today's clock, so some dated
turns end as a question back instead of a search: fine for load, not a quality score.
"""

import argparse
import asyncio
import json
import math
import random
import sys
from collections import Counter
from collections.abc import AsyncIterator, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

import httpx

CHAINS = sorted(Path(__file__).parents[1].joinpath("assistant").glob("chains.v*.jsonl"))
THINK_SECONDS = (2.0, 6.0)  # between two turns of one conversation; the turn rate is set apart
CLIENT_TIMEOUT_SECONDS = 30.0  # the server gives up at CHAT_TIMEOUT_SECONDS (12)
HISTORY_TURNS = 20  # what the app sends back (CHAT_*_HISTORY_TURNS)


@dataclass
class TurnResult:
    stage: str
    started: float  # seconds since the test began
    status: int  # HTTP status; 0 when no response came
    outcome: str  # "done", the SSE error code, "http_<status>", "timeout" or "transport"
    total: float  # seconds until the stream ended
    first_text: float | None = None  # seconds until the first words: what the user waits for
    llm: str = ""  # Controller outcome: "ok", "http_429", "breaker_open"…
    degraded: list[str] = field(default_factory=list)
    kind: str = ""
    cost_usd: float = 0.0


@dataclass
class Conversation:
    ip: str
    messages: list[str]
    conversation_id: str = field(default_factory=lambda: str(uuid4()))
    history: list[dict[str, str]] = field(default_factory=list)
    trip: dict[str, Any] | None = None


def load_sessions(paths: Iterable[Path]) -> list[list[str]]:
    sessions = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            chain = json.loads(line)
            if not chain.get("inReel"):  # a reel turn needs a real contextPostId
                sessions.append([turn["message"] for turn in chain["turns"]])
    return sessions


def parse_stages(text: str) -> list[tuple[float, float]]:
    stages = []
    for part in text.split(","):
        rate, seconds = part.split(":")
        stages.append((float(rate), float(seconds)))
    if not stages or any(rate <= 0 or seconds <= 0 for rate, seconds in stages):
        raise ValueError("stages look like 0.5:120,1:120 (turns a second : seconds)")
    return stages


def guest_ip(n: int) -> str:
    return f"10.{(n >> 16) & 255}.{(n >> 8) & 255}.{n & 255}"


async def read_events(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    name = None
    async for line in lines:
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: ") and name is not None:
            yield name, json.loads(line.removeprefix("data: "))
            name = None


async def play_turn(
    client: httpx.AsyncClient, url: str, chat: Conversation, message: str, *, stage: str, t0: float
) -> TurnResult:
    loop = asyncio.get_running_loop()
    start = loop.time()
    body = {
        "conversationId": chat.conversation_id,
        "message": message,
        "history": chat.history[-HISTORY_TURNS:],
        "trip": chat.trip,
    }
    result = TurnResult(stage=stage, started=start - t0, status=0, outcome="transport", total=0.0)
    text: list[str] = []
    try:
        async with client.stream(
            "POST", url, json=body, headers={"X-Forwarded-For": chat.ip}
        ) as response:
            result.status = response.status_code
            if response.status_code != 200:
                await response.aread()
                result.outcome = f"http_{response.status_code}"
            else:
                result.outcome = "cut"  # stream ended without done or error
                async for name, data in read_events(response.aiter_lines()):
                    if name == "text":
                        if result.first_text is None:
                            result.first_text = loop.time() - start
                        text.append(data["delta"])
                    elif name == "status" and data.get("step") == "llm":
                        if data.get("outcome") != "calling":
                            result.llm = data["outcome"]
                    elif name == "trip":
                        chat.trip = data
                    elif name == "done":
                        result.outcome = "done"
                        result.kind = data["kind"]
                        result.degraded = data.get("degraded", [])
                        result.cost_usd = data["usage"]["costUsd"]
                    elif name == "error":
                        result.outcome = data.get("code", "error")
                        result.cost_usd = data.get("usage", {}).get("costUsd", 0.0)
    except httpx.TimeoutException:
        result.outcome = "timeout"
    except httpx.HTTPError:
        result.outcome = "transport"
    result.total = loop.time() - start
    chat.history.append({"role": "user", "text": message})
    if text and result.kind:
        reply = "".join(text)[:2000]
        chat.history.append({"role": "assistant", "text": reply, "kind": result.kind})
    return result


class LoadTest:
    def __init__(self, url: str, stages: list[tuple[float, float]], *, budget_usd: float) -> None:
        self.url = url
        self.stages = stages
        self.budget_usd = budget_usd
        self.results: list[TurnResult] = []
        self.stop = asyncio.Event()
        self.t0 = 0.0

    def stage_at(self, elapsed: float) -> str:
        end = 0.0
        for i, (_, seconds) in enumerate(self.stages):
            end += seconds
            if elapsed < end:
                return str(i + 1)
        return "tail"

    def record(self, result: TurnResult) -> None:
        self.results.append(result)
        if sum(r.cost_usd for r in self.results) >= self.budget_usd and not self.stop.is_set():
            print(f"Dừng: đã tiêu {self.budget_usd} USD (--budget-usd).", file=sys.stderr)
            self.stop.set()

    async def converse(self, client: httpx.AsyncClient, chat: Conversation, rng: random.Random):
        loop = asyncio.get_running_loop()
        for i, message in enumerate(chat.messages):
            if i:
                await asyncio.sleep(rng.uniform(*THINK_SECONDS))
            if self.stop.is_set():
                return
            stage = self.stage_at(loop.time() - self.t0)
            self.record(await play_turn(client, self.url, chat, message, stage=stage, t0=self.t0))

    async def run(self, sessions: list[list[str]], *, seed: int) -> None:
        loop = asyncio.get_running_loop()
        rng = random.Random(seed)
        turns_per_chat = mean(len(s) for s in sessions)
        tasks: set[asyncio.Task[None]] = set()
        timeout = httpx.Timeout(CLIENT_TIMEOUT_SECONDS)
        limits = httpx.Limits(max_connections=None, max_keepalive_connections=100)
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            self.t0 = loop.time()
            started = 0
            for rate, seconds in self.stages:
                end = loop.time() + seconds
                while not self.stop.is_set():
                    wait = rng.expovariate(rate / turns_per_chat)
                    if loop.time() + wait >= end:
                        await asyncio.sleep(max(0.0, end - loop.time()))
                        break
                    await asyncio.sleep(wait)
                    started += 1
                    chat = Conversation(ip=guest_ip(started), messages=rng.choice(sessions))
                    task = asyncio.create_task(self.converse(client, chat, rng))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
            await asyncio.gather(*tasks)  # let started conversations finish (the tail)


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


def peak_inflight(results: list[TurnResult]) -> int:
    edges = sorted(
        [(r.started, 1) for r in results] + [(r.started + r.total, -1) for r in results],
        key=lambda edge: (edge[0], edge[1]),  # an end before a start at the same instant
    )
    peak = level = 0
    for _, step in edges:
        level += step
        peak = max(peak, level)
    return peak


# "rules": code decided the turn, so there was no LLM call to fail.
LLM_FINE = ("ok", "rules")


def summarize(results: list[TurnResult], stages: list[tuple[float, float]]) -> list[dict]:
    rows = []
    names = [str(i + 1) for i in range(len(stages))] + ["tail"]
    for i, name in enumerate(names):
        turns = [r for r in results if r.stage == name]
        if not turns:
            continue
        done = [r for r in turns if r.outcome == "done"]
        full = [r for r in done if r.llm in LLM_FINE and not r.degraded]
        first = [r.first_text for r in done if r.first_text is not None]
        totals = [r.total for r in done]
        seconds = stages[i][1] if name != "tail" else None
        rows.append(
            {
                "stage": name,
                "target": stages[i][0] if name != "tail" else None,
                "turns": len(turns),
                "rate": round(len(turns) / seconds, 2) if seconds else None,
                "peakInflight": peak_inflight(turns),
                "donePct": round(100 * len(done) / len(turns), 1),
                "fullPct": round(100 * len(full) / len(turns), 1),
                "firstP50": percentile(first, 50),
                "firstP95": percentile(first, 95),
                "totalP50": percentile(totals, 50),
                "totalP95": percentile(totals, 95),
                "totalP99": percentile(totals, 99),
                "failures": dict(Counter(r.outcome for r in turns if r.outcome != "done")),
                "llm": dict(Counter(r.llm or "-" for r in turns if r.llm not in LLM_FINE)),
                "degraded": dict(Counter(d for r in done for d in r.degraded)),
                "costUsd": round(sum(r.cost_usd for r in turns), 4),
            }
        )
    return rows


def show(rows: list[dict]) -> str:
    def sec(value: float | None) -> str:
        return "-" if value is None else f"{value:.2f}"

    head = "stage  target  turns  rate  inflight  done%  full%  text p50/p95  total p50/p95/p99"
    lines = [head]
    for row in rows:
        target = "-" if row["target"] is None else f"{row['target']:g}"
        rate = "-" if row["rate"] is None else f"{row['rate']:g}"
        lines.append(
            f"{row['stage']:<6} {target:>6} {row['turns']:>6} {rate:>5} {row['peakInflight']:>9}"
            f" {row['donePct']:>6} {row['fullPct']:>6}  {sec(row['firstP50']):>5}/"
            f"{sec(row['firstP95']):<6}  {sec(row['totalP50'])}/{sec(row['totalP95'])}/"
            f"{sec(row['totalP99'])}"
        )
        for key in ("failures", "llm", "degraded"):
            if row[key]:
                lines.append(f"       {key}: {row[key]}")
        lines.append(f"       cost: {row['costUsd']} USD")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load test for POST /chat (Tripi).")
    parser.add_argument("--url", default="http://localhost:8000/chat")
    parser.add_argument("--stages", required=True, help="turns a second : seconds, e.g. 0.5:120")
    parser.add_argument("--budget-usd", type=float, required=True, help="stop starting turns here")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, help="write every turn as JSON lines")
    args = parser.parse_args()

    test = LoadTest(args.url, parse_stages(args.stages), budget_usd=args.budget_usd)
    asyncio.run(test.run(load_sessions(CHAINS), seed=args.seed))
    rows = summarize(test.results, test.stages)
    print(show(rows))
    if args.out:
        args.out.write_text(
            "".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in test.results),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
