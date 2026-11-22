import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evals.moderation.calibrate_visobert import canonical, validate_rows

ROOT = Path(__file__).resolve().parents[1] / "evals/moderation"
FOLDER = ROOT / "dev_hard_negatives_v1"


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8-sig").splitlines() if line.strip()]


def test_dev_additions_preserve_pairs_and_have_no_old_text_or_id_duplicates() -> None:
    rows = read_rows(FOLDER / "dev-additions.jsonl")
    manifest = json.loads((FOLDER / "manifest.json").read_text("utf-8"))
    validate_rows(rows)
    assert len(rows) == manifest["counts"]["additions"]
    assert sum(r["toxic"] for r in rows) == manifest["counts"]["toxic"]
    assert dict(Counter(r["kind"] for r in rows)) == manifest["counts_by_kind"]
    assert all(r["split"] == "dev" and r["label_status"] == "proposed" for r in rows)
    pairs: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        pairs[row["group_id"]].append(row["toxic"])
    assert len(pairs) == manifest["counts"]["pairs"]
    assert all(sorted(labels) == [False, True] for labels in pairs.values())

    previous = []
    for name in (
        "vi_3k.jsonl",
        "vi_30.jsonl",
        "quality_review/vi_3k.candidate.jsonl",
        "holdout_v1/reviewed/test.jsonl",
    ):
        previous.extend(read_rows(ROOT / name))
    previous.extend(read_rows(FOLDER / "dev-expanded.jsonl")[:240])

    def normalize(text: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9 ]", " ", canonical(text)).split())

    normalized = [normalize(r["text"]) for r in rows]
    assert len(set(normalized)) == len(rows)
    assert not set(normalized) & {normalize(r["text"]) for r in previous}
    assert not {r["id"] for r in rows} & {r["id"] for r in previous}


def test_expanded_dev_preserves_reviewed_labels_and_manifest_hashes() -> None:
    rows = read_rows(FOLDER / "dev-expanded.jsonl")
    additions = read_rows(FOLDER / "dev-additions.jsonl")
    manifest = json.loads((FOLDER / "manifest.json").read_text("utf-8"))
    validate_rows(rows)
    assert len(rows) == manifest["counts"]["expanded"]
    assert sum(r["toxic"] for r in rows) == manifest["counts"]["expanded_toxic"]
    assert len({r["group_id"] for r in rows}) == manifest["counts"]["expanded_groups"]
    for name, expected in manifest["dataset_sha256"].items():
        assert hashlib.sha256((FOLDER / name).read_bytes()).hexdigest() == expected
    assert rows[240:] == additions
    with (ROOT / "quality_review/review_240.csv").open(encoding="utf-8-sig", newline="") as f:
        reviewed = {r["ID"]: r for r in csv.DictReader(f)}
    assert {r["id"] for r in rows[:240]} == set(reviewed)
    for row in rows[:240]:
        original = reviewed[row["id"]]
        assert row["text"] == (original["Câu sửa"] or original["Câu cần duyệt"])
        assert row["toxic"] == (original["Nhãn duyệt"] == "toxic")
        assert row["label_status"] == "reviewed"
