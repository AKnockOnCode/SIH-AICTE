"""Command Dashboard aggregates. Every figure is a live SQL aggregate over persisted cases.

Date filters select the *receipt cohort* (cases received in the range); statuses are as of today.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..alerts.service import visible_clause
from ..core import clock
from ..core.provenance import data_mode
from ..core.security import User, region_scope
from ..scoring.rules import category_rules
from ..sla.engine import AGEING_BUCKETS


def cohort_filter(user: User, f: dict[str, Any], alias: str = "c") -> tuple[str, list[Any]]:
    where, params = ["1=1"], []
    scope = region_scope(user)
    if scope:
        where.append(f"{alias}.region_code = ?")
        params.append(scope)
    if f.get("date_from"):
        where.append(f"{alias}.received_date >= ?")
        params.append(str(f["date_from"]))
    if f.get("date_to"):
        where.append(f"{alias}.received_date <= ?")
        params.append(str(f["date_to"]))
    for key, col in (("bureau", "bureau_code"), ("region", "region_code"), ("state", "state"), ("category", "category_code"),
                     ("status", "status")):
        vals = f.get(key)
        if vals:
            where.append(f"{alias}.{col} IN ({','.join('?' for _ in vals)})")
            params.extend(vals)
    if f.get("institution_id"):
        where.append(f"{alias}.institution_id = ?")
        params.append(f["institution_id"])
    return " AND ".join(where), params


def kpis(db, where: str, params: list[Any], today: str) -> dict[str, Any]:
    r = db.one(
        f"SELECT COUNT(*) received, SUM(status IN ('RECEIVED','PENDING')) pending, SUM(status = 'UNDER_PROCESS') under_process, "
        f"SUM(status = 'TRANSFERRED') transferred, SUM(status = 'ESCALATED') escalated, SUM(status = 'DISPOSED') disposed, "
        f"SUM(status != 'DISPOSED') open_total, SUM(status != 'DISPOSED' AND expected_disposal_date < ?) overdue, "
        f"SUM(status = 'DISPOSED' AND disposed_date <= expected_disposal_date) disposed_in_time, "
        f"AVG(CASE WHEN status = 'DISPOSED' THEN julianday(disposed_date) - julianday(received_date) END) avg_days, "
        f"SUM(transfer_count > 0) ever_transferred, SUM(escalation_level > 0) ever_escalated "
        f"FROM complaints c WHERE {where}", (today, *params))
    out = {k: (r[k] or 0) for k in r}
    out["disposal_rate"] = round(out["disposed"] / out["received"], 4) if out["received"] else 0.0
    out["sla_compliance"] = round(out["disposed_in_time"] / out["disposed"], 4) if out["disposed"] else 0.0
    out["avg_disposal_days"] = round(float(r["avg_days"] or 0), 1)
    return out


def dashboard(db, user: User, f: dict[str, Any]) -> dict[str, Any]:
    today_d = clock.today()
    today = today_d.isoformat()
    where, params = cohort_filter(user, f)
    rules = category_rules(db)
    k = kpis(db, where, params, today)
    officers = {r["bureau_code"]: r["n"] for r in db.all(
        "SELECT bureau_code, COUNT(*) n FROM officers WHERE active = 1 GROUP BY bureau_code")}
    by_bureau = []
    for r in db.all(
            f"SELECT b.code, b.name, COUNT(c.id) received, SUM(c.status IN ('RECEIVED','PENDING')) pending, "
            f"SUM(c.status = 'UNDER_PROCESS') under_process, SUM(c.status = 'TRANSFERRED') transferred, "
            f"SUM(c.status = 'ESCALATED') escalated, SUM(c.status = 'DISPOSED') disposed, SUM(c.status != 'DISPOSED') open_total, "
            f"SUM(c.status != 'DISPOSED' AND c.expected_disposal_date < ?) overdue "
            f"FROM bureaus b LEFT JOIN complaints c ON c.bureau_code = b.code AND {where} GROUP BY b.code ORDER BY b.sort_order",
            (today, *params)):
        r = {key: (val or 0) if key not in ("code", "name") else val for key, val in r.items()}
        r["officers"] = officers.get(r["code"], 0)
        r["open_per_officer"] = round(r["open_total"] / r["officers"], 1) if r["officers"] else None
        by_bureau.append(r)
    priority = db.all(f"SELECT COALESCE(priority_override_band, priority_band) band, COUNT(*) n FROM complaints c "
                      f"WHERE {where} AND status != 'DISPOSED' GROUP BY band", params)
    by_region = db.all(f"SELECT r.code, r.name, COUNT(c.id) received, SUM(c.status != 'DISPOSED') open_total, "
                       f"SUM(c.status != 'DISPOSED' AND c.expected_disposal_date < ?) overdue FROM regions r "
                       f"LEFT JOIN complaints c ON c.region_code = r.code AND {where} GROUP BY r.code ORDER BY r.sort_order",
                       (today, *params))
    for r in by_region:
        r["received"], r["open_total"], r["overdue"] = r["received"] or 0, r["open_total"] or 0, r["overdue"] or 0
    by_state = db.all(f"SELECT state, COUNT(*) received, SUM(status != 'DISPOSED') open_total, "
                      f"SUM(status != 'DISPOSED' AND expected_disposal_date < ?) overdue FROM complaints c WHERE {where} "
                      f"AND state IS NOT NULL GROUP BY state ORDER BY received DESC", (today, *params))
    ages = db.all(f"SELECT bureau_code, CAST(julianday(?) - julianday(received_date) AS INTEGER) age FROM complaints c "
                  f"WHERE {where} AND status != 'DISPOSED'", (today, *params))
    ageing = []
    for lo, hi, label in AGEING_BUCKETS:
        rows = [a for a in ages if lo <= a["age"] <= hi]
        by_b: dict[str, int] = {}
        for a in rows:
            by_b[a["bureau_code"]] = by_b.get(a["bureau_code"], 0) + 1
        ageing.append({"bucket": label, "count": len(rows), "by_bureau": by_b})
    start = (today_d.replace(day=1) - timedelta(days=540)).replace(day=1)
    if f.get("date_from") and str(f["date_from"]) > start.isoformat():
        start = date.fromisoformat(str(f["date_from"])).replace(day=1)
    received_m = {r["m"]: r["n"] for r in db.all(
        f"SELECT substr(received_date, 1, 7) m, COUNT(*) n FROM complaints c WHERE {where} AND received_date >= ? GROUP BY m",
        (*params, start.isoformat()))}
    disposed_m = {r["m"]: r for r in db.all(
        f"SELECT substr(disposed_date, 1, 7) m, COUNT(*) n, SUM(disposed_date <= expected_disposal_date) in_time "
        f"FROM complaints c WHERE {where} AND status = 'DISPOSED' AND disposed_date >= ? GROUP BY m",
        (*params, start.isoformat()))}
    trend = []
    cur = start
    while cur <= today_d:
        m = cur.strftime("%Y-%m")
        rec, dis = received_m.get(m, 0), disposed_m.get(m, {}).get("n", 0)
        trend.append({"month": m, "received": rec, "disposed": dis,
                      "disposal_ratio": round(dis / rec, 2) if rec else None,
                      "in_time_share": round((disposed_m.get(m, {}).get("in_time") or 0) / dis, 2) if dis else None})
        cur = (cur.replace(day=28) + timedelta(days=5)).replace(day=1)
    by_category = []
    for r in db.all(f"SELECT category_code, COUNT(*) received, SUM(status != 'DISPOSED') open_total FROM complaints c "
                    f"WHERE {where} GROUP BY category_code", params):
        rule = rules[r["category_code"]]
        by_category.append({**r, "label": rule["label"], "severity_level": rule["severity_level"]})
    by_category.sort(key=lambda x: (-x["severity_level"], -x["received"]))
    scope = region_scope(user)
    owhere, oparams = "o.status IN ('OPEN','UNDER_REVIEW')", []
    if scope:
        owhere += " AND i.region_code = ?"
        oparams.append(scope)
    ov_counts = {r["tier"]: r["n"] for r in db.all(
        f"SELECT o.tier, COUNT(*) n FROM overlap_alerts o JOIN institutions i ON i.id = o.institution_id WHERE {owhere} "
        f"GROUP BY o.tier", oparams)}
    cross = db.val(f"SELECT COUNT(*) FROM overlap_alerts o JOIN institutions i ON i.id = o.institution_id WHERE {owhere} "
                   f"AND o.cross_bureau = 1", oparams, 0)
    coordination = db.all(
        f"SELECT o.id, o.tier, o.headline, o.score, o.status, o.recommended_lead, o.bureaus_json, o.created_at, "
        f"i.id institution_id, i.name institution_name, i.demo_tag FROM overlap_alerts o JOIN institutions i "
        f"ON i.id = o.institution_id WHERE {owhere} AND (o.tier = 'CONFLICT' OR o.cross_bureau = 1) ORDER BY "
        f"CASE o.tier WHEN 'CONFLICT' THEN 0 WHEN 'DUPLICATE' THEN 1 ELSE 2 END, o.score DESC LIMIT 6", oparams)
    from ..core.util import loads

    for c in coordination:
        c["bureaus"] = loads(c.pop("bureaus_json"), [])
    multi = db.all(f"SELECT c.institution_id, i.name, COUNT(DISTINCT c.bureau_code) bureaus, "
                   f"GROUP_CONCAT(DISTINCT c.bureau_code) codes, COUNT(*) open_cases FROM complaints c JOIN institutions i "
                   f"ON i.id = c.institution_id WHERE {where} AND c.status != 'DISPOSED' GROUP BY c.institution_id "
                   f"HAVING bureaus >= 2 ORDER BY bureaus DESC, open_cases DESC", params)
    for m in multi:
        m["codes"] = sorted((m["codes"] or "").split(","))
    aclause, aparams = visible_clause(user)
    recent_alerts = db.all(f"SELECT a.id, a.alert_type, a.severity, a.title, a.case_id, a.institution_id, a.created_at, a.state "
                           f"FROM alerts a WHERE {aclause} AND a.state = 'NEW' ORDER BY CASE a.severity WHEN 'CRITICAL' THEN 0 "
                           f"WHEN 'WARNING' THEN 1 ELSE 2 END, CASE a.alert_type WHEN 'OVERLAP' THEN 0 WHEN 'ESCALATION' THEN 1 "
                           f"WHEN 'PREDICTED_BREACH' THEN 2 ELSE 3 END, a.created_at DESC LIMIT 8", aparams)
    triage = intake_triage(db, where, params)
    demo_a = db.one("SELECT id, name FROM institutions WHERE demo_tag = 'INSTITUTION_A'")
    demo_b = db.one("SELECT id, name FROM institutions WHERE demo_tag = 'LIVE_TRIGGER'")
    conflict_a = db.one("SELECT o.id FROM overlap_alerts o WHERE o.institution_id = ? AND o.tier = 'CONFLICT' ORDER BY o.created_at "
                        "LIMIT 1", (demo_a["id"],)) if demo_a else None
    pending_reviews = db.val("SELECT COUNT(*) FROM match_reviews WHERE status = 'PENDING'", default=0)
    return {
        "generated_at": clock.now_iso(), "as_of": today, "filters": {k: v for k, v in f.items() if v not in (None, [], "")},
        "data_mode": data_mode(db),
        "kpis": k, "by_bureau": by_bureau, "priority_mix": priority, "by_region": by_region, "by_state": by_state,
        "ageing": ageing, "trend": trend, "by_category": by_category,
        "overlaps": {"open_by_tier": ov_counts, "cross_bureau_open": cross, "coordination_queue": coordination},
        "multi_bureau_institutions": multi[:10], "multi_bureau_count": len(multi), "recent_alerts": recent_alerts,
        "triage": triage,
        "demo": {"institution_a": demo_a, "institution_a_conflict": conflict_a["id"] if conflict_a else None,
                 "live_trigger_institution": demo_b, "live_trigger_case": "RB-2310",
                 "pending_match_reviews": pending_reviews},
    }


TRIAGE_GROUPS = {
    "DUPLICATE": "Duplicate of an existing case",
    "RELATED": "Related or conflicting case",
    "UNIQUE": "New unique case",
}


def intake_triage(db, where: str, params: list[Any]) -> dict[str, Any]:
    """Where the cohort's cases went after intake de-duplication, and their (effective) priority band.

    DUPLICATE: member of a duplicate-tier overlap alert (not dismissed) or of a duplicate Master Case.
    RELATED:   member of a related/conflict-tier alert (not dismissed) or holding an active case link.
    UNIQUE:    no overlap found.
    """
    rows = db.all(
        f"SELECT c.id, COALESCE(c.priority_override_band, c.priority_band, 'LOW') band, "
        f"EXISTS(SELECT 1 FROM overlap_alert_cases ac JOIN overlap_alerts o ON o.id = ac.alert_id WHERE ac.case_id = c.id "
        f"AND o.tier = 'DUPLICATE' AND o.status != 'DISMISSED') "
        f"OR EXISTS(SELECT 1 FROM master_cases m WHERE m.id = c.master_case_id AND m.kind = 'DUPLICATE_MERGE') dup, "
        f"EXISTS(SELECT 1 FROM overlap_alert_cases ac JOIN overlap_alerts o ON o.id = ac.alert_id WHERE ac.case_id = c.id "
        f"AND o.tier IN ('RELATED','CONFLICT') AND o.status != 'DISMISSED') "
        f"OR EXISTS(SELECT 1 FROM case_links l WHERE l.active = 1 AND (l.case_a = c.id OR l.case_b = c.id)) rel "
        f"FROM complaints c WHERE {where}", params)
    flows: dict[tuple[str, str], int] = {}
    totals = {g: 0 for g in TRIAGE_GROUPS}
    for r in rows:
        g = "DUPLICATE" if r["dup"] else "RELATED" if r["rel"] else "UNIQUE"
        totals[g] += 1
        flows[(g, r["band"])] = flows.get((g, r["band"]), 0) + 1
    return {
        "received": len(rows), "groups": [{"key": k, "label": v, "n": totals[k]} for k, v in TRIAGE_GROUPS.items()],
        "flows": [{"group": g, "band": b, "n": n} for (g, b), n in sorted(flows.items())],
        "note": "Grouping reflects overlap alerts and links recorded so far; dismissed alerts are excluded.",
    }
