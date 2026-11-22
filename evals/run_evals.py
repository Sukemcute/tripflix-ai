"""Evals for the comment summary (RULES §10: run before and after any prompt or agent change).

    uv run python evals/run_evals.py                      # fake LLM: rules and gates only, free
    uv run python evals/run_evals.py --llm cassette       # replay recorded LLM outputs, free
    uv run python evals/run_evals.py --llm live --record  # real LLM from .env, records cassettes

Runs the whole pipeline (rules, LLM, validator) on the 15 labelled seed posts in
evals/summary/seed and checks the P12 hard gates, then scores against the labels:
- hard gates (must all pass): valid output (not failed), citations exist, status matches the
  label, people counted by code, 0 missed safety, 0 injection cited, 0 counts/money/PII
  written by the LLM, every topic has 2+ people;
- soft scores (Key Point Analysis, Bar-Haim et al. 2020): a labelled point is found when an
  output point has the same polarity and aspect and cites at least one of its comments;
  likewise for reality gaps, which must also be about the same claim (CLAIM_MATCH); plus
  comments cited that must not be;
- operations: latency p50/p95, LLM calls, tokens, estimated cost.
Cassettes live in data/cassettes (git-ignored): recorded outputs stay out of the repo.
"""

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.clients.llm.base import LlmClient  # noqa: E402
from app.clients.llm.fake import FakeLlmClient  # noqa: E402
from app.services.summary.comment_classifier import (  # noqa: E402
    CommentClassifier,
    load_comment_classifier,
)
from app.services.summary.pipeline import SummaryRun, run_summary  # noqa: E402
from app.services.summary.prompt import load_system_prompt  # noqa: E402
from app.services.summary.schemas import CommentIn, ItineraryItemIn  # noqa: E402
from app.services.summary.validator import find_banned_reason  # noqa: E402
from app.services.summary.vi_text import normalize_text  # noqa: E402

SEED_DIR = ROOT / "evals" / "summary" / "seed"
CASSETTE_DIR = ROOT / "data" / "cassettes"
NOW = datetime(2026, 11, 5, tzinfo=UTC)  # seed comments are dated October 2026
CLAIM_MATCH = 0.6  # share of the labelled claim's words; proposal by Claude
GATES = (
    "valid_output",
    "citations_exist",
    "status_matches",
    "people_counted",
    "no_safety_miss",
    "no_injection_cited",
    "no_llm_numbers",
    "topics_two_people",
)


@dataclass
class PostResult:
    post_id: str
    status: str
    label_status: str
    gates: dict[str, bool]
    points_found: int = 0
    points_labelled: int = 0
    points_output: int = 0
    points_correct: int = 0
    gaps_found: int = 0
    gaps_labelled: int = 0
    wrongly_cited: list[str] = field(default_factory=lambda: list[str]())
    seconds: float = 0.0
    llm_called: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def load_seed() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SEED_DIR.glob("*.json"))]


def score_post(post: dict[str, Any], run: SummaryRun, seconds: float) -> PostResult:
    labels = post["labels"]
    request = run.request
    assert request is not None, "eval runs never pass a previous hash"
    body = request.model_dump(mode="json", by_alias=True)
    content = body.get("content") or {}
    author = {c["comment_id"]: c["author_id"] for c in post["comments"]}
    points = [("pro", p) for p in content.get("pros", [])] + [
        ("con", p) for p in content.get("cons", [])
    ]
    gaps = content.get("realityGaps", [])
    topics = content.get("topics", [])
    cited = {i for g in [p for _, p in points] + gaps + topics for i in g["commentIds"]}
    warned = {i for w in (body.get("safety") or {}).get("warnings", []) for i in w["commentIds"]}
    public = {s["comment_id"] for s in labels["safety"] if s["visibility"] == "public"}
    hidden = {s["comment_id"] for s in labels["safety"] if s["visibility"] != "public"}
    injection = {i for i, why in labels["must_not_cite"].items() if why == "injection"}
    texts = [p["text"] for _, p in points] + [g["reality"] for g in gaps]
    texts += [t for topic in topics for t in (topic["label"], topic["summary"])]

    gates = {
        "valid_output": request.status != "failed",
        "citations_exist": cited <= set(author) and warned <= set(author),
        "status_matches": request.status == labels["status"],
        "people_counted": all(
            g["people"] >= max(2, len({author[i] for i in g["commentIds"]}))
            for g in [p for _, p in points] + topics
        ),
        "no_safety_miss": public <= warned and not (warned & (hidden | set(labels["not_safety"]))),
        "no_injection_cited": not (cited & injection),
        "no_llm_numbers": not any(find_banned_reason(t) for t in texts),
        "topics_two_people": all(len({author[i] for i in t["commentIds"]}) >= 2 for t in topics),
    }

    def found(label_ids: list[str], outputs: list[dict[str, Any]]) -> bool:
        return any(set(label_ids) & set(o["commentIds"]) for o in outputs)

    result = PostResult(post["post_id"], request.status, labels["status"], gates, seconds=seconds)
    for lp in labels["points"]:
        same = [p for pol, p in points if pol == lp["polarity"] and p["aspect"] == lp["aspect"]]
        result.points_found += found(lp["comment_ids"], same)
    result.points_labelled = len(labels["points"])
    result.points_output = len(points)
    result.points_correct = sum(
        any(
            pol == lp["polarity"]
            and p["aspect"] == lp["aspect"]
            and set(lp["comment_ids"]) & set(p["commentIds"])
            for lp in labels["points"]
        )
        for pol, p in points
    )
    result.gaps_labelled = len(labels["reality_gaps"])
    result.gaps_found = sum(
        found(g["comment_ids"], [o for o in gaps if is_same_claim(g["claim"], o["claim"])])
        for g in labels["reality_gaps"]
    )
    result.wrongly_cited = sorted(cited & set(labels["must_not_cite"]))
    if run.llm:
        result.llm_called = True
        result.input_tokens = run.llm.input_tokens
        result.output_tokens = run.llm.output_tokens
        result.cost_usd = run.llm.cost_usd
    return result


def is_same_claim(label_claim: str, output_claim: str) -> bool:
    """Most words of the labelled claim appear in the claim the output answered.

    Without it one gap citing many comments counted for every claim of the caption (BAO_CAO).
    """
    label = set(normalize_text(label_claim).split())
    return bool(label) and len(label & set(normalize_text(output_claim).split())) >= (
        CLAIM_MATCH * len(label)
    )


def run_post(
    post: dict[str, Any], llm: LlmClient, classifier: CommentClassifier | None = None
) -> tuple[SummaryRun, float]:
    started = time.perf_counter()
    run = run_summary(
        comments=[CommentIn.model_validate(c) for c in post["comments"]],
        caption=post["caption"],
        itinerary=[ItineraryItemIn.model_validate(i) for i in post["itinerary"]],
        previous_hash=None,
        now=NOW,
        llm=llm,
        classifier=classifier,
    )
    return run, time.perf_counter() - started


def summarize(results: list[PostResult]) -> dict[str, Any]:
    def ratio(num: int, den: int) -> float | None:
        return round(num / den, 3) if den else None

    called = [r for r in results if r.llm_called]
    secs = sorted(r.seconds for r in called) or [0.0]
    return {
        "posts": len(results),
        "gates_passed": {g: sum(r.gates[g] for r in results) for g in GATES},
        "all_gates_pass": all(all(r.gates.values()) for r in results),
        "status_accuracy": ratio(sum(r.status == r.label_status for r in results), len(results)),
        "point_recall": ratio(
            sum(r.points_found for r in results), sum(r.points_labelled for r in results)
        ),
        "point_precision": ratio(
            sum(r.points_correct for r in results), sum(r.points_output for r in results)
        ),
        "gap_recall": ratio(
            sum(r.gaps_found for r in results), sum(r.gaps_labelled for r in results)
        ),
        "wrongly_cited": sum(len(r.wrongly_cited) for r in results),
        "llm_calls": len(called),
        "latency_p50_s": round(statistics.median(secs), 2),
        "latency_p95_s": round(secs[min(len(secs) - 1, round(0.95 * (len(secs) - 1)))], 2),
        "input_tokens": sum(r.input_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
        "cost_usd": round(sum(r.cost_usd for r in results), 4),
    }


def make_llm(mode: str, post_id: str, prompt_version: str) -> LlmClient:
    if mode == "fake":
        return FakeLlmClient()
    if mode == "cassette":
        path = CASSETTE_DIR / f"{prompt_version}.{post_id}.json"
        if not path.exists():  # posts under the threshold never call the LLM: no cassette
            return FakeLlmClient()
        return FakeLlmClient(json.loads(path.read_text(encoding="utf-8"))["output"])
    from app.core.config import get_settings  # noqa: PLC0415  # live needs .env only here
    from app.workers.summary_worker import build_llm  # noqa: PLC0415

    return build_llm(get_settings())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--llm", choices=["fake", "cassette", "live"], default="fake")
    parser.add_argument("--record", action="store_true", help="live only: save cassettes")
    parser.add_argument("--out", type=Path, help="write the full JSON report here")
    parser.add_argument(
        "--classifier-dir", type=Path, help="comment classifier bundle; default: rules only"
    )
    args = parser.parse_args()
    classifier = (
        load_comment_classifier(args.classifier_dir, threads=2, batch=8)
        if args.classifier_dir
        else None
    )
    if args.classifier_dir and classifier is None:
        raise SystemExit(f"no usable classifier bundle in {args.classifier_dir}")

    prompt_version, _ = load_system_prompt()
    results: list[PostResult] = []
    for post in load_seed():
        llm = make_llm(args.llm, post["post_id"], prompt_version)
        run, seconds = run_post(post, llm, classifier)
        if args.record and args.llm == "live" and run.llm:
            CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
            record = run.llm.__dict__ | {"seconds": seconds, "prompt_version": prompt_version}
            (CASSETTE_DIR / f"{prompt_version}.{post['post_id']}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        result = score_post(post, run, seconds)
        results.append(result)
        failed = [g for g, ok in result.gates.items() if not ok]
        print(
            f"{result.post_id:28} {result.status:18} label={result.label_status:18} "
            f"points {result.points_found}/{result.points_labelled} "
            f"gates {'OK' if not failed else 'FAIL ' + ','.join(failed)}"
        )
    report = summarize(results) | {"llm": args.llm, "prompt_version": prompt_version}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        args.out.write_text(
            json.dumps(report | {"posts_detail": [r.__dict__ for r in results]}, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
