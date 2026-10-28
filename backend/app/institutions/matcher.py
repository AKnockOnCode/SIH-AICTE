"""Institution entity resolution: canonicalisation, candidate generation, calibrated scoring.

Layers (all offline):
1. Exact identifiers — AICTE Permanent ID, officer-confirmed aliases.
2. Candidate generation — TF-IDF over character n-grams of canonical names and aliases
   (plus acronym look-up, e.g. "S.I.E.T" -> Sankalp Institute of Engineering & Technology).
3. Pairwise features — token-set / token-sort / partial ratios (RapidFuzz-style), TF-IDF
   cosine, token coverage, acronym, pincode, district/state agreement or conflict.
4. Scoring — a logistic-regression model trained on synthetic labelled pairs generated from
   the current Institution Master (spelling errors, abbreviations, acronyms, campus
   suffixes, former names, wrong/missing address hints). Its output is a *calibrated
   confidence on synthetic validation data*, not a certainty; Brier score and reliability
   are stored with the model. A transparent weighted fallback is used if no model exists.
5. Human feedback — officer confirmations become aliases (exact matches next time);
   rejections are stored and heavily down-weight that pairing in later searches.

Low-confidence matches are never linked silently: AUTO_LINK requires the configurable
auto-link threshold *and* a clear margin over the runner-up; otherwise REVIEW or NO_MATCH.
"""

from __future__ import annotations

import json
import math
import random
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..core.config import get_settings
from ..core.util import clamp
from ..scoring.rules import get_settings_block
from .fuzzy import ratio, token_sort_ratio
from .normalize import (
    acronym,
    canonical_tokens,
    compact,
    fold,
    location_words,
    normalize_name,
    normalize_permanent_id,
    normalize_pincode,
)

FEATURES = [
    "tfidf", "token_sort", "idf_coverage", "query_idf_coverage", "brand_match", "alias_exact",
    "pincode", "pincode_conflict", "location", "location_conflict", "state", "permanent_id", "permanent_id_conflict",
]
# Transparent fallback weights (used only when no trained model is available).
FALLBACK = {"intercept": -9.0, "tfidf": 4.0, "token_sort": 2.0, "idf_coverage": 3.0, "query_idf_coverage": 1.0,
            "brand_match": 2.5, "alias_exact": 3.0, "pincode": 2.0, "pincode_conflict": -2.0, "location": 1.5,
            "location_conflict": -2.0, "state": 0.8, "permanent_id": 6.0, "permanent_id_conflict": -4.0}

_lock = threading.Lock()
_index_cache: dict[str, Any] = {}
_model_cache: dict[str, Any] = {}


@dataclass
class Query:
    raw_name: str
    raw_address: str | None = None
    raw_pincode: str | None = None
    raw_state: str | None = None
    raw_permanent_id: str | None = None

    @property
    def norm(self) -> str:
        return normalize_name(self.raw_name)


# ----------------------------------------------------------------------------- index
def _stamp(db) -> str:
    a = db.one("SELECT COUNT(*) n, MAX(updated_at) u FROM institutions")
    b = db.one("SELECT COUNT(*) n, MAX(id) m FROM institution_aliases")
    c = db.one("SELECT COUNT(*) n FROM match_feedback")
    return f"{a['n']}|{a['u']}|{b['n']}|{b['m']}|{c['n']}"


class MatchIndex:
    def __init__(self, db):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.insts: dict[str, dict[str, Any]] = {}
        for r in db.all("SELECT id, permanent_id, name, name_norm, district, city, state, pincode, region_code "
                        "FROM institutions WHERE status != 'MERGED'"):
            r["acronym"] = acronym(r["name"])
            r["tokens"] = set(canonical_tokens(r["name"]))
            r["district_l"] = fold(r["district"] or "")
            r["state_l"] = fold(r["state"] or "")
            self.insts[r["id"]] = r
        self.strings: list[tuple[str, str, str]] = []  # (inst_id, norm, kind)
        for inst in self.insts.values():
            self.strings.append((inst["id"], inst["name_norm"], "NAME"))
        self.confirmed: dict[str, str] = {}
        for a in db.all("SELECT institution_id, alias_norm, alias_type FROM institution_aliases"):
            if a["institution_id"] in self.insts and a["alias_norm"]:
                self.strings.append((a["institution_id"], a["alias_norm"], a["alias_type"]))
                if a["alias_type"] in ("CONFIRMED_MATCH", "IMPORTED"):
                    self.confirmed[a["alias_norm"]] = a["institution_id"]
        self.rejected: set[tuple[str, str]] = {
            (r["raw_norm"], r["institution_id"])
            for r in db.all("SELECT raw_norm, institution_id FROM match_feedback WHERE decision = 'REJECT'")
        }
        self.by_pid = {normalize_permanent_id(i["permanent_id"]): i["id"] for i in self.insts.values() if i["permanent_id"]}
        self.by_acronym: dict[str, list[str]] = {}
        for i in self.insts.values():
            if len(i["acronym"]) >= 3:
                self.by_acronym.setdefault(i["acronym"], []).append(i["id"])
        # Word-level IDF over canonical names/aliases: distinctive "brand" words weigh more than
        # generic ones such as "institute" or "technology".
        df: dict[str, int] = {}
        for _iid, string, _k in self.strings:
            for tok in set(string.split()):
                df[tok] = df.get(tok, 0) + 1
        n_docs = max(1, len(self.strings))
        self.idf = {t: math.log((1 + n_docs) / (1 + c)) + 1.0 for t, c in df.items()}
        self.default_idf = math.log(1 + n_docs) + 1.0
        corpus = [s for _, s, _ in self.strings] or ["empty"]
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform(corpus)
        self.locations = location_words()
        self.known_states = {fold(s) for s in {i["state"] for i in self.insts.values()}}

    def tfidf_scores(self, q_norm: str) -> dict[str, float]:
        if not q_norm:
            return {}
        vec = self.vectorizer.transform([q_norm])
        sims = (self.matrix @ vec.T).toarray().ravel()
        best: dict[str, float] = {}
        for (iid, _s, _k), score in zip(self.strings, sims, strict=False):
            if score > best.get(iid, 0.0):
                best[iid] = float(score)
        return best


def get_index(db) -> MatchIndex:
    key = str(get_settings().db_path)
    stamp = _stamp(db)
    with _lock:
        hit = _index_cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    idx = MatchIndex(db)
    with _lock:
        _index_cache[key] = (stamp, idx)
    return idx


def invalidate() -> None:
    with _lock:
        _index_cache.clear()


# ----------------------------------------------------------------------------- features
def _location_signals(q: Query, inst: dict[str, Any], idx: MatchIndex) -> tuple[float, float, float]:
    text = fold(" ".join(x for x in (q.raw_name, q.raw_address or "", q.raw_state or "") if x))
    words = set(text.split())
    district_words = set(inst["district_l"].split())
    state_words = set(inst["state_l"].split())
    location = 1.0 if district_words and district_words <= words else 0.0
    state = 1.0 if state_words and state_words <= words else 0.0
    mentioned = {w for w in words if w in idx.locations}
    conflict = 0.0
    if mentioned and not location and not state:
        own = district_words | state_words
        if not (mentioned & own):
            conflict = 1.0
    return location, conflict, state


def _token_match(tok: str, others: list[str]) -> float:
    """Best fuzzy agreement of one token against a token list (tolerates typos like prerna/prerana)."""
    best = 0.0
    for o in others:
        if o == tok:
            return 1.0
        if abs(len(o) - len(tok)) <= 3 and min(len(o), len(tok)) >= 4:
            best = max(best, ratio(tok, o) / 100)
    return best if best >= 0.8 else 0.0


def _idf_cover(src: list[str], dst: list[str], idx: MatchIndex) -> float:
    """Share of `src`'s IDF mass whose tokens appear (fuzzily) in `dst`."""
    if not src:
        return 0.0
    total = sum(idx.idf.get(t, idx.default_idf) for t in src)
    hit = sum(idx.idf.get(t, idx.default_idf) * _token_match(t, dst) for t in src)
    return hit / total if total else 0.0


def features(q: Query, iid: str, idx: MatchIndex, tfidf: float) -> dict[str, float]:
    inst = idx.insts[iid]
    qn = q.norm
    q_tokens = qn.split()
    strings = [s for (i, s, _k) in idx.strings if i == iid]
    tsort = max((token_sort_ratio(qn, s) for s in strings), default=0.0) / 100
    cov = qcov = brand = 0.0
    for s in strings:
        st = s.split()
        if not st or not q_tokens:
            continue
        cov = max(cov, _idf_cover(st, q_tokens, idx))
        qcov = max(qcov, _idf_cover(q_tokens, st, idx))
        distinctive = max(st, key=lambda t: idx.idf.get(t, idx.default_idf))
        brand = max(brand, _token_match(distinctive, q_tokens))
    alias_exact = 1.0 if qn and qn in strings else 0.0
    pin = normalize_pincode(q.raw_pincode)
    pincode = pin_conf = 0.0
    if pin and inst["pincode"]:
        if pin == inst["pincode"]:
            pincode = 1.0
        elif pin[:3] == inst["pincode"][:3]:
            pincode = 0.5
        else:
            pin_conf = 1.0
    location, loc_conf, state = _location_signals(q, inst, idx)
    pid_q = normalize_permanent_id(q.raw_permanent_id)
    pid = pid_conf = 0.0
    if pid_q:
        inst_pid = normalize_permanent_id(inst["permanent_id"])
        if inst_pid and pid_q == inst_pid:
            pid = 1.0
        elif inst_pid:
            pid_conf = 1.0
    return {"tfidf": tfidf, "token_sort": tsort, "idf_coverage": cov, "query_idf_coverage": qcov,
            "brand_match": brand, "alias_exact": alias_exact, "pincode": pincode, "pincode_conflict": pin_conf,
            "location": location, "location_conflict": loc_conf, "state": state, "permanent_id": pid,
            "permanent_id_conflict": pid_conf}


def acronym_hits(q: Query, idx: MatchIndex) -> dict[str, float]:
    """Acronym rule: 'S.I.E.T Bhopal' -> institutions whose initials are SIET.

    Acronyms are inherently ambiguous, so this rule never auto-links on its own:
    unique acronym + matching district -> 0.80; unique acronym -> 0.65; shared acronym ->
    0.45 for those in the mentioned district, 0.30 otherwise.
    """
    keys = {compact(q.raw_name.split(",")[0]), compact(q.raw_name.split()[0]) if q.raw_name.split() else ""}
    hits: list[str] = []
    for key in keys:
        if 3 <= len(key) <= 7:
            hits.extend(idx.by_acronym.get(key, []))
    hits = sorted(set(hits))
    if not hits:
        return {}
    text = fold(" ".join(x for x in (q.raw_name, q.raw_address or "") if x))
    words = set(text.split())
    located = [h for h in hits if set(idx.insts[h]["district_l"].split()) <= words]
    out: dict[str, float] = {}
    for h in hits:
        if len(hits) == 1:
            out[h] = 0.80 if h in located else 0.65
        elif len(located) == 1 and h in located:
            out[h] = 0.80
        else:
            out[h] = 0.45 if h in located else 0.30
    return out


def _vector(f: dict[str, float]) -> list[float]:
    return [f[k] for k in FEATURES]


# ----------------------------------------------------------------------------- model
def _model_path():
    return get_settings().models_dir / "matcher.json"


def load_model() -> dict[str, Any] | None:
    path = _model_path()
    key = str(path)
    if key in _model_cache:
        return _model_cache[key]
    if not path.exists():
        return None
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
        if model.get("features") != FEATURES:
            return None
    except (OSError, ValueError):
        return None
    _model_cache[key] = model
    return model


def _probability(vec: list[float], model: dict[str, Any] | None) -> tuple[float, str]:
    if model:
        z = model["intercept"] + sum(c * v for c, v in zip(model["coef"], vec, strict=True))
        source = "MODEL"
    else:
        z = FALLBACK["intercept"] + sum(FALLBACK[k] * v for k, v in zip(FEATURES, vec, strict=True))
        source = "FALLBACK_WEIGHTS"
    return 1.0 / (1.0 + math.exp(-clamp(z, -40, 40))), source


def explain(f: dict[str, float], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    if f["permanent_id"]:
        out.append({"factor": "permanent_id", "label": "AICTE Permanent ID matches", "effect": "+"})
    if f["permanent_id_conflict"]:
        out.append({"factor": "permanent_id_conflict", "label": "Permanent ID given but differs", "effect": "-"})
    out.append({"factor": "name", "label": f"Name similarity: n-gram {round(f['tfidf'] * 100)}%, "
                                           f"word order-insensitive {round(f['token_sort'] * 100)}%",
                "effect": "+" if max(f["tfidf"], f["token_sort"]) >= 0.75 else "~"})
    out.append({"factor": "coverage", "label": f"{round(f['idf_coverage'] * 100)}% of the institution's distinctive "
                                               f"name words present", "effect": "+" if f["idf_coverage"] >= 0.7 else "-"})
    if f["brand_match"]:
        out.append({"factor": "brand", "label": "Distinctive name word matches (typos tolerated)", "effect": "+"})
    if f["alias_exact"]:
        out.append({"factor": "alias", "label": "Exact match with a known alias / canonical name", "effect": "+"})
    if f["pincode"] == 1:
        out.append({"factor": "pincode", "label": "Pincode matches", "effect": "+"})
    elif f["pincode"] == 0.5:
        out.append({"factor": "pincode", "label": "Pincode area (first 3 digits) matches", "effect": "+"})
    if f["pincode_conflict"]:
        out.append({"factor": "pincode_conflict", "label": "Pincode belongs to a different area", "effect": "-"})
    if f["location"]:
        out.append({"factor": "location", "label": "District/city mentioned matches", "effect": "+"})
    if f["state"]:
        out.append({"factor": "state", "label": "State matches", "effect": "+"})
    if f["location_conflict"]:
        out.append({"factor": "location_conflict", "label": "A different district/state is mentioned", "effect": "-"})
    return out + extra


def match(db, q: Query, *, limit: int | None = None, exclude: set[str] | None = None) -> dict[str, Any]:
    """Return ranked candidates with confidence, explanation and a routing decision."""
    cfg = get_settings_block(db, "matching")
    limit = limit or int(cfg.get("max_candidates", 5))
    idx = get_index(db)
    model = load_model()
    qn = q.norm
    tf = idx.tfidf_scores(qn)
    candidates = set(sorted(tf, key=lambda k: -tf[k])[:12])
    pid_q = normalize_permanent_id(q.raw_permanent_id)
    if pid_q and pid_q in idx.by_pid:
        candidates.add(idx.by_pid[pid_q])
    acr = acronym_hits(q, idx)
    candidates |= set(acr)
    if exclude:
        candidates -= exclude
    scored = []
    for iid in candidates:
        f = features(q, iid, idx, tf.get(iid, 0.0))
        p, source = _probability(_vector(f), model)
        extra: list[dict[str, Any]] = []
        if f["permanent_id"]:
            p = max(p, 0.995)
        if f["permanent_id_conflict"]:
            p *= 0.3
        if acr.get(iid, 0) > p:
            p = acr[iid]
            extra.append({"factor": "acronym", "label": "Acronym matches institution initials (acronym rule; "
                                                         "never auto-links alone)", "effect": "+"})
        if idx.confirmed.get(qn) == iid:
            p = max(p, 0.97)
            extra.append({"factor": "confirmed", "label": "Previously confirmed by an officer", "effect": "+"})
        if (qn, iid) in idx.rejected:
            p *= 0.15
            extra.append({"factor": "rejected", "label": "An officer rejected this pairing before", "effect": "-"})
        inst = idx.insts[iid]
        scored.append({
            "institution_id": iid, "name": inst["name"], "permanent_id": inst["permanent_id"],
            "district": inst["district"], "state": inst["state"], "pincode": inst["pincode"],
            "confidence": round(float(p), 4), "features": {k: round(v, 4) for k, v in f.items()},
            "factors": explain(f, extra), "score_source": source,
        })
    scored.sort(key=lambda c: (-c["confidence"], c["institution_id"]))
    top = scored[:limit]
    auto_t, review_t = float(cfg["auto_link_threshold"]), float(cfg["review_threshold"])
    best = top[0]["confidence"] if top else 0.0
    second = top[1]["confidence"] if len(top) > 1 else 0.0
    if best >= auto_t and second < review_t:
        decision, reason = "AUTO_LINK", "High confidence and no other plausible candidate"
    elif best >= review_t:
        decision = "REVIEW"
        reason = ("Ambiguous: more than one institution is plausible — officer must choose" if second >= review_t
                  else "Moderate confidence — needs officer confirmation")
    else:
        decision, reason = "NO_MATCH", "No candidate reaches the review threshold"
    for c in top:
        c["band"] = "HIGH" if c["confidence"] >= auto_t else "MEDIUM" if c["confidence"] >= review_t else "LOW"
    return {"query": {"raw_name": q.raw_name, "normalized": qn, "raw_address": q.raw_address,
                      "raw_pincode": q.raw_pincode, "raw_state": q.raw_state, "raw_permanent_id": q.raw_permanent_id},
            "candidates": top, "decision": decision, "reason": reason,
            "thresholds": {"auto_link": auto_t, "review": review_t},
            "model": {"source": top[0]["score_source"] if top else ("MODEL" if model else "FALLBACK_WEIGHTS"),
                      "metrics": (model or {}).get("metrics")},
            "note": "Confidence is a model-estimated probability calibrated on synthetic validation pairs; "
                    "it is not a certainty. Officers confirm or reject."}


# ----------------------------------------------------------------------------- training
_TYPE_WORDS = {"institute", "college", "engineering", "technology", "school", "polytechnic", "pharmacy",
               "management", "studies", "research", "science", "computer", "applications", "architecture"}


def _noisy_variants(name: str, district: str, rng: random.Random) -> list[str]:
    from ..seed.generator import _abbreviate, _misspell

    words = name.split()
    out = [name, name.upper(), _abbreviate(name), f"{name}, {district}", f"{name} (Main Campus)",
           f"{_abbreviate(name)}, {district}", name.replace("&", "and")]
    for _ in range(2):
        mw = list(words)
        idxs = [i for i, w in enumerate(mw) if len(w) >= 5]
        for _k in range(rng.choice([1, 1, 2])):
            if idxs:
                j = rng.choice(idxs)
                mw[j] = _misspell(mw[j], rng)
        out.append(" ".join(mw))
    core = [w for w in words if fold(w) not in _TYPE_WORDS and w not in ("of", "&", "and")]
    if core:
        out.append(f"{' '.join(core)} {rng.choice(['College', 'Institute', 'Engg College'])} {district}")
    return out


def train_model(db, seed: int = 26264) -> dict[str, Any]:
    """Fit the match-confidence model on synthetic positive/negative pairs and save it."""
    from sklearn.linear_model import LogisticRegression

    rng = random.Random(seed + 7)
    idx = MatchIndex(db)
    X, y = [], []
    inst_ids = sorted(idx.insts)
    for iid in inst_ids:
        inst = idx.insts[iid]
        aliases = [s for (i, s, k) in idx.strings if i == iid and k == "FORMER_NAME"]
        variants = _noisy_variants(inst["name"], inst["district"], rng) + aliases
        for v in variants:
            r = rng.random()
            address = None
            if r < 0.4:
                address = f"{inst['district']}, {inst['state']}"
            elif r < 0.55:
                other = idx.insts[rng.choice(inst_ids)]
                address = f"{other['district']}, {other['state']}"  # noisy / wrong hint
            pin = inst["pincode"] if rng.random() < 0.25 else None
            pid = inst["permanent_id"] if rng.random() < 0.08 else None
            q = Query(v, raw_address=address, raw_pincode=pin, raw_permanent_id=pid)
            tf = idx.tfidf_scores(q.norm)
            X.append(_vector(features(q, iid, idx, tf.get(iid, 0.0))))
            y.append(1)
            negs = [k for k in sorted(tf, key=lambda k: -tf[k]) if k != iid][:6]
            negs += rng.sample([k for k in inst_ids if k != iid], 2)
            for nid in negs:
                X.append(_vector(features(q, nid, idx, tf.get(nid, 0.0))))
                y.append(0)
    Xa, ya = np.array(X), np.array(y)
    order = np.random.default_rng(seed).permutation(len(ya))
    cut = int(len(ya) * 0.75)
    tr, te = order[:cut], order[cut:]
    clf = LogisticRegression(C=2.0, max_iter=5000)
    clf.fit(Xa[tr], ya[tr])
    p = clf.predict_proba(Xa[te])[:, 1]
    brier = float(np.mean((p - ya[te]) ** 2))
    acc = float(np.mean((p >= 0.5) == ya[te]))
    bins = []
    for lo in np.arange(0, 1.0, 0.2):
        m = (p >= lo) & (p < lo + 0.2 + (1e-9 if lo >= 0.8 else 0))
        if m.sum():
            bins.append({"bin": f"{lo:.1f}-{lo + 0.2:.1f}", "n": int(m.sum()), "mean_predicted": round(float(p[m].mean()), 3),
                         "observed_rate": round(float(ya[te][m].mean()), 3)})
    clf.fit(Xa, ya)  # final model on all pairs
    from ..core.clock import now_iso

    model = {
        "features": FEATURES, "coef": [round(float(c), 6) for c in clf.coef_[0]],
        "intercept": round(float(clf.intercept_[0]), 6),
        "metrics": {"brier_score": round(brier, 4), "accuracy_at_0_5": round(acc, 4), "n_pairs": int(len(ya)),
                    "n_positive": int(ya.sum()), "holdout_fraction": 0.25, "reliability": bins,
                    "validation": "synthetic variants of the Institution Master (not real-world data)"},
        "trained_at": now_iso(), "seed": seed,
    }
    path = _model_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=1), encoding="utf-8")
    _model_cache.pop(str(path), None)
    return model


def ensure_model(db) -> dict[str, Any]:
    model = load_model()
    if model is None:
        model = train_model(db, seed=get_settings().seed)
    return model
