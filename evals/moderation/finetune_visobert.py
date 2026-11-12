"""Data splitting and validation-only threshold selection for Colab fine-tuning."""

import argparse
import hashlib
import json
import math
import random
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from evals.moderation.calibrate_visobert import canonical, measure, validate_pack, validate_rows

SEED = 42
THRESHOLDS = (0.5, 0.8, 0.9, 0.95, 0.97, 0.99, 1.01)
ROOT = Path(__file__).resolve().parents[2]


def split_groups(
    rows: list[dict[str, Any]], validation_fraction: float = 0.2
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validate_rows(rows)
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between zero and one")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("label_status") != "reviewed":
            raise ValueError("Fine-tuning data must have confirmed labels")
        groups[row["group_id"]].append(row)
    buckets: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for key, members in groups.items():
        signature = tuple(sorted({str(r.get("focus", r["kind"])) for r in members}))
        buckets[signature].append(key)
    rng = random.Random(SEED)
    validation_groups: set[str] = set()
    for signature in sorted(buckets):
        keys = sorted(buckets[signature])
        rng.shuffle(keys)
        count = max(1, round(len(keys) * validation_fraction)) if len(keys) > 1 else 0
        validation_groups.update(keys[: min(count, len(keys) - 1)])
    train = [dict(r, split="train") for r in rows if r["group_id"] not in validation_groups]
    validation = [dict(r, split="validation") for r in rows if r["group_id"] in validation_groups]
    validate_rows(train)
    validate_rows(validation)
    if {canonical(r["text"]) for r in train} & {canonical(r["text"]) for r in validation}:
        raise ValueError("Train and validation texts overlap")
    return train, validation


def score_predictions(
    rows: list[dict[str, Any]], predictions: dict[str, dict[str, float]], threshold: float
) -> dict[str, Any]:
    if set(predictions) != {r["id"] for r in rows}:
        raise ValueError("Predictions must match exactly the labelled IDs")
    if any(not math.isfinite(p["toxic"]) or not 0 <= p["toxic"] <= 1 for p in predictions.values()):
        raise ValueError("Invalid toxicity score")
    return measure(rows, {key: p["toxic"] >= threshold for key, p in predictions.items()})


def select_validation_threshold(
    rows: list[dict[str, Any]],
    original: dict[str, dict[str, float]],
    candidate: dict[str, dict[str, float]],
) -> dict[str, Any]:
    validate_rows(rows)
    if any(r.get("split") != "validation" for r in rows):
        raise ValueError("Threshold selection requires validation rows only")
    reference = score_predictions(rows, original, 0.97)
    # Keep false positives at or below the original model on the same validation rows.
    sweep = [{"threshold": t, "metrics": score_predictions(rows, candidate, t)} for t in THRESHOLDS]
    eligible = [item for item in sweep if item["metrics"]["fp"] <= reference["fp"]]
    best = max(
        eligible,
        key=lambda item: (
            item["metrics"]["target_recall"]
            if item["metrics"]["target_total"]
            else item["metrics"]["recall"],
            item["metrics"]["f1"],
            -item["metrics"]["fp"],
            item["threshold"],
        ),
    )
    return {
        "threshold": best["threshold"],
        "metrics": best["metrics"],
        "original_at_097": reference,
        "sweep": sweep,
    }


def build_bundle(regression_pack: Path, output: Path) -> None:
    data = ROOT / "evals/moderation/finetune_v1"
    manifest = json.loads((data / "manifest.json").read_text("utf-8"))
    for name, expected in manifest["dataset_sha256"].items():
        if hashlib.sha256((data / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Dataset hash mismatch: {name}")
    if (
        hashlib.sha256(regression_pack.read_bytes()).hexdigest()
        != manifest["regression_pack_sha256"]
    ):
        raise ValueError("Regression pack differs from the declared snapshot")
    regression = json.loads(regression_pack.read_text("utf-8"))
    validate_pack(regression)
    rows = [
        json.loads(line) for line in (data / "reviewed-dev.jsonl").read_text("utf-8").splitlines()
    ]
    train, validation = split_groups(rows)
    if {r["id"] for r in rows} & {r["id"] for r in regression["rows"]}:
        raise ValueError("Regression IDs overlap training data")
    for name, members in (("train.jsonl", train), ("validation.jsonl", validation)):
        declared = [json.loads(line) for line in (data / name).read_text("utf-8").splitlines()]
        if members != declared:
            raise ValueError(f"Frozen split differs: {name}")
    output.mkdir(parents=True, exist_ok=False)
    bundle = output / "finetune-input.zip"
    with zipfile.ZipFile(bundle, "x", zipfile.ZIP_DEFLATED) as archive:
        for name in ("manifest.json", "train.jsonl", "validation.jsonl"):
            archive.write(data / name, name)
        archive.write(regression_pack, "regression-pack.json")
        archive.writestr("evals/__init__.py", "")
        archive.writestr("evals/moderation/__init__.py", "")
        for name in ("calibrate_visobert.py", "finetune_visobert.py"):
            archive.write(ROOT / "evals/moderation" / name, "evals/moderation/" + name)
        for path in sorted((ROOT / "app").rglob("*.py")):
            archive.write(path, path.relative_to(ROOT).as_posix())
    shutil.copyfile(
        ROOT / "notebooks/tf32-visobert-finetune-colab.ipynb",
        output / "tf32-visobert-finetune-colab.ipynb",
    )
    shutil.copyfile(data / "README.md", output / "HUONG-DAN.md")
    with zipfile.ZipFile(
        output / "tf32-visobert-finetune-ready.zip", "x", zipfile.ZIP_DEFLATED
    ) as archive:
        for name in ("finetune-input.zip", "tf32-visobert-finetune-colab.ipynb", "HUONG-DAN.md"):
            archive.write(output / name, name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regression-pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_bundle(args.regression_pack, args.output)
