"""Pinned multilingual-e5-small text embeddings on CPU for core's recommend job (TF28).

Core's discovery job embeds post captions and its own bin descriptions, then compares them by
cosine; this service only turns text into unit vectors and knows nothing about bins.
"""

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import numpy as np

MODEL_ID = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
FILES = ("model.onnx", "tokenizer.json")
MAX_TOKENS = 256
PREFIX = "query: "  # e5 symmetric-task prefix, same as the TF28 caption experiment


def verify_bundle(folder: Path) -> dict[str, Any]:
    manifest = json.loads((folder / "manifest.json").read_text("utf-8"))
    if (manifest["model"], manifest["revision"]) != (MODEL_ID, REVISION):
        raise ValueError("Unexpected embedding checkpoint")
    for name in FILES:
        with (folder / name).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["files"][name]:
                raise ValueError(f"Embedding {name}: sha256 mismatch")
    return manifest


class E5Embedder:
    def __init__(self, session: Any, tokenizer: Any, *, pad_id: int, batch_size: int) -> None:
        self.session = session
        self.tokenizer = tokenizer
        self.pad_id = pad_id
        self.batch_size = batch_size
        self.inputs = {i.name for i in session.get_inputs()}
        self.model = f"multilingual-e5-small@{REVISION[:12]}"
        # One inference at a time: the job calls in batches, parallel runs only fight for CPU.
        self._lock = threading.Lock()

    def embed(self, texts: list[str]) -> np.ndarray:
        """Unit vectors, one row per text, in input order."""
        with self._lock:
            out = np.zeros((len(texts), 0), dtype=np.float32)
            rows: dict[int, np.ndarray] = {}
            order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
            for offset in range(0, len(order), self.batch_size):
                indices = order[offset : offset + self.batch_size]
                encoded = self.tokenizer.encode_batch([PREFIX + texts[i] for i in indices])
                width = max(len(e.ids) for e in encoded)
                ids = np.full((len(indices), width), self.pad_id, dtype=np.int64)
                masks = np.zeros_like(ids)
                for i, item in enumerate(encoded):
                    ids[i, : len(item.ids)] = item.ids
                    masks[i, : len(item.ids)] = 1
                feed = {"input_ids": ids, "attention_mask": masks}
                if "token_type_ids" in self.inputs:
                    feed["token_type_ids"] = np.zeros_like(ids)
                hidden = self.session.run(None, feed)[0]
                # e5 = mean of token states over the mask, then L2 norm.
                mask = masks[..., None].astype(np.float32)
                pooled = (hidden * mask).sum(axis=1) / mask.sum(axis=1)
                pooled /= np.linalg.norm(pooled, axis=1, keepdims=True)
                if not np.isfinite(pooled).all():
                    raise ValueError("Invalid embedding output")
                rows.update(zip(indices, pooled, strict=True))
            return np.stack([rows[i] for i in range(len(texts))]) if texts else out


def load_embedder(folder: Path, *, threads: int, batch_size: int) -> E5Embedder:
    import onnxruntime as ort
    from tokenizers import Tokenizer

    manifest = verify_bundle(folder)
    tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=MAX_TOKENS)
    tokenizer.no_padding()
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    # Shared 2 vCPU / 8 GB box: arena off keeps RSS flat (~440 MB vs ~600 MB after a long
    # batch) for ~93 instead of ~130 captions/s on one thread.
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    session = ort.InferenceSession(
        str(folder / "model.onnx"), options, providers=["CPUExecutionProvider"]
    )
    return E5Embedder(session, tokenizer, pad_id=manifest["pad_id"], batch_size=batch_size)
