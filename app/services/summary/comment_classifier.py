"""Per-comment labels from the trained classifier (run10: ViSoBERT distilled from XLM-R large).

Answers what the summary needs per comment (labelling guide §15-16): did the writer
experience the place (first-hand, or hearsay from someone who went), is it praise or a
complaint, and is it only a reaction to the video. YouTube part of gold: experienced F1
0.768, close to the 560M teacher's 0.780 (BAO_CAO run10). Runs on CPU with onnxruntime and
the tokenizers library, no torch: about 19 comments/s on 2 threads (int8, batch 8).

The bundle (model.int8.onnx, tokenizer.json, thresholds.json, manifest.json) is baked into the
image and never committed (DeepResearch_Luu_tru_model_phan_loai_khi_deploy.md). When it is
missing or broken the loader returns None and the pipeline keeps its rules, so summaries
still run (PRD: an AI failure must not stop the rest).
"""

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

logger = logging.getLogger(__name__)

LABELS: tuple[str, ...] = (
    "first_hand",
    "hearsay",
    "video_reaction",
    "complaint",
    "praise",
    "experienced",
)
MODEL_FILE = "model.int8.onnx"
BUNDLE_FILES = (MODEL_FILE, "tokenizer.json", "thresholds.json")
MANIFEST_FILE = "manifest.json"


@dataclass(frozen=True)
class CommentLabels:
    is_experienced: bool  # first-hand or hearsay: the product's "đã trải nghiệm"
    is_first_hand: bool
    is_hearsay: bool
    is_complaint: bool
    is_praise: bool
    is_video_reaction: bool


class CommentClassifier(Protocol):
    version: str

    def classify(self, pairs: Sequence[tuple[str, str]]) -> list[CommentLabels]:
        """One label set per (comment, parent comment) pair, in input order."""
        ...


def decide_labels(probs: Mapping[str, float], thresholds: Mapping[str, float]) -> CommentLabels:
    """Yes/no per label at the run's thresholds.

    "experienced" follows its own head: that is the score measured on gold. First-hand and
    hearsay then only split it, by whichever clears its threshold by more, so they are never
    both true and never true without experienced.
    """
    margin = {k: probs[k] - thresholds[k] for k in LABELS}
    experienced = margin["experienced"] >= 0
    first_hand = experienced and margin["first_hand"] >= margin["hearsay"]
    return CommentLabels(
        is_experienced=experienced,
        is_first_hand=first_hand,
        is_hearsay=experienced and not first_hand,
        is_complaint=margin["complaint"] >= 0,
        is_praise=margin["praise"] >= 0,
        is_video_reaction=margin["video_reaction"] >= 0,
    )


class OnnxCommentClassifier:
    def __init__(
        self,
        session: Any,  # onnxruntime.InferenceSession
        tokenizer: Any,  # tokenizers.Tokenizer with truncation set
        thresholds: Mapping[str, float],
        labels: Sequence[str],  # model output order
        *,
        version: str,
        pad_id: int,
        batch: int,
    ) -> None:
        self.session = session
        self.tokenizer = tokenizer
        self.thresholds = dict(thresholds)
        self.labels = tuple(labels)
        self.version = version
        self.pad_id = pad_id
        self.batch = batch

    def classify(self, pairs: Sequence[tuple[str, str]]) -> list[CommentLabels]:
        # shortest first so a batch pads to similar lengths (batch 32 unsorted was slower
        # per comment than batch 1, BAO_CAO benchmark)
        order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][0]) + len(pairs[i][1]))
        out: dict[int, CommentLabels] = {}
        for start in range(0, len(order), self.batch):
            part = order[start : start + self.batch]
            ids = [e.ids for e in self.tokenizer.encode_batch([pairs[i] for i in part])]
            (logits,) = self.session.run(["logits"], self._feed(ids))
            for i, row in zip(part, 1 / (1 + np.exp(-logits)), strict=True):
                out[i] = decide_labels(
                    dict(zip(self.labels, row.tolist(), strict=True)), self.thresholds
                )
        return [out[i] for i in range(len(pairs))]

    def _feed(self, ids: list[list[int]]) -> dict[str, np.ndarray]:
        width = max(len(x) for x in ids)
        input_ids = np.full((len(ids), width), self.pad_id, dtype=np.int64)
        mask = np.zeros((len(ids), width), dtype=np.int64)
        for row, x in enumerate(ids):
            input_ids[row, : len(x)] = x
            mask[row, : len(x)] = 1
        return {"input_ids": input_ids, "attention_mask": mask}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_bundle(bundle_dir: Path) -> dict[str, Any]:
    """The manifest, once every file matches its sha256 and the labels match thresholds."""
    manifest = json.loads((bundle_dir / MANIFEST_FILE).read_text("utf-8"))
    for name in BUNDLE_FILES:
        if file_sha256(bundle_dir / name) != manifest["files"][name]:
            raise ValueError(f"{name}: sha256 differs from the manifest")
    thresholds = json.loads((bundle_dir / "thresholds.json").read_text("utf-8"))
    if list(thresholds) != manifest["labels"] or set(thresholds) != set(LABELS):
        raise ValueError(f"labels {list(thresholds)} do not match {manifest['labels']}")
    return manifest


def load_comment_classifier(
    bundle_dir: Path, threads: int, batch: int
) -> OnnxCommentClassifier | None:
    try:
        classifier = _load(bundle_dir, threads, batch)
    except Exception as e:  # any broken bundle means rules, never a worker that cannot start
        logger.error("comment classifier not loaded from %s, rules used instead: %s", bundle_dir, e)
        return None
    logger.info(
        "comment classifier %s loaded, %s threads, batch %s", classifier.version, threads, batch
    )
    return classifier


def _load(bundle_dir: Path, threads: int, batch: int) -> OnnxCommentClassifier:
    import onnxruntime as ort  # imported here: the API process never loads the runtime
    from tokenizers import Tokenizer

    manifest = verify_bundle(bundle_dir)
    tokenizer = Tokenizer.from_file(str(bundle_dir / "tokenizer.json"))
    # same as transformers truncation=True on a pair: cut the longer side first; checked
    # equal on 1,009 of 1,009 gold rows (scripts/benchmark_onnx.py export)
    tokenizer.enable_truncation(max_length=manifest["max_len"], strategy="longest_first")
    tokenizer.no_padding()
    options = ort.SessionOptions()
    # onnxruntime's default is the host's physical cores, not the container's CPU limit
    options.intra_op_num_threads = threads
    session = ort.InferenceSession(
        str(bundle_dir / MODEL_FILE), options, providers=["CPUExecutionProvider"]
    )
    inputs = {i.name for i in session.get_inputs()}
    if not {"input_ids", "attention_mask"} <= inputs:
        raise ValueError(f"model inputs are {sorted(inputs)}")
    thresholds = json.loads((bundle_dir / "thresholds.json").read_text("utf-8"))
    logger.info("comment classifier files: %s", manifest["files"])
    return OnnxCommentClassifier(
        session,
        tokenizer,
        thresholds,
        manifest["labels"],
        version=manifest["version"],
        pad_id=manifest["pad_id"],
        batch=batch,
    )
