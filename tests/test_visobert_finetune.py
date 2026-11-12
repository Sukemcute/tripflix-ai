import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pytest

from evals.moderation.finetune_visobert import select_validation_threshold, split_groups

FOLDER = Path(__file__).resolve().parents[1] / "evals/moderation/finetune_v1"


def test_frozen_split_is_reproducible_and_keeps_contrastive_pairs_together() -> None:
    rows = [
        json.loads(line) for line in (FOLDER / "reviewed-dev.jsonl").read_text("utf-8").splitlines()
    ]
    train, validation = split_groups(rows)
    reversed_train, reversed_validation = split_groups(list(reversed(rows)))
    assert {r["id"] for r in train} == {r["id"] for r in reversed_train}
    assert {r["id"] for r in validation} == {r["id"] for r in reversed_validation}
    assert {r["id"] for r in train} | {r["id"] for r in validation} == {r["id"] for r in rows}
    assert not {r["group_id"] for r in train} & {r["group_id"] for r in validation}
    paired = defaultdict(set)
    for split, members in (("train", train), ("validation", validation)):
        for row in members:
            paired[row["group_id"]].add(split)
    assert all(len(splits) == 1 for splits in paired.values())
    assert all(r["label_status"] == "reviewed" for r in rows)
    for name, expected in (("train.jsonl", train), ("validation.jsonl", validation)):
        actual = [json.loads(line) for line in (FOLDER / name).read_text("utf-8").splitlines()]
        assert actual == expected


def test_group_split_rejects_unconfirmed_labels() -> None:
    rows = [
        {
            "id": "a",
            "text": "one",
            "kind": "hate",
            "toxic": True,
            "group_id": "g1",
            "label_status": "proposed",
        },
        {
            "id": "b",
            "text": "two",
            "kind": "neutral",
            "toxic": False,
            "group_id": "g2",
            "label_status": "reviewed",
        },
    ]
    with pytest.raises(ValueError, match="confirmed"):
        split_groups(rows)


def test_threshold_is_selected_from_validation_with_original_fp_budget() -> None:
    rows = [
        {
            "id": "a",
            "text": "one",
            "kind": "harassment",
            "toxic": True,
            "group_id": "g1",
            "split": "validation",
        },
        {
            "id": "b",
            "text": "two",
            "kind": "quoted_report",
            "toxic": False,
            "group_id": "g2",
            "split": "validation",
        },
    ]
    original = {"a": {"toxic": 0.98}, "b": {"toxic": 0.99}}
    candidate = {"a": {"toxic": 0.95}, "b": {"toxic": 0.2}}
    selected = select_validation_threshold(rows, original, candidate)
    assert selected["metrics"]["tp"] == 1
    assert selected["metrics"]["fp"] == 0
    rows[0]["split"] = "test"
    with pytest.raises(ValueError, match="validation"):
        select_validation_threshold(rows, original, candidate)


def test_confirmed_manifest_hashes_and_regression_exclusion() -> None:
    manifest = json.loads((FOLDER / "manifest.json").read_text("utf-8"))
    assert manifest["label_status"] == "reviewed"
    assert manifest["review_confirmation"]["confirmed_by"] == "user"
    for name, expected in manifest["dataset_sha256"].items():
        assert hashlib.sha256((FOLDER / name).read_bytes()).hexdigest() == expected
    rows = [
        json.loads(line) for line in (FOLDER / "reviewed-dev.jsonl").read_text("utf-8").splitlines()
    ]
    regression_path = FOLDER.parent / "holdout_v1/reviewed/test.jsonl"
    regression = [json.loads(line) for line in regression_path.read_text("utf-8").splitlines()]
    assert not {r["id"] for r in rows} & {r["id"] for r in regression}
    assert not {r["group_id"] for r in rows} & {r["group_id"] for r in regression}
