import asyncio
import threading
from pathlib import Path

import numpy as np
import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel

from app.clients.moderation.visobert import VisobertModeration, verify_bundle


class Session:
    def __init__(self) -> None:
        self.feeds: list[dict[str, np.ndarray]] = []

    def run(self, _outputs: list[str], feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.feeds.append(feed)
        return [np.tile(np.array([[-10.0, 10.0, -10.0]]), (len(feed["input_ids"]), 1))]


def local(session: Session | None = None) -> VisobertModeration:
    tokenizer = Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    return VisobertModeration(
        session or Session(), tokenizer, threshold=0.97, pad_id=1, batch_size=2, timeout_seconds=0.1
    )


def test_softmax_namespaced_scores_and_image_only_texts() -> None:
    session = Session()
    client = local(session)
    try:
        results = client.classify(["", "short", "longer text"])
        assert results[0].flagged is False and results[0].scores == {}
        assert results[1].flagged is True
        assert results[1].categories == {"visobert/toxic": True}
        assert 0 <= results[1].scores["visobert/toxic"] <= 1
        assert all(f["input_ids"].dtype == np.int64 for f in session.feeds)
    finally:
        client.close()


def test_corrupt_logits_are_rejected_and_async_failure_is_isolated() -> None:
    class Broken(Session):
        def run(self, _outputs: list[str], feed: dict[str, np.ndarray]) -> list[np.ndarray]:
            return [np.full((len(feed["input_ids"]), 3), np.nan)]

    client = local(Broken())
    try:
        with pytest.raises(ValueError, match="logits"):
            client.classify(["text"])
        assert asyncio.run(client.moderate_batch(["text"])) is None
        assert asyncio.run(client.moderate_batch(["again"])) is None
    finally:
        client.close()


def test_timed_out_inference_remains_bounded_until_worker_exits() -> None:
    entered, release = threading.Event(), threading.Event()

    class Slow(Session):
        def run(self, outputs: list[str], feed: dict[str, np.ndarray]) -> list[np.ndarray]:
            entered.set()
            release.wait(5)
            return super().run(outputs, feed)

    client = local(Slow())
    try:
        assert asyncio.run(client.moderate_batch(["first"])) is None
        assert entered.is_set()
        # No second ONNX job gets queued while the timed-out worker still runs.
        assert asyncio.run(client.moderate_batch(["second"])) is None
    finally:
        release.set()
        client.close()


def test_missing_bundle_is_explicit_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify_bundle(tmp_path)
