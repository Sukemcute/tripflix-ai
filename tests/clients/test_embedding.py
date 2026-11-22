import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from app.clients.embedding import MODEL_ID, PREFIX, REVISION, E5Embedder, verify_bundle

VOCAB = {"[UNK]": 0, "<pad>": 1, "query": 2, ":": 7, "biển": 3, "núi": 4, "cà": 5, "phê": 6}


class Session:
    """Token state = one-hot of its id, so the mean pool shows which tokens were counted."""

    def __init__(self) -> None:
        self.feeds: list[dict[str, np.ndarray]] = []

    def get_inputs(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=n) for n in ("input_ids", "attention_mask")]

    def run(self, _outputs: None, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.feeds.append(feed)
        return [np.eye(len(VOCAB), dtype=np.float32)[feed["input_ids"]]]


def embedder(session: Session) -> E5Embedder:
    tokenizer = Tokenizer(WordLevel(VOCAB, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()  # pyright: ignore[reportAttributeAccessIssue]
    return E5Embedder(session, tokenizer, pad_id=1, batch_size=2)


def test_unit_vectors_in_input_order_with_padding_masked_out() -> None:
    session = Session()
    texts = ["cà phê", "biển", "núi"]

    vectors = embedder(session).embed(texts)

    assert vectors.shape == (3, len(VOCAB))
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-6)
    # Prefix counted, padding (<pad>) never counted.
    assert vectors[1][VOCAB["biển"]] > 0 and vectors[1][VOCAB["query"]] > 0
    assert vectors[1][VOCAB["<pad>"]] == 0 and vectors[2][VOCAB["<pad>"]] == 0
    assert vectors[0][VOCAB["cà"]] > 0 and vectors[2][VOCAB["núi"]] > 0
    # Two batches of two, shortest first; padded rows keep a zero mask.
    assert [f["input_ids"].shape[0] for f in session.feeds] == [2, 1]
    assert session.feeds[0]["attention_mask"].sum() == 6  # "query : biển", "query : núi"
    assert PREFIX == "query: "


def test_empty_input_gives_no_rows() -> None:
    assert embedder(Session()).embed([]).shape[0] == 0


def test_bundle_hash_and_checkpoint_are_checked(tmp_path: Path) -> None:
    for name in ("model.onnx", "tokenizer.json"):
        (tmp_path / name).write_bytes(name.encode())
    files = {
        n: hashlib.sha256((tmp_path / n).read_bytes()).hexdigest()
        for n in ("model.onnx", "tokenizer.json")
    }
    manifest = {"model": MODEL_ID, "revision": REVISION, "pad_id": 1, "files": files}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    assert verify_bundle(tmp_path)["pad_id"] == 1

    (tmp_path / "model.onnx").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sha256"):
        verify_bundle(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest | {"revision": "x"}), "utf-8")
    with pytest.raises(ValueError, match="checkpoint"):
        verify_bundle(tmp_path)
