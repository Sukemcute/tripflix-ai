"""Pinned ViHSD ViSoBERT inference on CPU, isolated from the OpenAI decision."""

import asyncio
import hashlib
import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from app.clients.moderation.base import ModerationResult

MODEL_ID = "nd-khoa/vihsd-uit-visobert-v2"
REVISION = "5e8e892f45bf3d52bc3d4c780b6235b65714f07b"
LABELS = ["clean", "offensive", "hate"]
FILES = ("model.onnx", "tokenizer.json")
logger = logging.getLogger(__name__)


def verify_bundle(folder: Path) -> dict[str, Any]:
    manifest = json.loads((folder / "manifest.json").read_text("utf-8"))
    if (manifest["model"], manifest["revision"], manifest["labels"], manifest["max_length"]) != (
        MODEL_ID,
        REVISION,
        LABELS,
        256,
    ):
        raise ValueError("Unexpected ViSoBERT checkpoint or input contract")
    for name in FILES:
        with (folder / name).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["files"][name]:
                raise ValueError(f"ViSoBERT {name}: sha256 mismatch")
    return manifest


class VisobertModeration:
    def __init__(
        self,
        session: Any,
        tokenizer: Any,
        *,
        threshold: float,
        pad_id: int,
        batch_size: int,
        timeout_seconds: float,
        run_options_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.session = session
        self.tokenizer = tokenizer
        self.threshold = threshold
        self.pad_id = pad_id
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds
        self._run_options_factory = run_options_factory
        self.model = f"visobert-vihsd@{REVISION[:12]}"
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="visobert")
        self._busy = threading.BoundedSemaphore(1)

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    async def moderate_batch(self, texts: list[str]) -> list[ModerationResult] | None:
        if not any(t.strip() for t in texts):
            return None
        if not self._busy.acquire(blocking=False):
            logger.warning("moderation.visobert unavailable: busy; OpenAI result used")
            return None
        control = self._run_options_factory() if self._run_options_factory else None
        future = asyncio.get_running_loop().run_in_executor(
            self._executor, self._run, texts, control
        )
        try:
            return await asyncio.wait_for(future, self.timeout_seconds)
        except Exception as error:
            if control is not None:
                control.terminate = True
            logger.warning(
                "moderation.visobert unavailable: %s; OpenAI result used", type(error).__name__
            )
            return None
        except asyncio.CancelledError:
            if control is not None:
                control.terminate = True
            raise

    def _run(self, texts: list[str], control: Any = None) -> list[ModerationResult]:
        try:
            return self.classify(texts, control)
        finally:
            self._busy.release()

    def classify(self, texts: list[str], control: Any = None) -> list[ModerationResult]:
        results = [ModerationResult(False, {}, {}, self.model) for _ in texts]
        order = sorted((i for i, t in enumerate(texts) if t.strip()), key=lambda i: len(texts[i]))
        for offset in range(0, len(order), self.batch_size):
            if control is not None and control.terminate:
                raise TimeoutError("ViSoBERT inference cancelled")
            indices = order[offset : offset + self.batch_size]
            encoded = self.tokenizer.encode_batch([texts[i] for i in indices])
            width = max(len(e.ids) for e in encoded)
            ids = np.full((len(indices), width), self.pad_id, dtype=np.int64)
            masks = np.zeros_like(ids)
            for i, item in enumerate(encoded):
                ids[i, : len(item.ids)] = item.ids
                masks[i, : len(item.ids)] = 1
            feed = {"input_ids": ids, "attention_mask": masks}
            (logits,) = (
                self.session.run(["logits"], feed, control)
                if control is not None
                else self.session.run(["logits"], feed)
            )
            if logits.shape != (len(indices), 3) or not np.isfinite(logits).all():
                raise ValueError("Invalid ViSoBERT logits")
            probabilities = np.exp(logits - logits.max(axis=-1, keepdims=True))
            probabilities /= probabilities.sum(axis=-1, keepdims=True)
            for index, scores in zip(indices, probabilities, strict=True):
                toxic = min(1.0, float(scores[1] + scores[2]))
                flagged = toxic >= self.threshold
                results[index] = ModerationResult(
                    flagged,
                    {"visobert/toxic": flagged},
                    {
                        "visobert/clean": float(scores[0]),
                        "visobert/offensive": float(scores[1]),
                        "visobert/hate": float(scores[2]),
                        "visobert/toxic": toxic,
                    },
                    self.model,
                )
        return results


def load_visobert(
    folder: Path, *, threshold: float, threads: int, batch_size: int, timeout_seconds: float
) -> VisobertModeration:
    import onnxruntime as ort
    from tokenizers import Tokenizer

    manifest = verify_bundle(folder)
    tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=256)
    tokenizer.no_padding()
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    session = ort.InferenceSession(
        str(folder / "model.onnx"), options, providers=["CPUExecutionProvider"]
    )
    if {i.name for i in session.get_inputs()} != {"input_ids", "attention_mask"}:
        raise ValueError("Invalid ViSoBERT ONNX inputs")
    return VisobertModeration(
        session,
        tokenizer,
        threshold=threshold,
        pad_id=manifest["pad_id"],
        batch_size=batch_size,
        timeout_seconds=timeout_seconds,
        run_options_factory=ort.RunOptions,
    )
