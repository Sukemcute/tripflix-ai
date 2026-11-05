"""Train the complaint classifier and export it to app/models/ (BAO_CAO "So sánh cách gán nhãn").

TF-IDF (word 1-2 grams + char_wb 2-5 grams, 10k features each) + Logistic Regression, the
best F1 of the measured options (0.68 vs 0.21 for the complaint lexicon). scikit-learn is
needed only here, never by the service: run with

    uv run --with scikit-learn python scripts/train_complaint_model.py

Training data: data/generated (TripAdvisor VN reviews, git-ignored); label = the review has
at least one negative aspect. Reviews used by data/generated/eval_300.jsonl are held out.
The script checks that app/services/summary/complaint_model.py scores exactly like
scikit-learn before it writes the file.
"""

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline, make_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.summary import complaint_model  # noqa: E402  (needs ROOT on sys.path)

DATA = ROOT / "data" / "generated"
VERSION = 1
SEED = 20261105
MAX_FEATURES = 10_000  # per vectorizer: F1 0.681 vs 0.684 with all 67,595 features


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    held_out = {
        r["source_id"]
        for line in (DATA / "eval_300.jsonl").read_text(encoding="utf-8").splitlines()
        if (r := json.loads(line))["source_id"]
    }
    labels = {}
    for line in (DATA / "labels.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        labels[r["comment_id"]] = any(v == "negative" for v in r["aspects"].values())
    rows = [
        json.loads(line)
        for line in (DATA / "comments.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows = [r for r in rows if r["comment_id"] not in held_out]
    texts = [complaint_model.prepare(r["body"]) for r in rows]
    y = np.array([labels[r["comment_id"]] for r in rows], int)

    word = TfidfVectorizer(
        **complaint_model.WORD_PARAMS, min_df=2, sublinear_tf=True, max_features=MAX_FEATURES
    )
    char = TfidfVectorizer(
        **complaint_model.CHAR_PARAMS, min_df=2, sublinear_tf=True, max_features=MAX_FEATURES
    )
    pipe = make_pipeline(
        make_union(word, char), LogisticRegression(C=4, class_weight="balanced", max_iter=2000)
    )

    pred = cross_val_predict(pipe, texts, y, cv=StratifiedKFold(5, shuffle=True, random_state=SEED))
    p, r, f, _ = precision_recall_fscore_support(y, pred, average="binary")
    print(
        f"train {len(y)} reviews ({y.sum()} complaints), held out {len(held_out)}; "
        f"5-fold CV P {p:.2f} R {r:.2f} F1 {f:.2f}"
    )

    pipe.fit(texts, y)
    clf = pipe[-1]
    coef = clf.coef_[0]
    model = {
        "name": "complaint",
        "version": VERSION,
        "threshold": 0.5,
        "intercept": float(clf.intercept_[0]),
        "word": _export(word, coef[: len(word.vocabulary_)]),
        "char": _export(char, coef[len(word.vocabulary_) :]),
        "trained_on": f"{len(y)} TripAdvisor VN reviews, label: >=1 negative aspect; CV F1 {f:.3f}",
    }
    out = ROOT / "app" / "models" / f"complaint.v{VERSION}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    complaint_model.load.cache_clear()
    ours = np.array([complaint_model.predict_probability(r["body"]) for r in rows])
    theirs = pipe.predict_proba(texts)[:, 1]
    gap = float(np.abs(ours - theirs).max())
    assert gap < 1e-9, f"pure-Python scoring differs from scikit-learn by {gap}"
    print(
        f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB); parity max gap {gap:.1e}"
    )


def _export(vectorizer: TfidfVectorizer, coef: np.ndarray) -> dict[str, list[float]]:
    """term -> [idf, weight]; terms are stored, not indexes, so the file is self-contained."""
    return {
        term: [float(vectorizer.idf_[i]), float(coef[i])]
        for term, i in vectorizer.vocabulary_.items()
    }


if __name__ == "__main__":
    main()
