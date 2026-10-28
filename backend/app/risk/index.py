"""Institution Risk Index (0-100) with recency decay, outcome adjustment, size
normalisation and empirical-Bayes shrinkage, plus the serious-complaint forecast.

For institution i, as of date t (complaint categories only; regulatory process files excluded):
  load_i = sum_c  severity_weight(c) * 0.5^(age_c / half_life) * outcome_factor(c)
           outcome factors: substantiated 1.0, partly 0.7, still open 0.6 (fallback: outcome
           unknown), unsubstantiated 0.2, withdrawn/not maintainable 0.1 (editable)
  exposure_i = intake_i / 1000 students (fallback intake if unknown -> lower confidence)
  rate_i = (load_i + k * pop_rate) / (exposure_i + k)        # Gamma-Poisson style shrinkage
           k = prior_strength_students / 1000; pop_rate = sum(load) / sum(exposure)
  index_i = 100 * rate_i / (rate_i + median_rate)            # 50 = the median institution
The 6-month change compares the index as of today and as of 182 days ago, both on today's
scale (today's median rate), so it reflects the institution's own change.
This is a complaint-burden indicator on SYNTHETIC data — not a finding of wrongdoing.
"""

from __future__ import annotations

import statistics
import threading
from datetime import date, timedelta
from typing import Any

from ..core.config import get_settings
from ..scoring.rules import category_rules, get_settings_block
from . import hawkes

START = date(2019, 1, 1)
_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _load_cases(db) -> list[dict[str, Any]]:
    return db.all("SELECT id, institution_id, category_code, received_date, disposed_date, status, outcome, bureau_code "
                  "FROM complaints WHERE institution_id IS NOT NULL")


def _stamp(db, today: date) -> str:
    r = db.one("SELECT COUNT(*) n, MAX(updated_at) u FROM complaints")
    i = db.one("SELECT COUNT(*) n, MAX(updated_at) u FROM institutions")
    s = db.one("SELECT MAX(updated_at) u FROM app_settings")
    c = db.one("SELECT MAX(updated_at) u FROM category_rules")
    return f"{today}|{r['n']}|{r['u']}|{i['n']}|{i['u']}|{s['u']}|{c['u']}"


def _loads(insts: list[dict[str, Any]], cases: list[dict[str, Any]], rules: dict[str, Any], cfg: dict[str, Any],
           as_of: date) -> dict[str, dict[str, Any]]:
    half = float(cfg["half_life_days"])
    factors = cfg["outcome_factors"]
    out = {i["id"]: {"load": 0.0, "n": 0, "by_level": {}, "recent_load": 0.0, "outcomes": {}, "known_outcome": 0,
                     "first": None, "last": None, "serious_12m": 0} for i in insts}
    asof_s = as_of.isoformat()
    for c in cases:
        rule = rules.get(c["category_code"])
        if rule is None or rule["family"] == "REGULATORY_PROCESS" or c["received_date"] > asof_s:
            continue
        rec = out.get(c["institution_id"])
        if rec is None:
            continue
        age = (as_of - date.fromisoformat(c["received_date"])).days
        decay = 0.5 ** (age / half)
        disposed_by_then = c["disposed_date"] is not None and c["disposed_date"] <= asof_s
        outcome = c["outcome"] if disposed_by_then and c["outcome"] else "OPEN"
        f = float(factors.get(outcome, factors.get("OPEN", 0.6)))
        w = float(rule["severity_weight"]) * decay * f
        rec["load"] += w
        rec["n"] += 1
        lvl = int(rule["severity_level"])
        rec["by_level"][lvl] = rec["by_level"].get(lvl, 0) + 1
        rec["outcomes"][outcome] = rec["outcomes"].get(outcome, 0) + 1
        if outcome != "OPEN":
            rec["known_outcome"] += 1
        if age <= 365:
            rec["recent_load"] += w
            if lvl >= int(cfg.get("serious_min_severity", 4)):
                rec["serious_12m"] += 1
        rec["first"] = min(rec["first"] or c["received_date"], c["received_date"])
        rec["last"] = max(rec["last"] or c["received_date"], c["received_date"])
    return out


def _scores(insts: list[dict[str, Any]], loads: dict[str, dict[str, Any]], cfg: dict[str, Any],
            median_override: float | None = None) -> dict[str, dict[str, Any]]:
    fallback = float(cfg["intake_fallback"])
    k = float(cfg["prior_strength_students"]) / 1000.0
    exposure = {}
    for i in insts:
        known = i["intake_total"] is not None and i["intake_total"] > 0
        exposure[i["id"]] = ((i["intake_total"] if known else fallback) / 1000.0, known)
    total_load = sum(v["load"] for v in loads.values())
    total_exp = sum(e for e, _ in exposure.values())
    pop_rate = total_load / total_exp if total_exp else 0.0
    rates = {}
    for iid, rec in loads.items():
        e, _known = exposure[iid]
        rates[iid] = (rec["load"] + k * pop_rate) / (e + k)
    median_rate = median_override or (statistics.median(rates.values()) if rates else 1.0)
    median_rate = median_rate or 1e-9
    out = {}
    for iid, rec in loads.items():
        e, known = exposure[iid]
        rate = rates[iid]
        out[iid] = {
            "score": round(100.0 * rate / (rate + median_rate), 1),
            "rate": rate, "raw_rate": rec["load"] / e if e else 0.0, "exposure": e, "intake_known": known,
            "credibility": e / (e + k) if (e + k) else 0.0, "pop_rate": pop_rate, "median_rate": median_rate, "k": k,
        }
    return out


def compute_all(db, today: date) -> dict[str, Any]:
    """Risk, trend and forecast for every institution (cached per data stamp)."""
    key = str(get_settings().db_path)
    stamp = _stamp(db, today)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    rules = category_rules(db)
    cfg = get_settings_block(db, "risk")
    insts = db.all("SELECT id, name, intake_total, intake_source, region_code, state, trust_id, demo_tag FROM institutions")
    cases = _load_cases(db)
    now_loads = _loads(insts, cases, rules, cfg, today)
    past_loads = _loads(insts, cases, rules, cfg, today - timedelta(days=182))
    now_scores = _scores(insts, now_loads, cfg)
    # The 6-month change is measured on today's scale (same reference median), so it reflects
    # the institution's own change rather than movement of the whole population.
    ref_median = next(iter(now_scores.values()))["median_rate"] if now_scores else None
    past_scores = _scores(insts, past_loads, cfg, median_override=ref_median)
    # Serious-complaint event times (days since START) for the Hawkes forecast.
    T = float((today - START).days)
    serious_min = int(cfg.get("serious_min_severity", 4))
    series: dict[str, list[float]] = {i["id"]: [] for i in insts}
    for c in cases:
        rule = rules.get(c["category_code"])
        if rule and rule["family"] != "REGULATORY_PROCESS" and int(rule["severity_level"]) >= serious_min:
            t = float((date.fromisoformat(c["received_date"]) - START).days)
            if 0 <= t <= T and c["institution_id"] in series:
                series[c["institution_id"]].append(t)
    pooled = hawkes.fit_pooled(list(series.values()), T)
    seed = get_settings().seed
    forecasts = {iid: hawkes.forecast(sorted(ts), T, pooled, seed=seed) for iid, ts in series.items()}
    mean_p = sum(f["probability"] for f in forecasts.values()) / max(1, len(forecasts))
    deltas = sorted(now_scores[i["id"]]["score"] - past_scores[i["id"]]["score"] for i in insts)
    median_delta = deltas[len(deltas) // 2] if deltas else 0.0
    bands = cfg["bands"]
    result: dict[str, Any] = {"as_of": today.isoformat(), "median_delta_6m": round(median_delta, 1), "pooled": {k: round(v, 5) if isinstance(v, float) else v
                                                                    for k, v in pooled.items()},
                              "institutions": {}}
    for i in insts:
        iid = i["id"]
        s, p, ld = now_scores[iid], past_scores[iid], now_loads[iid]
        fc = forecasts[iid]
        fc["relative_likelihood"] = round(fc["probability"] / mean_p, 2) if mean_p else None
        delta = round(s["score"] - p["score"], 1)
        # Rising/falling must stand out from system-wide drift (e.g. admission-season volume).
        rel = delta - median_delta
        trend = "RISING" if delta >= 5 and rel >= 5 else "FALLING" if delta <= -5 and rel <= -5 else "STABLE"
        band = "HIGH" if s["score"] >= float(bands["HIGH"]) else "ELEVATED" if s["score"] >= float(bands["ELEVATED"]) else "NORMAL"
        confidence = "HIGH" if ld["n"] >= 10 and s["intake_known"] else "MEDIUM" if ld["n"] >= 4 else "LOW"
        caveats = ["Computed from SYNTHETIC complaint history — not an AICTE finding about any institution.",
                   "Measures complaint burden; unsubstantiated complaints are down-weighted, not ignored."]
        if i["intake_source"] in (None, "SYNTHETIC"):
            caveats.append("Student intake is synthetic/unverified; size normalisation is illustrative."
                           if i["intake_total"] else "Intake unknown: fallback intake used (reduced confidence).")
        if ld["n"] - ld["known_outcome"] > 0:
            caveats.append(f"{ld['n'] - ld['known_outcome']} case(s) still open: outcome factor 0.6 used as a documented fallback.")
        result["institutions"][iid] = {
            "institution_id": iid, "score": s["score"], "band": band, "score_6m_ago": p["score"], "delta_6m": delta,
            "trend": trend, "delta_vs_median_change": round(rel, 1), "confidence": confidence,
            "components": {
                "severity_weighted_load": round(ld["load"], 3), "recent_12m_share": round(ld["recent_load"] / ld["load"], 3) if ld["load"] else 0.0,
                "cases_considered": ld["n"], "cases_by_severity": {str(k): v for k, v in sorted(ld["by_level"].items())},
                "outcomes": ld["outcomes"], "outcome_coverage": round(ld["known_outcome"] / ld["n"], 3) if ld["n"] else 0.0,
                "exposure_thousand_students": round(s["exposure"], 3), "intake_known": s["intake_known"],
                "raw_rate": round(s["raw_rate"], 3), "shrunk_rate": round(s["rate"], 3),
                "population_rate": round(s["pop_rate"], 3), "median_rate": round(s["median_rate"], 3),
                "credibility": round(s["credibility"], 3), "prior_strength": round(s["k"], 3),
                "half_life_days": cfg["half_life_days"], "serious_last_12m": ld["serious_12m"],
                "first_case": ld["first"], "last_case": ld["last"],
            },
            "forecast": fc, "caveats": caveats,
        }
    with _lock:
        _cache[key] = (stamp, result)
    return result


def for_institution(db, inst_id: str, today: date) -> dict[str, Any] | None:
    return compute_all(db, today)["institutions"].get(inst_id)


def explain_text(r: dict[str, Any]) -> str:
    c = r["components"]
    return (f"Risk {r['score']:.0f}/100 ({r['band'].lower()}), {r['trend'].lower()} ({r['delta_6m']:+.0f} in 6 months). "
            f"Severity-weighted load {c['severity_weighted_load']:.1f} from {c['cases_considered']} complaint(s); "
            f"{round(c['recent_12m_share'] * 100)}% of it from the last 12 months; shrinkage credibility "
            f"{round(c['credibility'] * 100)}%.")


def score_band(score: float, bands: dict[str, float]) -> str:
    return "HIGH" if score >= float(bands["HIGH"]) else "ELEVATED" if score >= float(bands["ELEVATED"]) else "NORMAL"

