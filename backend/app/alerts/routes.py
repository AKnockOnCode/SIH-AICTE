"""Alerts Centre endpoints (in-app only; no email/SMS delivery is configured or claimed)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from ..core.api import APIRouter, Ctx
from ..core.schemas import In, Out, PageQuery
from . import service as svc

router = APIRouter("/api", tags=["alerts"])


class AlertFilter(PageQuery):
    alert_type: list[str] | None = None
    severity: list[Literal["CRITICAL", "WARNING", "INFO"]] | None = None
    state: list[Literal["NEW", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"]] | None = None
    case_id: str | None = None
    institution_id: str | None = None
    q: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class AlertRow(Out):
    id: str
    alert_type: str
    severity: str
    title: str
    message: str
    institution_id: str | None = None
    institution_name: str | None = None
    case_id: str | None = None
    overlap_alert_id: str | None = None
    target_bureau: str | None = None
    target_region: str | None = None
    state: str
    channel: str
    created_at: str
    updated_at: str
    acted_by: str | None = None
    acted_role: str | None = None
    acted_at: str | None = None
    action_remarks: str | None = None


class AlertPage(Out):
    items: list[AlertRow]
    total: int
    page: int
    page_size: int
    counts: dict[str, dict[str, int]]
    unread: int
    delivery_note: str = "In-app alerts only. No email or SMS provider is configured in this prototype."


@router.get("/alerts", query=AlertFilter, response=AlertPage, perm="alert.view")
def list_alerts(ctx: Ctx, q: AlertFilter):
    """Alerts addressed to the current role (Bureau or region), newest and most severe first."""
    clause, params = svc.visible_clause(ctx.user)
    where, p = [clause], list(params)
    for col, values in (("a.alert_type", q.alert_type), ("a.severity", q.severity), ("a.state", q.state)):
        if values:
            where.append(f"{col} IN ({','.join('?' for _ in values)})")
            p.extend(values)
    if q.case_id:
        where.append("a.case_id = ?")
        p.append(q.case_id)
    if q.institution_id:
        where.append("a.institution_id = ?")
        p.append(q.institution_id)
    if q.q:
        where.append("(a.title LIKE ? OR a.message LIKE ? OR a.case_id LIKE ?)")
        p.extend([f"%{q.q}%"] * 3)
    if q.date_from:
        where.append("a.created_at >= ?")
        p.append(q.date_from.isoformat())
    if q.date_to:
        where.append("a.created_at <= ?")
        p.append(q.date_to.isoformat() + "T23:59:59Z")
    w = " AND ".join(where)
    base = "FROM alerts a LEFT JOIN institutions i ON i.id = a.institution_id"
    total = ctx.db.val(f"SELECT COUNT(*) {base} WHERE {w}", p, 0)
    rows = ctx.db.all(f"SELECT a.*, i.name AS institution_name {base} WHERE {w} ORDER BY "
                      f"CASE a.state WHEN 'NEW' THEN 0 WHEN 'ACKNOWLEDGED' THEN 1 ELSE 2 END, "
                      f"CASE a.severity WHEN 'CRITICAL' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END, a.created_at DESC "
                      f"LIMIT ? OFFSET ?", (*p, q.page_size, (q.page - 1) * q.page_size))
    counts: dict[str, dict[str, int]] = {}
    for r in ctx.db.all(f"SELECT a.alert_type, a.state, COUNT(*) n {base} WHERE {clause} GROUP BY a.alert_type, a.state", params):
        counts.setdefault(r["alert_type"], {})[r["state"]] = r["n"]
    unread = ctx.db.val(f"SELECT COUNT(*) {base} WHERE {clause} AND a.state = 'NEW'", params, 0)
    return {"items": rows, "total": total, "page": q.page, "page_size": q.page_size, "counts": counts, "unread": unread}


class AlertActionIn(In):
    action: Literal["ACKNOWLEDGE", "RESOLVE", "DISMISS", "REOPEN"]
    remarks: str | None = Field(None, max_length=1000)


@router.post("/alerts/{alert_id}/act", body=AlertActionIn, perm="alert.act")
def act(ctx: Ctx, alert_id: str, body: AlertActionIn):
    """Acknowledge / resolve / dismiss / re-open an alert (persisted and audited)."""
    return svc.act(ctx.db, ctx.user, alert_id, body.action, body.remarks)


class SweepOut(Out):
    overdue: int
    due_soon: int
    predicted: int
    reminders: int
    escalations: int
    match_reviews: int
    auto_resolved: int
    audit_warning: int


@router.post("/alerts/sweep", response=SweepOut, perm="system.sweep")
def run_sweep(ctx: Ctx):
    """Recompute SLA/reminder/predicted-breach/escalation alerts now (idempotent)."""
    return svc.sweep(ctx.db)
