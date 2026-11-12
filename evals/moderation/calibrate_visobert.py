"""Offline dev calibration and frozen test evaluation; no provider calls."""

import argparse
import csv
import hashlib
import json
import math
import subprocess
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

MODEL = "nd-khoa/vihsd-uit-visobert-v2"
REVISION = "5e8e892f45bf3d52bc3d4c780b6235b65714f07b"
ROOT = Path(__file__).resolve().parents[2]
GRID = (0.5, 0.8, 0.9, 0.95, 0.97, 0.99, 1.01)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def canonical(text: str) -> str:
    return " ".join(
        "".join(
            c for c in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(c)
        )
        .replace("đ", "d")
        .split()
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)


def validate_rows(rows: list[dict[str, Any]]) -> None:
    if not rows or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Dataset must have unique IDs and at least one row")
    for row in rows:
        if not all(
            isinstance(row.get(k), str) and row[k].strip()
            for k in ("id", "text", "kind", "group_id")
        ):
            raise ValueError("Each row needs id, text, kind and group_id strings")
        if type(row.get("toxic")) is not bool:
            raise ValueError("toxic must be a JSON boolean; resolve needs_context separately")
    if {r["toxic"] for r in rows} != {False, True}:
        raise ValueError("Evaluation requires both clean and toxic samples")


def export_core(rows: list[dict[str, Any]], core_repo: Path) -> dict[str, Any]:
    rules = core_repo / "apps/core-api/src/modules/content/moderation/domain/rules.ts"
    # Execute the actual TypeScript rules with Node 24's built-in type stripping.
    script = (
        "import {readFileSync} from 'node:fs';"
        f"import {{evaluateRules}} from {json.dumps(rules.resolve().as_uri())};"
        "const rows=JSON.parse(readFileSync(0,'utf8'));"
        "process.stdout.write(JSON.stringify(Object.fromEntries(rows.map(r=>"
        "[r.id,evaluateRules(r.text).map(h=>h.code)]))));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        input=json.dumps(rows, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return {
        "rules_sha256": hashlib.sha256(rules.read_bytes()).hexdigest(),
        "hits": json.loads(result.stdout),
        "allowed_domains": [],
    }


def prepare(
    review: Path, results_zip: Path, cache_path: Path, core_repo: Path, output: Path
) -> None:
    with review.open(encoding="utf-8-sig", newline="") as source:
        reviewed = list(csv.DictReader(source))
    rows, challenge = [], []
    for item in reviewed:
        decision, label = item["Quyết định"].strip(), item["Nhãn duyệt"].strip()
        if decision in {"Loại", "Cần thảo luận"} or label == "needs_context":
            challenge.append(item)
            continue
        if decision not in {"Giữ", "Sửa nhãn", "Sửa câu"} or label not in {"clean", "toxic"}:
            raise ValueError(f"Unresolved review decision for {item['ID']}")
        text = item["Câu sửa"].strip() if decision == "Sửa câu" else item["Câu cần duyệt"]
        rows.append(
            {
                "id": item["ID"],
                "text": text,
                "toxic": label == "toxic",
                "kind": item["Nhóm"],
                "group_id": digest(canonical(item["Câu trước biến đổi"])),
            }
        )
    validate_rows(rows)
    cache = read_json(cache_path)
    original_path = ROOT / "evals/moderation/vi_3k.jsonl"
    original = [
        json.loads(line) for line in original_path.read_text("utf-8").splitlines() if line.strip()
    ]
    with zipfile.ZipFile(results_zip) as archive:
        run = json.loads(archive.read("visobert-3k.json"))
    if run["model"] != MODEL or run["revision"] != REVISION:
        raise ValueError("Unexpected model checkpoint")
    if run["sha256"] != hashlib.sha256(original_path.read_bytes()).hexdigest():
        raise ValueError("Colab predictions do not match the original dataset")
    original_by_text = {r["text"]: r["id"] for r in original}
    scores, remapped_cache, pending = {}, {}, []
    for row in rows:
        old_id = original_by_text.get(row["text"])
        scores[row["id"]] = {"text_sha256": digest(row["text"])}
        if old_id is None:
            pending.append(row)
            continue
        entry = cache[old_id]
        if entry["text"] != row["text"]:
            raise ValueError(f"Historical cache mismatch: {old_id}")
        remapped_cache[row["id"]] = entry
        scores[row["id"]].update(openai_flagged=entry["flagged"], **run["predictions"][old_id])
    core = export_core(rows, core_repo)
    for key, score in scores.items():
        score["core_codes"] = core["hits"][key]
    policy_path = review.parent / "ANNOTATION_POLICY.md"
    pack = {
        "split": "dev",
        "rows": rows,
        "scores": scores,
        "model": MODEL,
        "revision": REVISION,
        "openai_models": sorted({entry["model"] for entry in remapped_cache.values()}),
        "rules_sha256": core["rules_sha256"],
        "allowed_domains": [],
        "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "review_sha256": hashlib.sha256(review.read_bytes()).hexdigest(),
        "excluded_count": len(challenge),
        "pending_ids": [r["id"] for r in pending],
        "historical_text_hashes": [digest(canonical(r["text"])) for r in original],
    }
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "dev-pack.json", pack)
    write_json(output / "challenge.json", challenge)
    write_json(output / "openai-dev-cache.json", remapped_cache)
    with (output / "dev.jsonl").open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(
        output / "test-template.json",
        {
            "split": "test",
            "rows": [],
            "scores": {},
            "model": MODEL,
            "revision": REVISION,
            "rules_sha256": core["rules_sha256"],
            "allowed_domains": [],
            "openai_models": pack["openai_models"],
            "policy_sha256": pack["policy_sha256"],
        },
    )
    with zipfile.ZipFile(output / "colab-input.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        archive.write(output / "dev-pack.json", "dev-pack.json")
        archive.write(Path(__file__), "calibrate_visobert.py")
        for path in sorted((ROOT / "app").rglob("*.py")):
            archive.write(path, path.relative_to(ROOT).as_posix())


def merge_openai(pack: dict[str, Any], cache: dict[str, Any]) -> None:
    for row in pack["rows"]:
        entry = cache.get(row["id"])
        if entry is None:
            raise ValueError(f"OpenAI prediction missing: {row['id']}")
        if entry["text"] != row["text"] or entry["model"] not in pack["openai_models"]:
            raise ValueError(f"OpenAI input/model mismatch: {row['id']}")
        pack["scores"][row["id"]]["openai_flagged"] = entry["flagged"]


def validate_pack(pack: dict[str, Any]) -> None:
    validate_rows(pack["rows"])
    if pack["model"] != MODEL or pack["revision"] != REVISION:
        raise ValueError("Checkpoint differs from calibrated model")
    if set(pack["scores"]) != {r["id"] for r in pack["rows"]}:
        raise ValueError("Scores must cover exactly the dataset IDs")
    for row in pack["rows"]:
        score = pack["scores"][row["id"]]
        if not {"clean", "offensive", "hate", "openai_flagged", "core_codes"} <= score.keys():
            raise ValueError(f"Incomplete predictions: {row['id']}")
        probs = [score[k] for k in ("clean", "offensive", "hate")]
        if not all(type(p) in {int, float} and math.isfinite(p) and 0 <= p <= 1 for p in probs):
            raise ValueError("Invalid model probabilities")
        if abs(sum(probs) - 1) > 1e-5:
            raise ValueError("Model probabilities must sum to one")
        if score["text_sha256"] != digest(row["text"]):
            raise ValueError("Prediction text differs from labelled text")
        if type(score["openai_flagged"]) is not bool or not isinstance(score["core_codes"], list):
            raise ValueError("Invalid provider or Core prediction")


def prepare_test(
    data_path: Path, predictions_path: Path, cache_path: Path, core_repo: Path, dev_path: Path
) -> dict[str, Any]:
    rows = [
        json.loads(line) for line in data_path.read_text("utf-8-sig").splitlines() if line.strip()
    ]
    validate_rows(rows)
    run, cache, dev = read_json(predictions_path), read_json(cache_path), read_json(dev_path)
    if run["sha256"] != hashlib.sha256(data_path.read_bytes()).hexdigest():
        raise ValueError("Test predictions do not match the dataset bytes")
    if run["model"] != MODEL or run["revision"] != REVISION:
        raise ValueError("Unexpected test checkpoint")
    core = export_core(rows, core_repo)
    scores = {}
    for row in rows:
        key = row["id"]
        if cache[key]["text"] != row["text"]:
            raise ValueError(f"OpenAI cache text mismatch: {key}")
        scores[key] = {
            "text_sha256": digest(row["text"]),
            "openai_flagged": cache[key]["flagged"],
            "core_codes": core["hits"][key],
            **run["predictions"][key],
        }
    pack = {
        "split": "test",
        "rows": rows,
        "scores": scores,
        "model": MODEL,
        "revision": REVISION,
        "rules_sha256": core["rules_sha256"],
        "allowed_domains": [],
        "policy_sha256": dev["policy_sha256"],
        "openai_models": sorted({cache[r["id"]]["model"] for r in rows}),
    }
    validate_pack(pack)
    return pack


def measure(rows: list[dict[str, Any]], flags: dict[str, bool]) -> dict[str, Any]:
    tp = sum(r["toxic"] and flags[r["id"]] for r in rows)
    fp = sum(not r["toxic"] and flags[r["id"]] for r in rows)
    fn = sum(r["toxic"] and not flags[r["id"]] for r in rows)
    tn = len(rows) - tp - fp - fn
    target = [r for r in rows if r["toxic"] and r["kind"] in {"hate", "harassment"}]
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else 0,
        "recall": tp / (tp + fn) if tp + fn else 0,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0,
        "fpr": fp / (fp + tn) if fp + tn else 0,
        "target_total": len(target),
        "target_recall": sum(flags[r["id"]] for r in target) / len(target) if target else None,
    }


def predict(pack: dict[str, Any], config: dict[str, Any]) -> dict[str, bool]:
    flags = {}
    for key, score in pack["scores"].items():
        baseline = score["openai_flagged"] or bool(score["core_codes"])
        if config["mode"] == "sum":
            extra = score["offensive"] + score["hate"] >= config["threshold"]
        elif config["mode"] == "separate":
            extra = (
                score["offensive"] >= config["offensive_threshold"]
                or score["hate"] >= config["hate_threshold"]
            )
        elif config["mode"] == "baseline":
            extra = False
        else:
            raise ValueError("Unknown calibration mode")
        flags[key] = baseline or extra
    return flags


def calibrate(pack: dict[str, Any], max_fpr_delta: float = 0.01) -> dict[str, Any]:
    validate_pack(pack)
    if pack["split"] != "dev" or not 0 <= max_fpr_delta <= 1:
        raise ValueError("Calibrate only on dev, with a valid FPR budget")
    rows = pack["rows"]
    baseline = measure(rows, predict(pack, {"mode": "baseline"}))
    if baseline["target_total"] == 0:
        raise ValueError("Dev needs toxic harassment/hate examples")
    candidates = [{"mode": "baseline"}]
    candidates += [{"mode": "sum", "threshold": t} for t in GRID]
    candidates += [
        {"mode": "separate", "offensive_threshold": a, "hate_threshold": b}
        for a in GRID
        for b in GRID
    ]
    sweep = [{"config": c, "metrics": measure(rows, predict(pack, c))} for c in candidates]
    eligible = [r for r in sweep if r["metrics"]["fpr"] <= baseline["fpr"] + max_fpr_delta]
    best = max(
        eligible,
        key=lambda r: (r["metrics"]["target_recall"], -r["metrics"]["fp"], r["metrics"]["f1"]),
    )
    return {
        "config": best["config"],
        "dev_metrics": best["metrics"],
        "dev_baseline": baseline,
        "max_fpr_delta": max_fpr_delta,
        "dev_sha256": digest(pack),
        "model": pack["model"],
        "revision": pack["revision"],
        "rules_sha256": pack["rules_sha256"],
        "allowed_domains": pack["allowed_domains"],
        "openai_models": pack["openai_models"],
        "policy_sha256": pack["policy_sha256"],
        "sweep": sweep,
    }


def evaluate_test(
    dev: dict[str, Any], test: dict[str, Any], lock: dict[str, Any]
) -> dict[str, Any]:
    validate_pack(dev)
    validate_pack(test)
    if dev["split"] != "dev" or test["split"] != "test" or digest(dev) != lock["dev_sha256"]:
        raise ValueError("Frozen config must match the original dev pack")
    for key in (
        "model",
        "revision",
        "rules_sha256",
        "allowed_domains",
        "openai_models",
        "policy_sha256",
    ):
        if lock[key] != test[key]:
            raise ValueError(f"Test differs from frozen setup: {key}")
    if {r["id"] for r in dev["rows"]} & {r["id"] for r in test["rows"]}:
        raise ValueError("Dev/test IDs overlap")
    if {r["group_id"] for r in dev["rows"]} & {r["group_id"] for r in test["rows"]}:
        raise ValueError("Dev/test base groups overlap")
    historical = set(dev["historical_text_hashes"])
    historical.update(digest(canonical(r["text"])) for r in dev["rows"])
    if any(digest(canonical(r["text"])) in historical for r in test["rows"]):
        raise ValueError("Test reuses historical or dev text")
    baseline_flags = predict(test, {"mode": "baseline"})
    flags = predict(test, lock["config"])
    baseline, hybrid = measure(test["rows"], baseline_flags), measure(test["rows"], flags)
    target_delta = (
        hybrid["target_recall"] - baseline["target_recall"] if hybrid["target_total"] else None
    )
    return {
        "test_sha256": digest(test),
        "lock_sha256": digest(lock),
        "baseline": baseline,
        "hybrid": hybrid,
        "target_recall_delta": target_delta,
        "fpr_delta": hybrid["fpr"] - baseline["fpr"],
        "meets_proposed_gate": target_delta is not None
        and target_delta >= 0.10
        and hybrid["fpr"] - baseline["fpr"] <= lock["max_fpr_delta"],
        "by_kind": {
            kind: {"baseline": measure(group, baseline_flags), "hybrid": measure(group, flags)}
            for kind in sorted({r["kind"] for r in test["rows"]})
            if (group := [r for r in test["rows"] if r["kind"] == kind])
        },
        "errors": [
            {"id": r["id"], "expected": r["toxic"], "predicted": flags[r["id"]]}
            for r in test["rows"]
            if r["toxic"] != flags[r["id"]]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--review", type=Path, required=True)
    prep.add_argument("--results-zip", type=Path, required=True)
    prep.add_argument("--cache", type=Path, required=True)
    prep.add_argument("--core-repo", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    tune = sub.add_parser("tune")
    tune.add_argument("--dev", type=Path, required=True)
    tune.add_argument("--output", type=Path, required=True)
    tune.add_argument("--max-fpr-delta", type=float, default=0.01)
    test = sub.add_parser("test")
    test.add_argument("--dev", type=Path, required=True)
    test.add_argument("--test", type=Path, required=True)
    test.add_argument("--lock", type=Path, required=True)
    test.add_argument("--output", type=Path, required=True)
    build_test = sub.add_parser("prepare-test")
    build_test.add_argument("--data", type=Path, required=True)
    build_test.add_argument("--predictions", type=Path, required=True)
    build_test.add_argument("--cache", type=Path, required=True)
    build_test.add_argument("--core-repo", type=Path, required=True)
    build_test.add_argument("--dev", type=Path, required=True)
    build_test.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.review, args.results_zip, args.cache, args.core_repo, args.output)
    elif args.command == "tune":
        write_json(args.output, calibrate(read_json(args.dev), args.max_fpr_delta))
    elif args.command == "prepare-test":
        write_json(
            args.output,
            prepare_test(args.data, args.predictions, args.cache, args.core_repo, args.dev),
        )
    else:
        write_json(
            args.output,
            evaluate_test(read_json(args.dev), read_json(args.test), read_json(args.lock)),
        )


if __name__ == "__main__":
    main()
