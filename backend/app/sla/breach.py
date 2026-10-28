"""SLA breach prediction with a Cox proportional-hazards survival model (numpy/scipy).

Event = disposal. Each case contributes its time to disposal (disposed cases) or its
current age (open cases, right-censored). Covariates: severity, issue family, Bureau/Cell,
transfers so far, complainants (log), evidence, Court/VIP/Parliament reference and
admission-season receipt. Current Bureau backlog is shown as context only: today's backlog
lies outside the historical range, so using it as an input would extrapolate. Coefficients are
fitted by penalised partial likelihood (Breslow ties, ridge 0.1); the baseline cumulative
hazard uses the Breslow estimator.

For an open case of age a with due date at day d:
    P(breach) = P(T > d | T > a) = exp(-(H0(d) - H0(a)) * exp(beta . x))
If the case is already past its due date the breach is a *fact*, not a prediction.
Limitations: trained on synthetic history (so it re-learns the generator's assumptions),
transfer counts are treated as known covariates, and probabilities are not guarantees.
A family-level Kaplan-Meier-style historical rate is shown alongside for transparency.
"""

from __future__ import annotations

import bisect
import json
import math
import threading
from datetime import date
from typing import Any

import numpy as np

from ..core.clock import now_iso
from ..core.config import get_settings
from ..scoring.rules import category_rules, get_settings_block

COVARIATES = ["severity", "safety", "regulatory", "process", "bureau_RB", "bureau_SDC", "bureau_LC", "bureau_RO",
              "bureau_AB", "transfers", "log_complainants", "evidence", "reference", "season"]
LABELS = {
    "severity": "Severity level", "safety": "Student-safety category", "regulatory": "Regulatory category",
    "process": "Regulatory process file", "bureau_RB": "Handled by RB", "bureau_SDC": "Handled by SDC",
    "bureau_LC": "Handled by Legal Cell", "bureau_RO": "Handled by a Regional Office", "bureau_AB": "Handled by AB",
    "transfers": "Transfers so far", "log_complainants": "Number of complainants", "evidence": "Evidence attached",
    "reference": "Court/VIP/Parliament reference", "season": "Received in admission season (Jul–Sep)",
}
RIDGE = 0.1

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _officer_counts(db) -> dict[str, int]:
    return {r["bureau_code"]: r["n"] for r in db.all(
        "SELECT bureau_code, COUNT(*) n FROM officers WHERE active = 1 GROUP BY bureau_code")}


def _backlog_at_receipt(cases: list[dict[str, Any]], officers: dict[str, int], today: date) -> dict[str, float]:
    """Open cases per officer in the case's Bureau on the day it was received."""
    by_bureau: dict[str, list[tuple[str, str]]] = {}
    for c in cases:
        end = c["disposed_date"] or "9999-12-31"
        by_bureau.setdefault(c["bureau_code"], []).append((c["received_date"], end))
    index: dict[str, tuple[list[str], list[str]]] = {}
    for b, spans in by_bureau.items():
        index[b] = (sorted(s for s, _ in spans), sorted(e for _, e in spans))
    out = {}
    for c in cases:
        starts, ends = index[c["bureau_code"]]
        t = c["received_date"]
        opened = bisect.bisect_right(starts, t)
        closed = bisect.bisect_right(ends, t)
        out[c["id"]] = (opened - closed) / max(1, officers.get(c["bureau_code"], 1))
    return out


def _row(case: dict[str, Any], rules: dict[str, Any], backlog: float) -> list[float]:
    rule = rules[case["category_code"]]
    fam = rule["family"]
    b = case["bureau_code"]
    month = int(case["received_date"][5:7])
    return [
        float(rule["severity_level"]), float(fam == "SAFETY"), float(fam == "REGULATORY"),
        float(fam == "REGULATORY_PROCESS"), float(b == "RB"), float(b == "SDC"), float(b == "LC"), float(b == "RO"),
        float(b == "AB"), float(case.get("transfer_count") or 0), math.log1p(int(case.get("complainant_count") or 1)),
        float(int(case.get("evidence_count") or 0) > 0), float((case.get("reference_flag") or "NONE") != "NONE"),
        float(month in (7, 8, 9)),
    ]


def _duration(case: dict[str, Any], today: date) -> tuple[float, int]:
    received = date.fromisoformat(case["received_date"])
    if case["status"] == "DISPOSED" and case["disposed_date"]:
        return max(0.5, float((date.fromisoformat(case["disposed_date"]) - received).days)), 1
    return max(0.5, float((today - received).days)), 0


def _neg_ll(beta: np.ndarray, X: np.ndarray, E: np.ndarray, last_idx: np.ndarray) -> tuple[float, np.ndarray]:
    eta = X @ beta
    eta_max = eta.max()
    w = np.exp(eta - eta_max)
    cum_w = np.cumsum(w)
    cum_wx = np.cumsum(w[:, None] * X, axis=0)
    risk_w = cum_w[last_idx]
    risk_wx = cum_wx[last_idx]
    ll = float(np.sum(E * (eta - eta_max - np.log(risk_w)))) - 0.5 * RIDGE * float(beta @ beta)
    grad = np.sum(E[:, None] * (X - risk_wx / risk_w[:, None]), axis=0) - RIDGE * beta
    return -ll, -grad


def fit(db, today: date) -> dict[str, Any]:
    from scipy.optimize import minimize

    rules = category_rules(db)
    cases = db.all("SELECT id, category_code, bureau_code, received_date, disposed_date, status, transfer_count, "
                   "complainant_count, evidence_count, reference_flag, sla_days FROM complaints")
    officers = _officer_counts(db)
    backlog = _backlog_at_receipt(cases, officers, today)
    X = np.array([_row(c, rules, backlog[c["id"]]) for c in cases], dtype=float)
    TE = [_duration(c, today) for c in cases]
    T = np.array([t for t, _ in TE])
    E = np.array([e for _, e in TE], dtype=float)
    mean, std = X.mean(axis=0), X.std(axis=0)
    std[std == 0] = 1.0
    Z = (X - mean) / std
    order = np.argsort(-T, kind="stable")
    Zs, Ts, Es = Z[order], T[order], E[order]
    # risk set for tied times = everyone with T >= t -> last index of the tie group (descending order)
    neg = -Ts
    last_idx = np.searchsorted(neg, neg, side="right") - 1
    res = minimize(_neg_ll, np.zeros(Z.shape[1]), args=(Zs, Es, last_idx), jac=True, method="L-BFGS-B")
    status = "FITTED" if res.success and np.all(np.isfinite(res.x)) else "FIT_FAILED"
    beta = res.x if status == "FITTED" else np.zeros(Z.shape[1])
    # Breslow baseline cumulative hazard at distinct event times (ascending)
    eta = Z @ beta
    w = np.exp(eta)
    asc = np.argsort(T, kind="stable")
    times = sorted({float(t) for t, e in zip(T, E, strict=True) if e == 1})
    H, cum = [], 0.0
    Ta, Ea, Wa = T[asc], E[asc], w[asc]
    suffix_w = np.cumsum(Wa[::-1])[::-1]
    for t in times:
        lo = int(np.searchsorted(Ta, t, side="left"))
        hi = int(np.searchsorted(Ta, t, side="right"))
        d = float(Ea[lo:hi].sum())
        cum += d / float(suffix_w[lo])
        H.append(cum)
    # Harrell's C-index (higher hazard should mean earlier disposal)
    ev = np.where(E == 1)[0]
    conc = disc = 0
    for i in ev:
        comparable = T[i] < T
        conc += int(np.sum(eta[i] > eta[comparable])) + 0.5 * int(np.sum(eta[i] == eta[comparable]))
        disc += int(np.sum(comparable))
    c_index = conc / disc if disc else 0.5
    # Family-level empirical durations (disposed only) for the transparent historical reference
    fam_durations: dict[str, list[float]] = {}
    for c, (t, e) in zip(cases, TE, strict=True):
        if e:
            fam_durations.setdefault(rules[c["category_code"]]["family"], []).append(t)
    model = {
        "status": status, "covariates": COVARIATES, "beta": [round(float(b), 6) for b in beta],
        "mean": [float(m) for m in mean], "std": [float(s) for s in std],
        "times": times, "H0": H, "c_index": round(float(c_index), 3), "n_cases": len(cases),
        "n_events": int(E.sum()), "trained_at": now_iso(), "as_of": today.isoformat(),
        "family_durations": {k: sorted(v) for k, v in fam_durations.items()},
        "method": "Cox proportional hazards (Breslow), ridge 0.1, fitted on synthetic case history",
    }
    path = get_settings().models_dir / "breach_model.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    slim = {k: v for k, v in model.items() if k not in ("times", "H0", "family_durations")}
    path.write_text(json.dumps(slim, indent=1), encoding="utf-8")
    return model


def _stamp(db, today: date) -> str:
    r = db.one("SELECT COUNT(*) n, SUM(status='DISPOSED') d, MAX(updated_at) u FROM complaints")
    return f"{today}|{r['n']}|{r['d']}|{(r['u'] or '')[:10]}"


def get_model(db, today: date) -> dict[str, Any]:
    key = str(get_settings().db_path)
    stamp = _stamp(db, today)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    model = fit(db, today)
    with _lock:
        _cache[key] = (stamp, model)
    return model


def _H0(model: dict[str, Any], t: float) -> float:
    i = bisect.bisect_right(model["times"], t) - 1
    return model["H0"][i] if i >= 0 else 0.0


def current_backlog(db, bureau: str) -> float:
    n = db.val("SELECT COUNT(*) FROM complaints WHERE bureau_code = ? AND status != 'DISPOSED'", (bureau,), 0)
    off = db.val("SELECT COUNT(*) FROM officers WHERE bureau_code = ? AND active = 1", (bureau,), 1)
    return n / max(1, off)


def predict(db, case: dict[str, Any], today: date, model: dict[str, Any] | None = None) -> dict[str, Any]:
    model = model or get_model(db, today)
    rules = category_rules(db)
    threshold = float(get_settings_block(db, "sla")["predicted_breach_threshold"])
    received = date.fromisoformat(case["received_date"])
    age = max(0, (today - received).days)
    due_offset = int(case["sla_days"])
    fam = rules[case["category_code"]]["family"]
    if case["status"] == "DISPOSED":
        return {"applicable": False, "reason": "Case is disposed; breach is a recorded fact, not a prediction."}
    if age > due_offset:
        return {"applicable": False, "is_fact": True, "reason": f"Already overdue by {age - due_offset} day(s): this is a fact, "
                "not a prediction.", "probability": None, "band": "OVERDUE"}
    backlog = current_backlog(db, case["bureau_code"])
    x = np.array(_row(case, rules, backlog))
    z = (x - np.array(model["mean"])) / np.array(model["std"])
    beta = np.array(model["beta"])
    eta = float(z @ beta)
    dH = max(0.0, _H0(model, float(due_offset)) - _H0(model, float(age)))
    # Survival beyond the due date given survival to today = probability of breaching the SLA.
    p = math.exp(-dH * math.exp(eta))
    contribs = beta * z
    factors = []
    for j in np.argsort(-np.abs(contribs))[:5]:
        c = float(contribs[j])
        if abs(c) < 0.03:
            continue
        name = COVARIATES[j]
        hr = math.exp(c)
        value = x[j]
        shown = {"log_complainants": f"{int(round(math.expm1(value)))}", "transfers": f"{int(value)}",
                 "severity": f"{int(value)}/5"}.get(name, "yes" if value else "no")
        factors.append({
            "factor": name, "label": f"{LABELS[name]}: {shown}", "hazard_ratio": round(hr, 2),
            "effect": "raises breach risk (slower disposal)" if c < 0 else "lowers breach risk (faster disposal)",
            "direction": "+" if c < 0 else "-",
        })
    durations = model["family_durations"].get(fam, [])
    still_open = [t for t in durations if t > age]
    hist = None
    if len(still_open) >= 8:
        missed = sum(1 for t in still_open if t > due_offset)
        hist = {"family": fam, "comparable_cases": len(still_open), "missed_share": round(missed / len(still_open), 3),
                "text": f"Of {len(still_open)} past '{fam.lower()}' cases still open at day {age}, "
                        f"{round(100 * missed / len(still_open))}% missed their due date."}
    band = "HIGH" if p >= threshold else "MEDIUM" if p >= 0.35 else "LOW"
    return {
        "applicable": True, "is_fact": False, "probability": round(p, 3), "band": band, "threshold": threshold,
        "context": {"bureau_backlog_per_officer": round(backlog, 1),
                    "note": "Current backlog is context only (not a model input)."},
        "age_days": age, "due_in_days": due_offset - age, "factors": factors, "historical_reference": hist,
        "model": {"method": model["method"], "c_index": model["c_index"], "status": model["status"],
                  "n_cases": model["n_cases"]},
        "disclaimer": "Model-estimated probability from synthetic history — a prompt for attention, not a certainty.",
    }
