import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from app.services.summary.comment_classifier import (
    BUNDLE_FILES,
    LABELS,
    MANIFEST_FILE,
    CommentLabels,
    OnnxCommentClassifier,
    decide_labels,
    file_sha256,
    load_comment_classifier,
    verify_bundle,
)

THRESHOLDS = dict.fromkeys(LABELS, 0.5)
REAL_BUNDLE = Path(__file__).resolve().parents[2] / "app" / "models" / "comment_classifier"


def probs(**values: float) -> dict[str, float]:
    return dict.fromkeys(LABELS, 0.0) | values


def test_first_hand_and_hearsay_split_experienced_by_the_larger_margin() -> None:
    both = decide_labels(probs(experienced=0.9, first_hand=0.6, hearsay=0.8), THRESHOLDS)
    neither = decide_labels(probs(experienced=0.9, first_hand=0.2, hearsay=0.1), THRESHOLDS)

    assert both.is_hearsay and not both.is_first_hand
    assert neither.is_first_hand and not neither.is_hearsay  # experienced always has a kind


def test_no_experience_means_neither_first_hand_nor_hearsay() -> None:
    labels = decide_labels(probs(experienced=0.4, first_hand=0.9, complaint=0.7), THRESHOLDS)

    assert labels == CommentLabels(
        is_experienced=False,
        is_first_hand=False,
        is_hearsay=False,
        is_complaint=True,
        is_praise=False,
        is_video_reaction=False,
    )


@dataclass
class FakeEncoding:
    ids: list[int]


@dataclass
class FakeTokenizer:
    def encode_batch(self, pairs: list[tuple[str, str]]) -> list[FakeEncoding]:
        return [FakeEncoding(list(range(2, 2 + len(text)))) for text, _ in pairs]


@dataclass
class FakeSession:
    """Complaint logit = number of real tokens - 3, so longer comments complain."""

    batches: list[np.ndarray] = field(default_factory=list)

    def run(self, outputs: list[str], feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.batches.append(feed["input_ids"])
        logits = np.full((len(feed["input_ids"]), len(LABELS)), -5.0)
        logits[:, LABELS.index("complaint")] = feed["attention_mask"].sum(axis=1) - 3
        return [logits]


def test_batches_are_length_sorted_and_answers_come_back_in_input_order() -> None:
    session = FakeSession()
    classifier = OnnxCommentClassifier(
        session, FakeTokenizer(), THRESHOLDS, LABELS, version="t", pad_id=1, batch=2
    )

    found = classifier.classify([("dai lam", ""), ("a", ""), ("bb", ""), ("dai hon nua", "")])

    assert [f.is_complaint for f in found] == [True, False, False, True]
    assert [b.shape for b in session.batches] == [(2, 2), (2, 11)]  # short ones padded together
    assert session.batches[0][0].tolist() == [2, 1]  # pad_id fills the shorter row


def make_bundle(path: Path) -> Path:
    path.mkdir()
    (path / "model.int8.onnx").write_bytes(b"not a real model")
    (path / "tokenizer.json").write_text("{}", "utf-8")
    (path / "thresholds.json").write_text(json.dumps(THRESHOLDS), "utf-8")
    manifest = {
        "version": "t1",
        "labels": list(LABELS),
        "max_len": 128,
        "pad_id": 1,
        "files": {name: file_sha256(path / name) for name in BUNDLE_FILES},
    }
    (path / MANIFEST_FILE).write_text(json.dumps(manifest), "utf-8")
    return path


def test_bundle_check_catches_a_changed_file_and_mismatched_labels(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path / "b")
    assert verify_bundle(bundle)["version"] == "t1"

    (bundle / "tokenizer.json").write_text('{"x": 1}', "utf-8")
    with pytest.raises(ValueError, match="sha256"):
        verify_bundle(bundle)

    other = make_bundle(tmp_path / "c")
    manifest = json.loads((other / MANIFEST_FILE).read_text("utf-8"))
    manifest["labels"] = list(reversed(LABELS))
    (other / MANIFEST_FILE).write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(ValueError, match="labels"):
        verify_bundle(other)


def test_missing_or_broken_bundle_falls_back_to_rules(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert load_comment_classifier(tmp_path / "missing", 2, 8) is None
    assert load_comment_classifier(make_bundle(tmp_path / "broken"), 2, 8) is None  # bad model
    assert "rules used instead" in caplog.text


@pytest.mark.skipif(
    not (REAL_BUNDLE / MANIFEST_FILE).is_file(),
    reason="bundle not fetched (scripts/fetch_classifier.py)",
)
def test_real_bundle_tells_first_hand_hearsay_and_video_reactions() -> None:
    classifier = load_comment_classifier(REAL_BUNDLE, 2, 8)
    assert classifier is not None

    own, heard, reaction = classifier.classify(
        [
            ("Mình ở đây 3 đêm rồi, phòng bẩn, nhân viên thái độ", ""),
            ("Bạn mình đi về kể đồ ăn đắt mà dở lắm", ""),
            ("Anh Cường đẹp trai quá", ""),
        ]
    )

    assert own.is_first_hand and own.is_complaint
    assert heard.is_hearsay and heard.is_complaint
    assert reaction.is_video_reaction and not reaction.is_experienced
