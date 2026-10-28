"""Local complaint-category classifier: TF-IDF (word 1-2-grams) + Logistic Regression.

Trained offline on labelled *synthetic* complaint texts produced by `app.seed.texts` with a
fixed seed, so it can be rebuilt anywhere with `python -m app.tools.train_models`. Held-out metrics
are measured on synthetic template text and therefore overstate real-world accuracy; the
output is shown as a recommendation only and never changes a case's category by itself.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import joblib
import sklearn

from ..core.clock import now_iso
from ..core.config import get_settings
from ..seed import texts

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _paths():
    d = get_settings().models_dir
    return d / "classifier.joblib", d / "classifier.json"


def train(seed: int | None = None) -> dict[str, Any]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline

    seed = get_settings().seed if seed is None else seed
    data = texts.training_examples(160, seed + 1)
    xs = [t for t, _ in data]
    ys = [c for _, c in data]
    x_tr, x_te, y_tr, y_te = train_test_split(xs, ys, test_size=0.2, random_state=seed, stratify=ys)

    def make():
        return make_pipeline(
            TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2),
            LogisticRegression(max_iter=4000, C=4.0, class_weight="balanced"),
        )

    model = make()
    model.fit(x_tr, y_tr)
    pred = model.predict(x_te)
    per_class = f1_score(y_te, pred, average=None, labels=sorted(set(ys)))
    meta = {
        "kind": "tfidf_logistic_regression",
        "trained_at": now_iso(),
        "seed": seed,
        "sklearn_version": sklearn.__version__,
        "n_examples": len(xs),
        "n_test": len(x_te),
        "macro_f1": round(float(f1_score(y_te, pred, average="macro")), 4),
        "accuracy": round(float(accuracy_score(y_te, pred)), 4),
        "per_class_f1": {c: round(float(v), 3) for c, v in zip(sorted(set(ys)), per_class, strict=True)},
        "labels": sorted(set(ys)),
        "caveat": "Evaluated on held-out synthetic template texts; real-world accuracy is unknown.",
    }
    final = make()
    final.fit(xs, ys)
    model_path, meta_path = _paths()
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, model_path)
    meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    with _lock:
        _cache.clear()
    return meta


def load() -> tuple[Any, dict[str, Any]] | None:
    model_path, meta_path = _paths()
    key = str(model_path)
    with _lock:
        if key in _cache:
            return _cache[key]
    if not model_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("sklearn_version") != sklearn.__version__:
            return None  # pickles are version-specific: retrain instead of risking a bad load
        model = joblib.load(model_path)
    except Exception:
        return None
    with _lock:
        _cache[key] = (model, meta)
    return model, meta


def ensure() -> tuple[Any, dict[str, Any]]:
    loaded = load()
    if loaded is None:
        train()
        loaded = load()
    assert loaded is not None
    return loaded


def status() -> dict[str, Any]:
    loaded = load()
    if loaded is None:
        return {"available": False, "detail": "Model not trained yet (trained automatically on startup)."}
    return {"available": True, **loaded[1]}


def predict(text: str, top: int = 3) -> list[dict[str, Any]]:
    model, _meta = ensure()
    probs = model.predict_proba([text])[0]
    labels = model.classes_
    order = probs.argsort()[::-1][:top]
    return [{"category": str(labels[i]), "probability": round(float(probs[i]), 4)} for i in order]


def predict_many(text_list: list[str]) -> list[tuple[str, float]]:
    model, _meta = ensure()
    probs = model.predict_proba(text_list)
    labels = model.classes_
    out = []
    for row in probs:
        i = int(row.argmax())
        out.append((str(labels[i]), round(float(row[i]), 4)))
    return out
