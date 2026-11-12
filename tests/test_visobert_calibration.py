import csv
import hashlib
import json
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from evals.moderation import calibrate_visobert as calibration
from evals.moderation.calibrate_visobert import (
    MODEL,
    REVISION,
    calibrate,
    canonical,
    digest,
    evaluate_test,
    prepare,
    validate_pack,
)


def pack(split: str = "dev") -> dict[str, Any]:
    rows = [
        {
            "id": f"{split}-1",
            "text": f"{split} praise",
            "kind": "slang_praise",
            "group_id": f"{split}-base-1",
            "toxic": False,
        },
        {
            "id": f"{split}-2",
            "text": f"{split} insult",
            "kind": "harassment",
            "group_id": f"{split}-base-2",
            "toxic": True,
        },
    ]
    return {
        "split": split,
        "rows": rows,
        "model": MODEL,
        "revision": REVISION,
        "policy_sha256": "policy",
        "rules_sha256": "rules",
        "allowed_domains": [],
        "openai_models": ["omni-moderation-latest"],
        "historical_text_hashes": [],
        "scores": {
            r["id"]: {
                "text_sha256": digest(r["text"]),
                "openai_flagged": False,
                "core_codes": [],
                "clean": 0.01 if r["toxic"] else 0.4,
                "offensive": 0.98 if r["toxic"] else 0.59,
                "hate": 0.01,
            }
            for r in rows
        },
    }


def test_tune_obeys_fpr_budget_and_frozen_test_uses_same_threshold() -> None:
    dev = pack()
    lock = calibrate(dev, 0)
    assert lock["dev_metrics"]["fp"] == 0
    assert lock["dev_metrics"]["tp"] == 1
    test = pack("test")
    result = evaluate_test(dev, test, lock)
    assert result["hybrid"]["tp"] == 1
    assert result["meets_proposed_gate"] is True


@pytest.mark.parametrize("overlap", ["id", "group_id", "text", "historical"])
def test_test_rejects_leakage(overlap: str) -> None:
    dev, test = pack(), pack("test")
    if overlap == "historical":
        dev["historical_text_hashes"] = [digest(canonical(test["rows"][0]["text"]))]
    else:
        test["rows"][0][overlap] = dev["rows"][0][overlap]
        if overlap == "id":
            test["scores"][dev["rows"][0]["id"]] = test["scores"].pop("test-1")
        if overlap == "text":
            test["scores"]["test-1"]["text_sha256"] = digest(test["rows"][0]["text"])
    with pytest.raises(ValueError, match="overlap|reuses"):
        evaluate_test(dev, test, calibrate(dev))


def test_changed_dev_or_rules_cannot_use_existing_lock() -> None:
    dev = pack()
    lock = calibrate(dev)
    changed = deepcopy(dev)
    changed["rows"][0]["kind"] = "complaint"
    with pytest.raises(ValueError, match="original dev"):
        evaluate_test(changed, pack("test"), lock)
    test = pack("test")
    test["rules_sha256"] = "different"
    with pytest.raises(ValueError, match="rules_sha256"):
        evaluate_test(dev, test, lock)


def test_predictions_must_match_text_and_have_valid_probabilities() -> None:
    dev = pack()
    dev["scores"]["dev-1"]["hate"] = float("nan")
    with pytest.raises(ValueError, match="probabilities"):
        validate_pack(dev)
    dev = pack()
    dev["rows"][0]["text"] = "edited text"
    with pytest.raises(ValueError, match="text differs"):
        validate_pack(dev)


def test_core_signal_is_included_in_baseline_and_test_is_not_tuned() -> None:
    dev = pack()
    dev["scores"]["dev-2"]["core_codes"] = ["PROFANITY"]
    assert calibrate(dev)["dev_baseline"]["tp"] == 1
    with pytest.raises(ValueError, match="only on dev"):
        calibrate(pack("test"))


def test_prepare_matches_text_instead_of_reused_review_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "evals/moderation/vi_3k.jsonl"
    original.parent.mkdir(parents=True)
    original.write_text(json.dumps({"id": "old-1", "text": "correct text"}) + "\n", "utf-8")
    policy = tmp_path / "ANNOTATION_POLICY.md"
    policy.write_text("approved", "utf-8")
    review = tmp_path / "review.csv"
    headings = [
        "ID",
        "Quyết định",
        "Nhãn duyệt",
        "Câu sửa",
        "Câu cần duyệt",
        "Nhóm",
        "Câu trước biến đổi",
    ]
    with review.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headings)
        writer.writeheader()
        for key, text, label in [
            ("new-1", "correct text", "toxic"),
            ("old-1", "different text", "clean"),
        ]:
            writer.writerow(
                dict(zip(headings, [key, "Giữ", label, "", text, "harassment", text], strict=True))
            )
    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps({"old-1": {"text": "correct text", "flagged": True, "model": "openai"}}), "utf-8"
    )
    archive = tmp_path / "run.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(
            "visobert-3k.json",
            json.dumps(
                {
                    "model": MODEL,
                    "revision": REVISION,
                    "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                    "predictions": {"old-1": {"clean": 0.1, "offensive": 0.8, "hate": 0.1}},
                }
            ),
        )
    monkeypatch.setattr(calibration, "ROOT", tmp_path)
    monkeypatch.setattr(
        calibration,
        "export_core",
        lambda rows, repo: {"rules_sha256": "rules", "hits": {r["id"]: [] for r in rows}},
    )
    output = tmp_path / "output"
    prepare(review, archive, cache, tmp_path, output)
    dev = json.loads((output / "dev-pack.json").read_text("utf-8"))
    assert dev["scores"]["new-1"]["offensive"] == 0.8
    assert "offensive" not in dev["scores"]["old-1"]
    assert dev["pending_ids"] == ["old-1"]
    with pytest.raises(ValueError, match="probabilities|prediction|clean|OpenAI"):
        # Calibration cannot silently skip the missing prediction.
        calibration.calibrate(dev)
