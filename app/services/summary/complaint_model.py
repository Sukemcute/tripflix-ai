"""Does a comment complain? TF-IDF + logistic regression, scored in pure Python.

Replaces the complaint lexicon for selection (BAO_CAO "So sánh cách gán nhãn"): on 3,058
labelled reviews, F1 0.68 against 0.21 for the lexicon, at about 1 ms per comment and no
API cost. Trained by scripts/train_complaint_model.py; the service only reads the JSON, so
it needs no scikit-learn. Feature extraction mirrors scikit-learn's TfidfVectorizer
(word 1-2 grams, char_wb 2-5 grams, sublinear tf, L2 per block); the training script
checks the scores match before writing the file.
Limit: trained on hotel reviews (partly machine-translated), not on video comments.
"""

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from app.services.summary.vi_text import clean_text

MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
WORD_PARAMS: dict[str, Any] = {"ngram_range": (1, 2)}
CHAR_PARAMS: dict[str, Any] = {"analyzer": "char_wb", "ngram_range": (2, 5)}
_TOKEN = re.compile(r"(?u)\b\w\w+\b")  # scikit-learn's default token_pattern
_FILE_NAME = re.compile(r"^complaint\.v(?P<version>\d+)\.json$")


@dataclass(frozen=True)
class ComplaintModel:
    version: int
    threshold: float
    intercept: float
    word: dict[str, tuple[float, float]]  # term -> (idf, weight)
    char: dict[str, tuple[float, float]]


@cache
def load() -> ComplaintModel:
    """Latest app/models/complaint.v<N>.json."""
    files = {
        int(m["version"]): p
        for p in MODEL_DIR.glob("complaint.v*.json")
        if (m := _FILE_NAME.match(p.name))
    }
    if not files:
        raise FileNotFoundError(f"no complaint model in {MODEL_DIR}")
    data = json.loads(files[max(files)].read_text(encoding="utf-8"))
    return ComplaintModel(
        version=data["version"],
        threshold=data["threshold"],
        intercept=data["intercept"],
        word={t: (v[0], v[1]) for t, v in data["word"].items()},
        char={t: (v[0], v[1]) for t, v in data["char"].items()},
    )


def prepare(body: str) -> str:
    """Model input: raw text, lowercased. Diacritics kept: 2 F1 points better than norm."""
    return clean_text(body).lower()


@lru_cache(maxsize=4096)  # selection scores each comment and its sentences; reruns repeat
def predict_probability(body: str) -> float:
    model = load()
    text = prepare(body)
    score = (
        model.intercept
        + _block(_word_ngrams(text), model.word)
        + _block(_char_ngrams(text), model.char)
    )
    return 1 / (1 + math.exp(-score))


def is_complaint(body: str) -> bool:
    return predict_probability(body) >= load().threshold


def _block(grams: list[str], vocab: dict[str, tuple[float, float]]) -> float:
    """Dot product of one L2-normalized sublinear TF-IDF block with its weights."""
    square_sum = dot = 0.0
    for gram, n in Counter(grams).items():
        entry = vocab.get(gram)
        if entry is not None:
            value = (1 + math.log(n)) * entry[0]
            square_sum += value * value
            dot += value * entry[1]
    return dot / math.sqrt(square_sum) if square_sum else 0.0


def _word_ngrams(text: str) -> list[str]:
    tokens = _TOKEN.findall(text)
    return tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False)]


def _char_ngrams(text: str) -> list[str]:
    """scikit-learn's char_wb: n-grams inside each space-padded word."""
    low, high = CHAR_PARAMS["ngram_range"]
    grams: list[str] = []
    for word in text.split():
        padded = f" {word} "
        size = len(padded)
        for n in range(low, high + 1):
            if size <= n:  # word no longer than n: counted once, then stop (as sklearn)
                grams.append(padded)
                break
            grams += [padded[i : i + n] for i in range(size - n + 1)]
    return grams
