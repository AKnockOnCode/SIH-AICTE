"""Overlap & Conflict Alerts endpoints: queue, side-by-side detail, link, merge, lead decision, status."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..complaints.queries import BASE_SELECT, shape_row
from ..core import clock
from ..core.api import APIRouter, Ctx
from ..core.constants import ACTION_TYPES
from ..core.schemas import In, Out, PageQuery
from ..core.security import region_scope
from ..core.util import loads
from ..scoring.rules import category_rules
from ..sla.engine import sla_state
from . import detector
from . import service as svc

router = APIRouter("/api", tags=["overlaps"])

Tier = Literal["DUPLICATE", "RELATED", "CONFLICT"]
AStatus = Literal["OPEN", "UNDER_REVIEW", "RESOLVED", "DISMISSED"]


class OverlapFilter(PageQuery):
    tier: list[Tier] | None = None
    status: list[AStatus] | None = None
    q: str | None = Field(None, description="Institution name, alert ID or case ID")
    institution_id: str | None = None
    bureau: str | None = None
    cross_bureau: bool | None = None


class OverlapRow(Out):
    id: str
    institution_id: str
    institution_name: str
    region_code: str | None = None
    tier: str
    headline: str
    score: float
    status: str
    trigger_type: str
    trigger_case_id: str | None = None
    cross_bureau: bool
    bureaus: list[str]
    rules: list[str]
    cases: list[str]
    recommended_lead: str | None = None
    decided_lead: str | None = None
    lead_decision: str | None = None
    next_step: str | None = None
    created_at: str
    updated_at: str
    demo_tag: str | None = None


class OverlapPage(Out):
    items: list[OverlapRow]
    total: int
    page: int
    page_size: int
    counts: dict[str, dict[str, int]]


def _shape(db, row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["bureaus"] = loads(row.pop("bureaus_json"), [])
    row["rules"] = loads(row.pop("rules_json"), [])
    row["cross_bureau"] = bool(row["cross_bureau"])
    row["cases"] = [r["case_id"] for r in db.all("SELECT case_id FROM overlap_alert_cases WHERE alert_id = ? ORDER BY role DESC, case_id",
                                                 (row["id"],))]
    return row


@router.get("/overlaps", query=OverlapFilter, response=OverlapPage, perm="overlap.view")
def list_overlaps(ctx: Ctx, q: OverlapFilter):
    """Searchable overlap queue grouped by tier (DUPLICATE / RELATED / CONFLICT)."""
    where, params = ["1=1"], []
    if q.tier:
        where.append(f"o.tier IN ({','.join('?' for _ in q.tier)})")
        params.extend(q.tier)
    if q.status:
        where.append(f"o.status IN ({','.join('?' for _ in q.status)})")
        params.extend(q.status)
    if q.institution_id:
        where.append("o.institution_id = ?")
        params.append(q.institution_id)
    if q.cross_bureau is not None:
        where.append("o.cross_bureau = ?")
        params.append(int(q.cross_bureau))
    if q.bureau:
        where.append("o.bureaus_json LIKE ?")
        params.append(f'%"{q.bureau}"%')
    if q.q:
        like = f"%{q.q}%"
        where.append("(i.name LIKE ? OR o.id LIKE ? OR EXISTS (SELECT 1 FROM overlap_alert_cases x WHERE x.alert_id = o.id "
                     "AND x.case_id LIKE ?))")
        params.extend([like, like, like])
    scope = region_scope(ctx.user)
    if scope:
        where.append("i.region_code = ?")
        params.append(scope)
    w = " AND ".join(where)
    base = "FROM overlap_alerts o JOIN institutions i ON i.id = o.institution_id"
    total = ctx.db.val(f"SELECT COUNT(*) {base} WHERE {w}", params, 0)
    rows = ctx.db.all(
        f"SELECT o.*, i.name AS institution_name, i.region_code, i.demo_tag {base} WHERE {w} ORDER BY "
        f"CASE o.status WHEN 'OPEN' THEN 0 WHEN 'UNDER_REVIEW' THEN 1 ELSE 2 END, "
        f"CASE o.tier WHEN 'CONFLICT' THEN 0 WHEN 'DUPLICATE' THEN 1 ELSE 2 END, o.score DESC, "
        f"CASE o.trigger_type WHEN 'ACTION_ADDED' THEN 0 WHEN 'CASE_CREATED' THEN 1 ELSE 2 END, o.created_at DESC "
        f"LIMIT ? OFFSET ?", (*params, q.page_size, (q.page - 1) * q.page_size))
    counts: dict[str, dict[str, int]] = {}
    cw, cp = "1=1", []
    if scope:
        cw, cp = "i.region_code = ?", [scope]
    for r in ctx.db.all(f"SELECT o.tier, o.status, COUNT(*) n {base} WHERE {cw} GROUP BY o.tier, o.status", cp):
        counts.setdefault(r["tier"], {})[r["status"]] = r["n"]
    return {"items": [_shape(ctx.db, r) for r in rows], "total": total, "page": q.page, "page_size": q.page_size,
            "counts": counts}


class MemberCase(Out):
    id: str
    role: str
    bureau_code: str
    status: str
    category_code: str
    category_label: str
    severity_level: int
    subject: str
    received_date: str
    officer_name: str | None = None
    assigned_officer_id: str | None = None
    latest_action: str | None = None
    latest_action_at: str | None = None
    latest_actions: list[dict[str, Any]] = []
    next_action: str | None = None
    next_action_due: str | None = None
    sla_label: str
    sla_state: str
    effective_band: str | None = None
    priority_score: float | None = None
    outcome: str | None = None
    disposed_date: str | None = None
    external_ref: str | None = None
    institution_name_raw: str
    match_status: str
    match_confidence: float | None = None
    master_case_id: str | None = None


class OverlapDetail(Out):
    alert: OverlapRow
    institution: dict[str, Any]
    members: list[MemberCase]
    pairs: list[dict[str, Any]]
    trigger: dict[str, Any]
    explanation: str
    recommendation: dict[str, Any]
    links: list[dict[str, Any]]
    master_cases: list[dict[str, Any]]
    duplicate_groups: list[list[str]]
    permissions: dict[str, bool]
    decision: dict[str, Any]
    audit: list[dict[str, Any]]


@router.get("/overlaps/{alert_id}", response=OverlapDetail, perm="overlap.view")
def get_overlap(ctx: Ctx, alert_id: str):
    """Side-by-side comparison: member cases, matched institution, rules/signals, SLA, officers, lead recommendation."""
    db = ctx.db
    alert = svc.get_alert(db, alert_id)
    svc._check_view(ctx.user, alert, db)
    inst = db.one("SELECT id, name, permanent_id, state, district, region_code, trust_id, demo_tag FROM institutions WHERE id = ?",
                  (alert["institution_id"],))
    rules = category_rules(db)
    today = clock.today()
    roles = {r["case_id"]: r["role"] for r in db.all("SELECT case_id, role FROM overlap_alert_cases WHERE alert_id = ?", (alert_id,))}
    ids = sorted(roles)
    members = []
    for r in db.all(f"{BASE_SELECT} WHERE c.id IN ({','.join('?' for _ in ids)})", ids):
        shaped = shape_row(r, rules, today)
        st = sla_state(r, today)
        acts = db.all("SELECT action_type, action_at, actor_label, bureau_code, remarks FROM case_actions WHERE case_id = ? "
                      "ORDER BY action_at DESC, id DESC LIMIT 3", (r["id"],))
        for a in acts:
            a["label"] = ACTION_TYPES.get(a["action_type"], a["action_type"])
        members.append({**shaped, "role": roles[r["id"]], "severity_level": rules[r["category_code"]]["severity_level"],
                        "latest_action": acts[0]["label"] if acts else None,
                        "latest_action_at": acts[0]["action_at"] if acts else None, "latest_actions": acts,
                        "sla_label": st["label"], "sla_state": st["state"]})
    members.sort(key=lambda m: (m["role"] != "TRIGGER", m["bureau_code"], m["received_date"]))
    signals = svc.signals_of(alert)
    links = db.all(f"SELECT * FROM case_links WHERE case_a IN ({','.join('?' for _ in ids)}) AND case_b IN "
                   f"({','.join('?' for _ in ids)}) ORDER BY created_at", (*ids, *ids))
    masters = db.all(f"SELECT DISTINCT m.* FROM master_cases m JOIN master_case_members mm ON mm.master_case_id = m.id "
                     f"WHERE mm.case_id IN ({','.join('?' for _ in ids)}) ORDER BY m.created_at", ids)
    dup_groups = []
    if alert["tier"] == "DUPLICATE":
        dup_groups = [ids]
    user = ctx.user
    member_rows = [m for m in members]
    involved = user.bureau_code is not None and any(m["bureau_code"] == user.bureau_code for m in member_rows)
    same_bureau = {m["bureau_code"] for m in member_rows} == {user.bureau_code}
    perms = {
        "can_act": user.is_authority or (user.has("overlap.act") and (involved or user.role == "REGIONAL_OFFICE")),
        "can_decide": user.is_authority or (alert["tier"] != "CONFLICT" and user.has("overlap.decide") and involved),
        "can_merge_duplicates": alert["tier"] == "DUPLICATE" and (user.is_authority or (user.has("overlap.merge") and same_bureau)),
        "can_create_coordination_master": user.is_authority,
        "can_unmerge": user.is_authority,
    }
    audit = db.all("SELECT seq, ts, actor_label, actor_role, action, remarks FROM audit_events WHERE entity_id = ? "
                   "ORDER BY seq", (alert_id,))
    shaped_alert = _shape(db, {**alert, "institution_name": inst["name"], "region_code": inst["region_code"],
                               "demo_tag": inst["demo_tag"]})
    return {
        "alert": shaped_alert, "institution": inst, "members": members, "pairs": signals.get("pairs", []),
        "trigger": signals.get("trigger", {}), "explanation": signals.get("explanation", ""),
        "recommendation": svc.recommendation_of(alert), "links": links, "master_cases": masters,
        "duplicate_groups": dup_groups, "permissions": perms,
        "decision": {k: alert[k] for k in ("lead_decision", "decided_lead", "decision_remarks", "decided_by", "decided_role",
                                           "decided_at", "status_remarks", "status_by", "status_at")},
        "audit": audit,
    }


class LinkIn(In):
    case_a: str
    case_b: str
    link_type: Tier
    remarks: str | None = Field(None, max_length=1000)


@router.post("/overlaps/{alert_id}/link", body=LinkIn, perm="overlap.act", status_code=201)
def link(ctx: Ctx, alert_id: str, body: LinkIn):
    """Link two member cases (DUPLICATE / RELATED / CONFLICT) for context; audited, reversible."""
    return svc.link_cases(ctx.db, ctx.user, body.case_a, body.case_b, body.link_type, body.remarks, alert_id=alert_id)


class MergeIn(In):
    case_ids: list[str] = Field(..., min_length=1)
    kind: Literal["DUPLICATE_MERGE", "COORDINATION"] = "DUPLICATE_MERGE"
    master_case_id: str | None = None
    title: str | None = Field(None, max_length=200)
    lead_bureau: str | None = None
    remarks: str = Field(..., min_length=5, max_length=1000)


@router.post("/overlaps/{alert_id}/merge", body=MergeIn, perm="overlap.merge", status_code=201)
def merge(ctx: Ctx, alert_id: str, body: MergeIn):
    """Create/extend a Master Case. Originals keep their IDs, history and audit (non-destructive)."""
    return svc.merge(ctx.db, ctx.user, body.case_ids, kind=body.kind, master_case_id=body.master_case_id,
                     title=body.title, lead_bureau=body.lead_bureau, remarks=body.remarks, alert_id=alert_id)


class LeadIn(In):
    decision: Literal["ACCEPT", "OVERRIDE"]
    bureau: str | None = None
    remarks: str | None = Field(None, max_length=1000)


@router.post("/overlaps/{alert_id}/lead", body=LeadIn, perm="overlap.decide")
def decide_lead(ctx: Ctx, alert_id: str, body: LeadIn):
    """Accept or override the recommended lead Bureau/Cell (override needs remarks; no automatic reassignment)."""
    return svc.decide_lead(ctx.db, ctx.user, alert_id, body.decision, body.bureau, body.remarks)


class AlertStatusIn(In):
    status: AStatus
    remarks: str = Field(..., min_length=5, max_length=1000)


@router.post("/overlaps/{alert_id}/status", body=AlertStatusIn, perm="overlap.act")
def set_status(ctx: Ctx, alert_id: str, body: AlertStatusIn):
    """Mark for review, resolve, dismiss or re-open (CONFLICT resolution: Competent Authority only)."""
    return svc.set_status(ctx.db, ctx.user, alert_id, body.status, body.remarks)


class UnlinkIn(In):
    remarks: str = Field(..., min_length=5, max_length=1000)


@router.post("/links/{link_id}/remove", body=UnlinkIn, perm="overlap.act")
def remove_link(ctx: Ctx, link_id: str, body: UnlinkIn):
    """Deactivate a case link (kept in history and audit)."""
    return svc.unlink(ctx.db, ctx.user, link_id, body.remarks)


class MasterDetail(Out):
    master: dict[str, Any]
    membership_history: list[dict[str, Any]]
    cases: list[dict[str, Any]]


@router.get("/master-cases/{master_id}", response=MasterDetail, perm="case.view")
def get_master(ctx: Ctx, master_id: str):
    """Master Case with full membership history (merges and unmerges)."""
    return svc.master_case_detail(ctx.db, master_id)


class UnmergeIn(In):
    case_id: str | None = Field(None, description="Remove one case; omit to dissolve the whole Master Case")
    remarks: str = Field(..., min_length=5, max_length=1000)


@router.post("/master-cases/{master_id}/unmerge", body=UnmergeIn, perm="case.view")
def unmerge(ctx: Ctx, master_id: str, body: UnmergeIn):
    """Safe unmerge: memberships are closed (not deleted); the master dissolves below two members."""
    return svc.unmerge(ctx.db, ctx.user, master_id, body.case_id, body.remarks)


@router.post("/overlaps/scan", perm="system.sweep")
def scan(ctx: Ctx):
    """Re-run the detector over all open cases and recent regulatory actions (Competent Authority)."""
    with ctx.db.tx():
        return detector.scan_all(ctx.db, actor=ctx.user)
