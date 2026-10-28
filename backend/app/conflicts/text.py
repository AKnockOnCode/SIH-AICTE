"""TF-IDF index over complaint texts for duplicate/related similarity (offline, cached)."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from ..core.config import get_settings

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def case_text(row: dict[str, Any]) -> str:
    return f"{row.get('subject') or ''}. {row.get('description') or ''}"


class TextIndex:
    def __init__(self, db):
        from sklearn.feature_extraction.text import TfidfVectorizer

        rows = db.all("SELECT id, subject, description FROM complaints ORDER BY id")
        self.ids = [r["id"] for r in rows]
        self.pos = {cid: i for i, cid in enumerate(self.ids)}
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english", min_df=1)
        self.matrix = self.vectorizer.fit_transform([case_text(r) for r in rows] or ["empty"])

    def vector(self, case: dict[str, Any]):
        i = self.pos.get(case["id"])
        if i is not None:
            return self.matrix[i]
        return self.vectorizer.transform([case_text(case)])

    def similarities(self, case: dict[str, Any], others: list[dict[str, Any]]) -> dict[str, float]:
        if not others:
            return {}
        v = self.vector(case)
        rows = []
        for o in others:
            i = self.pos.get(o["id"])
            rows.append(self.matrix[i] if i is not None else self.vectorizer.transform([case_text(o)]))
        from scipy.sparse import vstack

        sims = (vstack(rows) @ v.T).toarray().ravel()
        return {o["id"]: float(np.clip(s, 0, 1)) for o, s in zip(others, sims, strict=True)}


def get_index(db) -> TextIndex:
    key = str(get_settings().db_path)
    r = db.one("SELECT COUNT(*) n, MAX(id) m FROM complaints")
    stamp = f"{r['n']}|{r['m']}"
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    idx = TextIndex(db)
    with _lock:
        _cache[key] = (stamp, idx)
    return idx
