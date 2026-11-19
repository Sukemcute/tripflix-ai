import threading
import time
from collections.abc import Iterator

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import embedding as embedding_api
from app.api.auth import ServiceTokenVerifier, get_service_verifier
from app.api.embedding import get_embedder
from app.main import app
from tests.test_moderation_api import AUDIENCE, ISSUER, KEY, auth, token


class FakeEmbedder:
    model = "fake-e5"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls.append(texts)
        return np.array([[1.0, 0.0] if "biển" in t else [0.0, 1.0] for t in texts])


@pytest.fixture
def fake() -> Iterator[FakeEmbedder]:
    client = FakeEmbedder()
    app.dependency_overrides[get_service_verifier] = lambda: ServiceTokenVerifier(
        lambda _t: KEY.public_key(), issuer=ISSUER, audience=AUDIENCE, callers=("core-api",)
    )
    app.dependency_overrides[get_embedder] = lambda: client
    yield client
    app.dependency_overrides.clear()


http = TestClient(app)


def test_core_gets_one_vector_per_text_in_order(fake: FakeEmbedder) -> None:
    response = http.post("/embed", json={"texts": ["Tắm biển", "Săn mây"]}, headers=auth())

    assert response.status_code == 200
    assert response.json() == {"model": "fake-e5", "vectors": [[1.0, 0.0], [0.0, 1.0]]}
    assert fake.calls == [["Tắm biển", "Săn mây"]]


@pytest.mark.parametrize(
    "texts", [[], [""], ["x" * (embedding_api.MAX_TEXT_CHARS + 1)], ["a"] * 65]
)
def test_bad_batches_are_rejected_before_the_model(fake: FakeEmbedder, texts: list[str]) -> None:
    assert http.post("/embed", json={"texts": texts}, headers=auth()).status_code == 422
    assert fake.calls == []


def test_only_core_may_call(fake: FakeEmbedder) -> None:
    assert http.post("/embed", json={"texts": ["a"]}).status_code == 401
    other = auth(token(sub="video-worker"))
    assert http.post("/embed", json={"texts": ["a"]}, headers=other).status_code == 403
    assert fake.calls == []


def test_missing_bundle_is_503_after_auth(fake: FakeEmbedder) -> None:
    def missing() -> None:
        raise HTTPException(503, "embedding bundle is unavailable")

    app.dependency_overrides[get_embedder] = missing
    assert http.post("/embed", json={"texts": ["a"]}).status_code == 401
    assert http.post("/embed", json={"texts": ["a"]}, headers=auth()).status_code == 503


def test_two_first_requests_at_once_load_the_model_once(monkeypatch: pytest.MonkeyPatch) -> None:
    loads: list[int] = []

    def slow_load(*_args: object, **_kwargs: object) -> FakeEmbedder:
        loads.append(1)
        time.sleep(0.2)  # both threads arrive while the first load is still running
        return FakeEmbedder()

    monkeypatch.setattr(embedding_api, "load_embedder", slow_load)
    embedding_api._load_embedder.cache_clear()  # pyright: ignore[reportPrivateUsage]
    got: list[object] = []
    threads = [threading.Thread(target=lambda: got.append(get_embedder())) for _ in range(2)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        embedding_api._load_embedder.cache_clear()  # pyright: ignore[reportPrivateUsage]
    assert len(loads) == 1
    assert got[0] is got[1]
