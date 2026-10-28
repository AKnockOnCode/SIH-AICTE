"""Read-side helpers for cases: filtering (all search fields), row shaping and detail assembly."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..core import clock
from ..core.security import User, allowed_case_ops, assert_can_view_case, region_scope
from ..core.util import loads
from ..scoring import priority as priority_mod
from ..scoring.rules import category_rules, get_settings_block
from ..sla import breach
from ..sla.engine import sla_state

SORTS = {
    "received_desc": "c.received_date DESC, c.id DESC",
    "received_asc": "c.received_date ASC, c.id ASC",
    "priority_desc": "c.priority_score DESC, c.received_date ASC",
    "due_asc": "c.expected_disposal_date ASC, c.id",
    "id": "c.id",
    "status": "c.status, c.received_date DESC",
}

BASE_SELECT = (
    "SELECT c.*, i.name AS institution_name, i.permanent_id AS permanent_id, o.display_name AS officer_name "
    "FROM complaints c LEFT JOIN institutions i ON i.id = c.institution_id "
    "LEFT JOIN officers o ON o.id = c.assigned_officer_id"
)


def institution_ids_for_text(db, text: str) -> list[str]:
    """Resolve institution text (name, alias, Permanent ID) to IDs via the entity-resolution engine."""
    from ..institutions import matcher

    ids = {r["id"] for r in db.all("SELECT id FROM institutions WHERE name LIKE ? OR permanent_id LIKE ?",
                                    (f"%{text}%", f"%{text}%"))}
    ids |= {r["institution_id"] for r in db.all("SELECT institution_id FROM institution_aliases WHERE alias LIKE ?",
                                                 (f"%{text}%",))}
    review_t = float(get_settings_block(db, "matching")["review_threshold"])
    res = matcher.match(db, matcher.Query(text), limit=5)
    ids |= {c["institution_id"] for c in res["candidates"] if c["confidence"] >= review_t}
    return sorted(ids)


def build_filters(db, user: User, f: dict[str, Any]) -> tuple[str, list[Any]]:
    where: list[str] = ["1=1"]
    params: list[Any] = []
    scope = region_scope(user)
    if scope:
        where.append("c.region_code = ?")
        params.append(scope)

    def multi(column: str, values: list[str] | None) -> None:
        if values:
            where.append(f"{column} IN ({','.join('?' for _ in values)})")
            params.extend(values)

    if f.get("q"):
        like = f"%{f['q']}%"
        where.append("(c.id LIKE ? OR c.source_ref LIKE ? OR c.external_ref LIKE ? OR c.subject LIKE ? "
                     "OR c.institution_name_raw LIKE ? OR i.name LIKE ? OR i.permanent_id LIKE ? "
                     "OR c.institution_id IN (SELECT institution_id FROM institution_aliases WHERE alias LIKE ?))")
        params.extend([like] * 8)
    if f.get("case_id"):
        where.append("c.id LIKE ?")
        params.append(f"%{f['case_id']}%")
    if f.get("institution_id"):
        where.append("c.institution_id = ?")
        params.append(f["institution_id"])
    if f.get("institution"):
        ids = institution_ids_for_text(db, f["institution"])
        clause = "c.institution_name_raw LIKE ?"
        params_local: list[Any] = [f"%{f['institution']}%"]
        if ids:
            clause = f"(c.institution_id IN ({','.join('?' for _ in ids)}) OR {clause})"
            params_local = [*ids, *params_local]
        where.append(clause)
        params.extend(params_local)
    if f.get("permanent_id"):
        where.append("(i.permanent_id = ? OR c.permanent_id_raw = ?)")
        params.extend([f["permanent_id"], f["permanent_id"]])
    multi("c.bureau_code", f.get("bureau"))
    multi("c.region_code", f.get("region"))
    multi("c.state", f.get("state"))
    multi("c.category_code", f.get("category"))
    multi("c.status", f.get("status"))
    multi("COALESCE(c.priority_override_band, c.priority_band)", f.get("priority"))
    multi("c.match_status", f.get("match_status"))
    if f.get("overdue") is not None:
        cond = "(c.status != 'DISPOSED' AND c.expected_disposal_date < ?)"
        where.append(cond if f["overdue"] else f"NOT {cond}")
        params.append(clock.today().isoformat())
    if f.get("open_only"):
        where.append("c.status != 'DISPOSED'")
    if f.get("date_from"):
        where.append("c.received_date >= ?")
        params.append(str(f["date_from"]))
    if f.get("date_to"):
        where.append("c.received_date <= ?")
        params.append(str(f["date_to"]))
    if f.get("master_case_id"):
        where.append("c.master_case_id = ?")
        params.append(f["master_case_id"])
    if f.get("demo_tag"):
        where.append("c.demo_tag = ?")
        params.append(f["demo_tag"])
    if f.get("synthetic") is not None:
        where.append("c.is_synthetic = ?")
        params.append(1 if f["synthetic"] else 0)
    if f.get("has_overlap"):
        where.append("EXISTS (SELECT 1 FROM overlap_alert_cases oc JOIN overlap_alerts oa ON oa.id = oc.alert_id "
                     "WHERE oc.case_id = c.id AND oa.status IN ('OPEN','UNDER_REVIEW'))")
    return " AND ".join(where), params


def shape_row(row: dict[str, Any], rules: dict[str, Any], today: date) -> dict[str, Any]:
    st = sla_state(row, today)
    out = dict(row)
    out["category_label"] = rules.get(row["category_code"], {}).get("label")
    out["effective_band"] = row.get("priority_override_band") or row.get("priority_band")
    out["overdue"] = st["overdue"]
    out["days_remaining"] = st["days_remaining"]
    out["age_days"] = st["age_days"]
    out["is_synthetic"] = bool(row.get("is_synthetic"))
    return out


def list_cases(db, user: User, f: dict[str, Any], page: int, page_size: int, sort: str = "received_desc") -> dict[str, Any]:
    where, params = build_filters(db, user, f)
    order = SORTS.get(sort, SORTS["received_desc"])
    total = db.val(f"SELECT COUNT(*) FROM complaints c LEFT JOIN institutions i ON i.id = c.institution_id WHERE {where}",
                   params, 0)
    rows = db.all(f"{BASE_SELECT} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                  (*params, page_size, (page - 1) * page_size))
    rules = category_rules(db)
    today = clock.today()
    return {"items": [shape_row(r, rules, today) for r in rows], "total": total, "page": page, "page_size": page_size,
            "filters": {k: v for k, v in f.items() if v not in (None, [], "")}}


def case_detail(db, user: User, case_id: str) -> dict[str, Any]:
    from ..core.errors import not_found

    row = db.one(f"{BASE_SELECT} WHERE c.id = ?", (case_id,))
    if row is None:
        raise not_found("Case", case_id)
    assert_can_view_case(user, row)
    today = clock.today()
    rules = category_rules(db)
    shaped = shape_row(row, rules, today)
    inst = db.one("SELECT id, name, permanent_id, state, district, region_code, trust_id, demo_tag FROM institutions WHERE id = ?",
                  (row["institution_id"],)) if row["institution_id"] else None
    timeline = db.all("SELECT * FROM case_actions WHERE case_id = ? ORDER BY action_at, id", (case_id,))
    for t in timeline:
        t["doc_ids"] = loads(t.pop("doc_ids_json"), [])
        t["id"] = f"ACT-{t['id']}"
    docs = db.all("SELECT * FROM case_documents WHERE case_id = ? ORDER BY created_at, id", (case_id,))
    for d in docs:
        d["downloadable"] = bool(d.pop("stored_name"))
    links = db.all("SELECT * FROM case_links WHERE (case_a = ? OR case_b = ?) ORDER BY created_at", (case_id, case_id))
    overlaps = db.all("SELECT o.id, o.tier, o.headline, o.status, o.score, o.recommended_lead, o.decided_lead, o.created_at "
                      "FROM overlap_alerts o JOIN overlap_alert_cases oc ON oc.alert_id = o.id WHERE oc.case_id = ? "
                      "ORDER BY o.created_at DESC", (case_id,))
    master = db.one("SELECT * FROM master_cases WHERE id = ?", (row["master_case_id"],)) if row["master_case_id"] else None
    overrides = db.all("SELECT * FROM priority_overrides WHERE case_id = ? ORDER BY created_at", (case_id,))
    officers = db.all("SELECT id, display_name, designation FROM officers WHERE bureau_code = ? AND active = 1 ORDER BY id",
                      (row["bureau_code"],))
    review = db.one("SELECT id, status, best_institution_id, best_confidence FROM match_reviews WHERE source_ref = ? "
                    "ORDER BY created_at DESC LIMIT 1", (case_id,))
    prio = priority_mod.compute_for_case(db, row, today)
    pred = breach.predict(db, row, today)
    return {
        "case": shaped, "institution": inst, "rule": {k: rules[row["category_code"]][k] for k in (
            "code", "label", "family", "severity_level", "severity_weight", "sla_days", "default_bureau")},
        "priority": prio, "sla": sla_state(row, today), "breach": pred, "timeline": timeline, "documents": docs,
        "links": links, "overlap_alerts": overlaps, "master_case": master, "priority_overrides": overrides,
        "officers": officers, "match_review": review,
        "allowed_ops": sorted(allowed_case_ops(user, row)),
        "description": row["description"], "complainant": {
            "count": row["complainant_count"], "type": row["complainant_type"], "evidence_count": row["evidence_count"],
            "evidence_note": row["evidence_note"], "reference_flag": row["reference_flag"], "reference_note": row["reference_note"],
            "note": "Complainant identity is not stored in this prototype (data minimisation)."},
    }
