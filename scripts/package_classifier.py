"""Build the comment classifier bundle the worker loads (summary/comment_classifier.py).

Takes a run folder that has gone through scripts/benchmark_onnx.py export:
  <run>/onnx/model.int8.onnx, <run>/model/tokenizer.json, <run>/model/config.json,
  <run>/thresholds.json (calibrated, keys in model output order)
and writes model.int8.onnx, tokenizer.json, thresholds.json and manifest.json (version,
labels, max_len, pad_id, sha256 per file) into --out. The folder is what goes to the
GitHub Release and into the image; it is never committed.

    uv run python -m scripts.package_classifier --run data/runs/0run10 \\
        --version comment-classifier-v1   # -> app/models/comment_classifier
"""

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.services.summary.comment_classifier import (
    BUNDLE_FILES,
    MANIFEST_FILE,
    MODEL_FILE,
    file_sha256,
    verify_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "models" / "comment_classifier"
MAX_LEN = 128  # same as training and the gold scores


def package(run: Path, out: Path, version: str) -> dict:
    sources = {
        MODEL_FILE: run / "onnx" / MODEL_FILE,
        "tokenizer.json": run / "model" / "tokenizer.json",
        "thresholds.json": run / "thresholds.json",
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, source in sources.items():
        shutil.copyfile(source, out / name)
    thresholds = json.loads(sources["thresholds.json"].read_text("utf-8"))
    config = json.loads((run / "model" / "config.json").read_text("utf-8"))
    manifest = {
        "version": version,
        "source_run": run.name,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "labels": list(thresholds),
        "max_len": MAX_LEN,
        "pad_id": config["pad_token_id"],
        "files": {name: file_sha256(out / name) for name in BUNDLE_FILES},
    }
    (out / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2), "utf-8")
    verify_bundle(out)  # the worker runs the same check at startup
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True, help="run dir after the ONNX export")
    parser.add_argument("--version", required=True, help="also the GitHub Release tag")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    manifest = package(args.run, args.out, args.version)
    print(json.dumps(manifest, indent=2))
    print(f"bundle written to {args.out}")


if __name__ == "__main__":
    main()
