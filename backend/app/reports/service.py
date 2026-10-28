"""Reports & analytics (Bureau/region/state/institution/category/status summaries, ageing, monthly and
quarterly performance, SLA compliance, overlap counts) with CSV/XLSX export of exactly what is shown."""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

from ..core import clock
from ..core.constants import STATUS_LABELS, SYNTHETIC_DISCLAIMER
from ..core.security import User, region_scope
from ..dashboard.service import cohort_filter
from ..scoring.rules import category_rules
from ..sla.engine import AGEING_BUCKETS

GROUPS = {
    "bureau": ("c.bureau_code", "Bureau/Cell"),
    "region": ("c.region_code", "Region"),
    "state": ("c.state", "State"),
    "institution": ("c.institution_id", "Institution"),
    "category": ("c.category_code", "Category"),
    "status": ("c.status", "Status"),
    "month": ("substr(c.received_date, 1, 7)", "Month received"),
    "quarter": ("substr(c.received_date, 1, 4) || '-Q' || ((CAST(substr(c.received_date, 6, 2) AS INTEGER) + 2) / 3)",
                "Quarter received"),
}

SUMMARY_COLUMNS = [
    ("group", "Group"), ("received", "Received"), ("open_total", "Open"), ("pending", "Pending"),
    ("under_process", "Under process"), ("transferred", "Transferred"), ("escalated", "Escalated"),
    ("disposed", "Disposed"), ("overdue", "Overdue (beyond SLA)"), ("disposal_rate", "Disposal rate"),
    ("sla_compliance", "SLA compliance"), ("avg_disposal_days", "Avg days to dispose"), ("serious_share", "Serious share"),
]


def _labels(db) -> dict[str, dict[str, str]]:
    return {
        "bureau": {r["code"]: f"{r['code']} – {r['name']}" for r in db.all("SELECT code, name FROM bureaus")},
        "region": {r["code"]: r["name"] for r in db.all("SELECT code, name FROM regions")},
        "institution": {r["id"]: f"{r['name']} ({r['id']})" for r in db.all("SELECT id, name FROM institutions")},
        "category": {k: v["label"] for k, v in category_rules(db).items()},
        "status": STATUS_LABELS,
    }


def summary(db, user: User, group_by: str, f: dict[str, Any]) -> dict[str, Any]:
    expr, label = GROUPS[group_by]
    where, params = cohort_filter(user, f)
    today = clock.today().isoformat()
    serious = [k for k, v in category_rules(db).items() if int(v["severity_level"]) >= 4 and v["family"] != "REGULATORY_PROCESS"]
    smarks = ",".join("?" for _ in serious)
    rows = db.all(
        f"SELECT {expr} AS grp, COUNT(*) received, SUM(c.status != 'DISPOSED') open_total, "
        f"SUM(c.status IN ('RECEIVED','PENDING')) pending, SUM(c.status = 'UNDER_PROCESS') under_process, "
        f"SUM(c.status = 'TRANSFERRED') transferred, SUM(c.status = 'ESCALATED') escalated, SUM(c.status = 'DISPOSED') disposed, "
        f"SUM(c.status != 'DISPOSED' AND c.expected_disposal_date < ?) overdue, "
        f"SUM(c.status = 'DISPOSED' AND c.disposed_date <= c.expected_disposal_date) in_time, "
        f"AVG(CASE WHEN c.status = 'DISPOSED' THEN julianday(c.disposed_date) - julianday(c.received_date) END) avg_days, "
        f"SUM(c.category_code IN ({smarks})) serious "
        f"FROM complaints c WHERE {where} GROUP BY grp ORDER BY received DESC", (today, *serious, *params))
    names = _labels(db).get(group_by, {})
    out = []
    for r in rows:
        key = r["grp"] if r["grp"] is not None else "(unassigned)"
        out.append({
            "key": key, "group": names.get(key, key), "received": r["received"], "open_total": r["open_total"] or 0,
            "pending": r["pending"] or 0, "under_process": r["under_process"] or 0, "transferred": r["transferred"] or 0,
            "escalated": r["escalated"] or 0, "disposed": r["disposed"] or 0, "overdue": r["overdue"] or 0,
            "disposal_rate": round((r["disposed"] or 0) / r["received"], 3) if r["received"] else 0.0,
            "sla_compliance": round((r["in_time"] or 0) / r["disposed"], 3) if r["disposed"] else None,
            "avg_disposal_days": round(r["avg_days"], 1) if r["avg_days"] is not None else None,
            "serious_share": round((r["serious"] or 0) / r["received"], 3) if r["received"] else 0.0,
        })
    if group_by in ("month", "quarter"):
        out.sort(key=lambda x: x["key"])
    return _table(f"Case summary by {label.lower()}", [(k, label if k == "group" else v) for k, v in SUMMARY_COLUMNS], out, f)


def ageing(db, user: User, f: dict[str, Any]) -> dict[str, Any]:
    where, params = cohort_filter(user, f)
    today = clock.today()
    rows = db.all(f"SELECT c.bureau_code, c.received_date FROM complaints c WHERE {where} AND c.status != 'DISPOSED'", params)
    table: dict[str, dict[str, Any]] = {}
    for r in rows:
        age = (today - date.fromisoformat(r["received_date"])).days
        rec = table.setdefault(r["bureau_code"], {"group": r["bureau_code"], **{b[2]: 0 for b in AGEING_BUCKETS}, "total": 0})
        for lo, hi, lab in AGEING_BUCKETS:
            if lo <= age <= hi:
                rec[lab] += 1
        rec["total"] += 1
    total = {"group": "All Bureaus/Cells", **{b[2]: sum(r[b[2]] for r in table.values()) for b in AGEING_BUCKETS},
             "total": sum(r["total"] for r in table.values())}
    out = sorted(table.values(), key=lambda x: -x["total"]) + [total]
    cols = [("group", "Bureau/Cell")] + [(b[2], b[2]) for b in AGEING_BUCKETS] + [("total", "Open total")]
    return _table("Pending-case ageing (open cases by age since receipt)", cols, out, f)


def performance(db, user: User, period: str, f: dict[str, Any]) -> dict[str, Any]:
    where, params = cohort_filter(user, f)
    if period == "quarter":
        rexpr = "substr(c.received_date,1,4) || '-Q' || ((CAST(substr(c.received_date,6,2) AS INTEGER)+2)/3)"
        dexpr = "substr(c.disposed_date,1,4) || '-Q' || ((CAST(substr(c.disposed_date,6,2) AS INTEGER)+2)/3)"
    else:
        rexpr, dexpr = "substr(c.received_date,1,7)", "substr(c.disposed_date,1,7)"
    rec = {r["p"]: r["n"] for r in db.all(f"SELECT {rexpr} p, COUNT(*) n FROM complaints c WHERE {where} GROUP BY p", params)}
    dis = {r["p"]: r for r in db.all(
        f"SELECT {dexpr} p, COUNT(*) n, SUM(c.disposed_date <= c.expected_disposal_date) in_time, "
        f"AVG(julianday(c.disposed_date) - julianday(c.received_date)) avg_days FROM complaints c WHERE {where} "
        f"AND c.status = 'DISPOSED' GROUP BY p", params)}
    periods = sorted(set(rec) | set(dis))
    out = []
    for p in periods:
        d = dis.get(p, {})
        n = d.get("n") or 0
        out.append({"group": p, "received": rec.get(p, 0), "disposed": n, "disposed_in_time": d.get("in_time") or 0,
                    "sla_compliance": round((d.get("in_time") or 0) / n, 3) if n else None,
                    "disposal_ratio": round(n / rec[p], 3) if rec.get(p) else None,
                    "avg_disposal_days": round(d["avg_days"], 1) if d.get("avg_days") is not None else None})
    cols = [("group", "Month" if period == "month" else "Quarter"), ("received", "Received"), ("disposed", "Disposed"),
            ("disposed_in_time", "Disposed within SLA"), ("sla_compliance", "SLA compliance"),
            ("disposal_ratio", "Disposed / received"), ("avg_disposal_days", "Avg days to dispose")]
    return _table(f"{'Monthly' if period == 'month' else 'Quarterly'} performance", cols, out, f)


def sla_report(db, user: User, f: dict[str, Any]) -> dict[str, Any]:
    where, params = cohort_filter(user, f)
    today = clock.today().isoformat()
    rules = category_rules(db)
    rows = db.all(
        f"SELECT c.bureau_code, c.category_code, COUNT(*) received, SUM(c.status = 'DISPOSED') disposed, "
        f"SUM(c.status = 'DISPOSED' AND c.disposed_date <= c.expected_disposal_date) in_time, "
        f"AVG(CASE WHEN c.status = 'DISPOSED' AND c.disposed_date > c.expected_disposal_date "
        f"THEN julianday(c.disposed_date) - julianday(c.expected_disposal_date) END) avg_delay, "
        f"SUM(c.status != 'DISPOSED' AND c.expected_disposal_date < ?) overdue_open FROM complaints c WHERE {where} "
        f"GROUP BY c.bureau_code, c.category_code ORDER BY c.bureau_code, received DESC", (today, *params))
    out = [{"group": f"{r['bureau_code']} · {rules[r['category_code']]['label']}", "bureau": r["bureau_code"],
            "category": r["category_code"], "sla_days": rules[r["category_code"]]["sla_days"], "received": r["received"],
            "disposed": r["disposed"] or 0, "in_time": r["in_time"] or 0,
            "sla_compliance": round((r["in_time"] or 0) / r["disposed"], 3) if r["disposed"] else None,
            "avg_delay_days_when_late": round(r["avg_delay"], 1) if r["avg_delay"] is not None else None,
            "overdue_open": r["overdue_open"] or 0} for r in rows]
    cols = [("group", "Bureau · Category"), ("sla_days", "SLA days"), ("received", "Received"), ("disposed", "Disposed"),
            ("in_time", "Within SLA"), ("sla_compliance", "SLA compliance"), ("avg_delay_days_when_late", "Avg delay when late"),
            ("overdue_open", "Open & overdue")]
    return _table("SLA compliance by Bureau/Cell and category", cols, out, f)


def overlaps_report(db, user: User, f: dict[str, Any]) -> dict[str, Any]:
    scope = region_scope(user)
    where, params = "1=1", []
    if scope:
        where, params = "i.region_code = ?", [scope]
    if f.get("date_from"):
        where += " AND o.created_at >= ?"
        params.append(str(f["date_from"]))
    if f.get("date_to"):
        where += " AND o.created_at <= ?"
        params.append(str(f["date_to"]) + "T23:59:59Z")
    rows = db.all(f"SELECT o.tier, o.status, o.cross_bureau, o.bureaus_json, (SELECT COUNT(*) FROM overlap_alert_cases x WHERE "
                  f"x.alert_id = o.id) n_cases FROM overlap_alerts o JOIN institutions i ON i.id = o.institution_id WHERE {where}",
                  params)
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = r["tier"]
        a = agg.setdefault(key, {"group": key, "alerts": 0, "open": 0, "under_review": 0, "resolved": 0, "dismissed": 0,
                                 "cross_bureau": 0, "cases_involved": 0})
        a["alerts"] += 1
        a[{"OPEN": "open", "UNDER_REVIEW": "under_review", "RESOLVED": "resolved", "DISMISSED": "dismissed"}[r["status"]]] += 1
        a["cross_bureau"] += r["cross_bureau"]
        a["cases_involved"] += r["n_cases"]
    masters = db.val("SELECT COUNT(*) FROM master_cases WHERE status = 'ACTIVE'", default=0)
    merged = db.val("SELECT COUNT(*) FROM complaints WHERE master_case_id IS NOT NULL", default=0)
    out = [agg[t] for t in ("CONFLICT", "DUPLICATE", "RELATED") if t in agg]
    out.append({"group": "Master Cases (active)", "alerts": masters, "open": None, "under_review": None, "resolved": None,
                "dismissed": None, "cross_bureau": None, "cases_involved": merged})
    cols = [("group", "Tier"), ("alerts", "Alerts"), ("open", "Open"), ("under_review", "Under review"), ("resolved", "Resolved"),
            ("dismissed", "Dismissed"), ("cross_bureau", "Cross-bureau"), ("cases_involved", "Cases involved")]
    return _table("Overlap / duplicate / conflict counts", cols, out, f)


def _table(title: str, cols: list[tuple[str, str]], rows: list[dict[str, Any]], f: dict[str, Any]) -> dict[str, Any]:
    return {"title": title, "columns": [{"key": k, "label": v} for k, v in cols], "rows": rows,
            "generated_at": clock.now_iso(), "filters": {k: v for k, v in f.items() if v not in (None, [], "")},
            "disclaimer": SYNTHETIC_DISCLAIMER}


def to_csv(table: dict[str, Any], user: User) -> str:
    buf = io.StringIO()
    buf.write(f"# AgniDrishti report: {table['title']}\n")
    buf.write(f"# Generated: {table['generated_at']} by {user.display_name} ({user.role_label})\n")
    buf.write(f"# Filters: {table['filters'] or 'none'}\n")
    buf.write(f"# {table['disclaimer']}\n")
    w = csv.writer(buf)
    w.writerow([c["label"] for c in table["columns"]])
    for r in table["rows"]:
        w.writerow(["" if r.get(c["key"]) is None else r.get(c["key"]) for c in table["columns"]])
    return buf.getvalue()


def to_xlsx(table: dict[str, Any], user: User) -> bytes:
    import xlsxwriter

    out = io.BytesIO()
    wb = xlsxwriter.Workbook(out, {"in_memory": True})
    head = wb.add_format({"bold": True, "bg_color": "#1F3864", "font_color": "#FFFFFF", "border": 1})
    pct = wb.add_format({"num_format": "0.0%"})
    ws = wb.add_worksheet("Report")
    ws.write(0, 0, table["title"], wb.add_format({"bold": True, "font_size": 13}))
    banner = ("MIXED DATA — synthetic demo records plus user-entered/imported records (see About)"
              if str(table["disclaimer"]).startswith("MIXED") else "SYNTHETIC DEMO DATA — not real AICTE records")
    ws.write(1, 0, banner, wb.add_format({"font_color": "#D64545", "bold": True}))
    for j, c in enumerate(table["columns"]):
        ws.write(3, j, c["label"], head)
        ws.set_column(j, j, max(12, min(45, len(c["label"]) + 4)))
    for i, r in enumerate(table["rows"], start=4):
        for j, c in enumerate(table["columns"]):
            v = r.get(c["key"])
            if v is None:
                continue
            if isinstance(v, float) and c["key"] in ("disposal_rate", "sla_compliance", "serious_share"):
                ws.write_number(i, j, v, pct)
            elif isinstance(v, (int, float)):
                ws.write_number(i, j, v)
            else:
                ws.write(i, j, str(v))
    about = wb.add_worksheet("About")
    for i, (k, v) in enumerate([("Report", table["title"]), ("Generated at (UTC)", table["generated_at"]),
                                ("Generated by", f"{user.display_name} ({user.role_label})"),
                                ("Filters", str(table["filters"] or "none")), ("Disclaimer", table["disclaimer"]),
                                ("Personal data", "None: complainant identities are not stored or exported.")]):
        about.write(i, 0, k, wb.add_format({"bold": True}))
        about.write(i, 1, v)
    about.set_column(0, 0, 22)
    about.set_column(1, 1, 110)
    wb.close()
    return out.getvalue()
