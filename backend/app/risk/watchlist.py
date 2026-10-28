"""Watch-list: institutions (and cases) that need attention, each with explicit reasons."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..core.security import User, region_scope
from ..scoring.rules import get_settings_block
from ..sla import breach
from . import index as risk_index

REASON_WEIGHT = {"HIGH_RISK": 3, "RISING_RISK": 3, "FORECAST": 2, "CONFLICT": 3, "OVERDUE": 2, "REPEATED_SERIOUS": 2,
                 "PREDICTED_BREACH": 1, "DUE_SOON": 1}


def institutions(db, user: User, today: date) -> list[dict[str, Any]]:
    risk = risk_index.compute_all(db, today)["institutions"]
    scope = region_scope(user)
    insts = {i["id"]: i for i in db.all("SELECT i.id, i.name, i.state, i.district, i.region_code, i.trust_id, t.name trust_name, "
                                        "i.demo_tag FROM institutions i LEFT JOIN trusts t ON t.id = i.trust_id")}
    stats = {r["institution_id"]: r for r in db.all(
        "SELECT institution_id, SUM(status != 'DISPOSED') open_c, SUM(status != 'DISPOSED' AND expected_disposal_date < ?) "
        "overdue_c, MAX(COALESCE(last_action_at, created_at)) last_activity FROM complaints WHERE institution_id IS NOT NULL "
        "GROUP BY institution_id", (today.isoformat(),))}
    conflicts: dict[str, list[str]] = {}
    for r in db.all("SELECT id, institution_id FROM overlap_alerts WHERE tier = 'CONFLICT' AND status IN ('OPEN','UNDER_REVIEW')"):
        conflicts.setdefault(r["institution_id"], []).append(r["id"])
    threshold = float(get_settings_block(db, "sla")["predicted_breach_threshold"])
    model = breach.get_model(db, today)
    predicted: dict[str, list[str]] = {}
    due_soon: dict[str, list[str]] = {}
    for c in db.all("SELECT * FROM complaints WHERE status != 'DISPOSED' AND expected_disposal_date >= ? "
                    "AND institution_id IS NOT NULL", (today.isoformat(),)):
        if c["expected_disposal_date"] <= (today + timedelta(days=3)).isoformat():
            due_soon.setdefault(c["institution_id"], []).append(c["id"])
        p = breach.predict(db, c, today, model)
        if p.get("applicable") and p["probability"] >= threshold:
            predicted.setdefault(c["institution_id"], []).append(c["id"])
    out = []
    for iid, inst in insts.items():
        if scope and inst["region_code"] != scope:
            continue
        r = risk[iid]
        s = stats.get(iid, {})
        fc = r["forecast"]
        reasons = []
        if r["band"] == "HIGH":
            reasons.append({"code": "HIGH_RISK", "label": f"High risk index ({r['score']:.0f}/100)"})
        if r["trend"] == "RISING":
            reasons.append({"code": "RISING_RISK", "label": f"Risk rising ({r['delta_6m']:+.0f} in 6 months)"})
        if fc["probability"] >= 0.6 or (fc.get("relative_likelihood") or 0) >= 1.8:
            reasons.append({"code": "FORECAST", "label": f"Serious complaint forecast {fc['probability']:.0%} in next 6 months "
                                                         f"({fc['confidence'].lower()} confidence)"})
        if conflicts.get(iid):
            reasons.append({"code": "CONFLICT", "label": f"Open cross-bureau conflict ({', '.join(conflicts[iid])})"})
        if (s.get("overdue_c") or 0) >= 3:
            reasons.append({"code": "OVERDUE", "label": f"{s['overdue_c']} overdue cases"})
        if r["components"]["serious_last_12m"] >= 2:
            reasons.append({"code": "REPEATED_SERIOUS", "label": f"{r['components']['serious_last_12m']} serious complaints in 12 months"})
        if predicted.get(iid):
            reasons.append({"code": "PREDICTED_BREACH", "label": f"Predicted SLA breach: {', '.join(predicted[iid][:3])}"})
        if due_soon.get(iid):
            reasons.append({"code": "DUE_SOON", "label": f"Due within 3 days: {', '.join(due_soon[iid][:3])}"})
        if not reasons:
            continue
        weight = sum(REASON_WEIGHT[x["code"]] for x in reasons)
        urgent = any(x["code"] in ("CONFLICT", "HIGH_RISK") for x in reasons) or weight >= 7
        review = today + timedelta(days=7 if urgent else 14 if weight >= 4 else 30)
        out.append({
            "institution_id": iid, "name": inst["name"], "state": inst["state"], "district": inst["district"],
            "region_code": inst["region_code"], "trust_id": inst["trust_id"], "trust_name": inst["trust_name"],
            "demo_tag": inst["demo_tag"], "reasons": reasons, "attention_score": weight, "risk_score": r["score"],
            "risk_band": r["band"], "trend": r["trend"], "delta_6m": r["delta_6m"], "risk_confidence": r["confidence"],
            "forecast_probability": fc["probability"], "forecast_interval": fc["interval_80"], "forecast_status": fc["status"],
            "forecast_confidence": fc["confidence"], "open_cases": s.get("open_c") or 0, "overdue_cases": s.get("overdue_c") or 0,
            "last_activity": s.get("last_activity"), "next_review": review.isoformat(),
        })
    out.sort(key=lambda x: (-x["attention_score"], -x["risk_score"]))
    return out


def cases_at_risk(db, user: User, today: date, limit: int = 50) -> list[dict[str, Any]]:
    scope = region_scope(user)
    model = breach.get_model(db, today)
    where = "c.status != 'DISPOSED' AND c.expected_disposal_date >= ?"
    params: list[Any] = [today.isoformat()]
    if scope:
        where += " AND c.region_code = ?"
        params.append(scope)
    rows = db.all(f"SELECT c.*, i.name AS institution_name FROM complaints c LEFT JOIN institutions i ON i.id = c.institution_id "
                  f"WHERE {where}", params)
    out = []
    for c in rows:
        p = breach.predict(db, c, today, model)
        if not p.get("applicable"):
            continue
        out.append({"case_id": c["id"], "institution_id": c["institution_id"],
                    "institution_name": c["institution_name"] or c["institution_name_raw"], "bureau_code": c["bureau_code"],
                    "category_code": c["category_code"], "status": c["status"], "due_date": c["expected_disposal_date"],
                    "days_remaining": (date.fromisoformat(c["expected_disposal_date"]) - today).days,
                    "probability": p["probability"], "band": p["band"],
                    "top_factor": next((f["label"] for f in p["factors"] if f["direction"] == "+"), None),
                    "historical": (p.get("historical_reference") or {}).get("text"),
                    "priority_band": c["priority_override_band"] or c["priority_band"]})
    out.sort(key=lambda x: (-x["probability"], x["days_remaining"]))
    return out[:limit]
