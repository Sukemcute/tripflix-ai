import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from evals.moderation.calibrate_visobert import canonical, validate_rows

ROOT = Path(__file__).resolve().parents[1] / "evals/moderation"


def test_new_holdout_matches_manifest_and_has_no_historical_text_or_id_overlap() -> None:
    path = ROOT / "holdout_v1/test.jsonl"
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
    manifest = json.loads((path.parent / "manifest.json").read_text("utf-8"))
    validate_rows(rows)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["dataset_sha256"]
    assert len(rows) == manifest["rows"]
    assert sum(r["toxic"] for r in rows) == manifest["toxic"]
    assert sum(not r["toxic"] for r in rows) == manifest["clean"]
    assert dict(Counter(r["kind"] for r in rows)) == manifest["counts_by_kind"]
    assert len({r["group_id"] for r in rows}) == manifest["groups"]
    assert all(r["label_status"] == "proposed" for r in rows)
    assert manifest["human_review_complete"] is False
    historical = []
    for name in ("vi_3k.jsonl", "vi_30.jsonl", "quality_review/vi_3k.candidate.jsonl"):
        historical.extend(
            json.loads(line)
            for line in (ROOT / name).read_text("utf-8-sig").splitlines()
            if line.strip()
        )
    with (ROOT / "quality_review/review_240.csv").open(encoding="utf-8-sig", newline="") as f:
        dev = list(csv.DictReader(f))
    previous_text = {canonical(r["text"]) for r in historical}
    previous_text.update(canonical(r["Câu sửa"] or r["Câu cần duyệt"]) for r in dev)
    assert not {canonical(r["text"]) for r in rows} & previous_text
    assert not {r["id"] for r in rows} & {r["ID"] for r in dev}


def test_confirmed_holdout_preserves_original_text_labels_and_predictions_identity() -> None:
    folder = ROOT / "holdout_v1"
    original = {
        r["id"]: r for r in map(json.loads, (folder / "test.jsonl").read_text("utf-8").splitlines())
    }
    path = folder / "reviewed/test.jsonl"
    reviewed = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    manifest = json.loads((path.parent / "manifest.json").read_text("utf-8"))
    validate_rows(reviewed)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["dataset_sha256"]
    assert manifest["human_review_complete"] is True
    assert manifest["review_confirmation"]["confirmed_by"] == "user"
    assert manifest["review_confirmation"]["confirmation_after_model_results_shared"] is True
    assert {r["id"] for r in reviewed} == set(original)
    for row in reviewed:
        assert row["label_status"] == "reviewed"
        assert {k: v for k, v in row.items() if k != "label_status"} == {
            k: v for k, v in original[row["id"]].items() if k != "label_status"
        }
