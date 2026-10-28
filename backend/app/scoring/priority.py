"""Explainable, deterministic priority engine.

score = 100 * W * (1 + min(cap, sum_k w_k * m_k)) / (W_max * (1 + cap))

* W   — severity weight of the case's category (editable table). If a keyword rule of a
        *more severe* category matches the text (e.g. "ragging" in a 'General enquiry'),
        that higher weight is used and a chip says so (configurable).
* m_k — normalised modifiers in [0, 1]: complainants (log scale), evidence attached,
        Court/Parliament/VIP reference, and age against the SLA.
* w_k — modifier weights; `cap` bounds the total modifier uplift.
Bands come from editable thresholds. Every contribution is returned as a "why" chip in
score points. The ML category suggestion is shown as an advisory chip only (0 points).
Officer overrides replace the band (not the computed score) and are logged separately.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from ..core.clock import now_iso
from ..core.clock import today as clock_today
from ..core.util import clamp
from .rules import SEVERITY_LABELS, category_rules, get_settings_block

_kw_cache: dict[str, re.Pattern[str]] = {}


def _kw_pattern(keyword: str) -> re.Pattern[str]:
    pat = _kw_cache.get(keyword)
    if pat is None:
        pat = re.compile(r"\b" + re.escape(keyword.lower()) + r"\b")
        _kw_cache[keyword] = pat
    return pat


def keyword_hits(text: str, rules: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    low = (text or "").lower()
    hits: dict[str, list[str]] = {}
    for code, rule in rules.items():
        if not rule.get("active", 1):
            continue
        found = [kw for kw in rule.get("keywords", []) if kw and _kw_pattern(kw).search(low)]
        if found:
            hits[code] = found
    return hits


def band_for(score: float, bands: dict[str, float]) -> str:
    if score >= float(bands["CRITICAL"]):
        return "CRITICAL"
    if score >= float(bands["HIGH"]):
        return "HIGH"
    if score >= float(bands["MEDIUM"]):
        return "MEDIUM"
    return "LOW"


def compute(case: dict[str, Any], rules: dict[str, dict[str, Any]], cfg: dict[str, Any], today: date,
            ml: dict[str, Any] | None = None) -> dict[str, Any]:
    rule = rules[case["category_code"]]
    mods = cfg["modifiers"]
    cap = float(cfg["modifier_cap"])
    w_max = float(cfg.get("max_severity_weight", 5.0))
    weight = float(rule["severity_weight"])
    level = int(rule["severity_level"])
    chips: list[dict[str, Any]] = []

    text = f"{case.get('subject') or ''}. {case.get('description') or ''}"
    hits = keyword_hits(text, rules)
    escalated_from = None
    sev_label = rule["label"]
    if cfg.get("keyword_escalation", True) and hits:
        best = max(hits, key=lambda c: (float(rules[c]["severity_weight"]), c))
        if float(rules[best]["severity_weight"]) > weight:
            escalated_from = rule["label"]
            sev_label = rules[best]["label"]
            weight = float(rules[best]["severity_weight"])
            level = int(rules[best]["severity_level"])
            chips.append({
                "key": "keyword", "kind": "keyword", "points": 0.0,
                "label": f"Keyword rule: '{hits[best][0]}'",
                "detail": f"Text matches the '{rules[best]['label']}' keyword list, so severity "
                          f"{SEVERITY_LABELS.get(level, level)} ({weight:g}) is used instead of "
                          f"'{escalated_from}'. Keyword rules are editable.",
            })

    # Normalised modifiers m_k in [0, 1]
    n = max(1, int(case.get("complainant_count") or 1))
    cap_count = float(mods["complainants"].get("cap_count", 100))
    m_c = clamp(math.log10(n) / math.log10(cap_count), 0, 1) if n > 1 else 0.0
    m_e = 1.0 if int(case.get("evidence_count") or 0) > 0 else 0.0
    flag = (case.get("reference_flag") or "NONE").upper()
    m_r = float(mods["reference"].get(flag.lower(), 0.0)) if flag != "NONE" else 0.0
    received = date.fromisoformat(case["received_date"])
    end = date.fromisoformat(case["disposed_date"]) if case.get("disposed_date") else today
    age = max(0, (end - received).days)
    sla = max(1, int(case.get("sla_days") or rule["sla_days"]))
    full_at = float(mods["age"].get("full_at_sla_multiple", 2.0))
    m_a = clamp(age / (sla * full_at), 0, 1)

    parts = {
        "complainants": float(mods["complainants"]["weight"]) * m_c,
        "evidence": float(mods["evidence"]["weight"]) * m_e,
        "reference": float(mods["reference"]["weight"]) * m_r,
        "age": float(mods["age"]["weight"]) * m_a,
    }
    raw_sum = sum(parts.values())
    applied = min(cap, raw_sum)
    scale = applied / raw_sum if raw_sum > 0 else 1.0
    max_raw = w_max * (1 + cap)
    score = clamp(100.0 * weight * (1 + applied) / max_raw, 0, 100)
    base_points = 100.0 * weight / max_raw

    chips.insert(0, {
        "key": "severity", "kind": "severity", "points": round(base_points, 1),
        "label": f"{sev_label} · severity {level}/5",
        "detail": f"{SEVERITY_LABELS.get(level, level)} severity, weight {weight:g} of max {w_max:g}.",
    })
    labels = {
        "complainants": (f"{n} complainant{'s' if n != 1 else ''}", f"log10({n})/log10({cap_count:g}) = {m_c:.2f} x weight {mods['complainants']['weight']}"),
        "evidence": ("Evidence attached" if m_e else "No evidence attached",
                     f"{case.get('evidence_count') or 0} item(s) x weight {mods['evidence']['weight']}"),
        "reference": (f"{flag.title()} reference" if m_r else "No Court/VIP/Parliament reference",
                      f"factor {m_r:.2f} x weight {mods['reference']['weight']}"),
        "age": (f"Age {age}d of {sla}d SLA", f"{age}/({sla} x {full_at:g}) = {m_a:.2f} x weight {mods['age']['weight']}"),
    }
    for key, value in parts.items():
        pts = 100.0 * weight * value * scale / max_raw
        chips.append({"key": key, "kind": "modifier", "points": round(pts, 1), "label": labels[key][0],
                      "detail": labels[key][1]})
    if raw_sum > cap:
        chips.append({"key": "cap", "kind": "cap", "points": 0.0, "label": f"Modifier cap {cap:g} applied",
                      "detail": f"Modifier sum {raw_sum:.2f} capped at {cap:g}; modifier points scaled by {scale:.2f}."})
    band = band_for(score, cfg["bands"])
    override = case.get("priority_override_band")
    if override:
        chips.append({"key": "override", "kind": "override", "points": 0.0, "label": f"Officer override: {override}",
                      "detail": case.get("priority_override_reason") or "Override recorded in the audit trail."})
    if ml and ml.get("category"):
        ml_cat = ml["category"]
        same = ml_cat == case["category_code"]
        chips.append({
            "key": "ml", "kind": "ml", "points": 0.0,
            "label": f"Text model: {rules.get(ml_cat, {}).get('label', ml_cat)} ({round(float(ml.get('probability', 0)) * 100)}%)",
            "detail": ("Agrees with the selected category." if same else
                       "Differs from the selected category — officer should review. ")
                      + " Recommendation only (TF-IDF + Logistic Regression on synthetic data); it does not change the score.",
        })
    return {
        "score": round(score, 1),
        "band": band,
        "effective_band": override or band,
        "overridden": bool(override),
        "chips": chips,
        "formula": f"100 x {weight:g} x (1 + min({cap:g}, {raw_sum:.2f})) / ({w_max:g} x (1 + {cap:g})) = {score:.1f}",
        "inputs": {"severity_weight": weight, "severity_level": level, "complainants": n, "evidence_count":
                   int(case.get("evidence_count") or 0), "reference_flag": flag, "age_days": age, "sla_days": sla,
                   "keyword_hits": hits},
        "explanation": f"{band} ({score:.1f}): " + ", ".join(f"{c['label']} {c['points']:+.1f}" for c in chips
                                                           if c["kind"] in ("severity", "modifier") and c["points"]),
    }


def compute_for_case(db, case: dict[str, Any], today: date | None = None, with_ml: bool = True) -> dict[str, Any]:
    rules = category_rules(db)
    cfg = get_settings_block(db, "priority")
    ml = None
    if with_ml and case.get("ml_category"):
        ml = {"category": case["ml_category"], "probability": case.get("ml_confidence") or 0}
    return compute(case, rules, cfg, today or clock_today(), ml)


def recompute_all(db, today: date | None = None, case_ids: list[str] | None = None) -> int:
    """Refresh the cached score/band used for list sorting and dashboards."""
    today = today or clock_today()
    rules = category_rules(db)
    cfg = get_settings_block(db, "priority")
    if case_ids is not None:
        if not case_ids:
            return 0
        marks = ",".join("?" for _ in case_ids)
        rows = db.all(f"SELECT * FROM complaints WHERE id IN ({marks})", case_ids)
    else:
        rows = db.all("SELECT * FROM complaints")
    stamp = now_iso()
    updates = []
    for case in rows:
        res = compute(case, rules, cfg, today)
        updates.append((res["score"], res["band"], stamp, case["id"]))
    db.many("UPDATE complaints SET priority_score = ?, priority_band = ?, priority_computed_at = ? WHERE id = ?", updates)
    return len(updates)
