"""Audit trail search and hash-chain verification."""

from __future__ import annotations

from datetime import date

from ..core.api import APIRouter, Ctx
from ..core.schemas import In, Out, PageQuery
from . import chain

router = APIRouter("/api", tags=["audit"])


class AuditFilter(PageQuery):
    date_from: date | None = None
    date_to: date | None = None
    actor: str | None = None
    role: list[str] | None = None
    action: str | None = None
    entity_id: str | None = None
    bureau: str | None = None


class AuditRow(Out):
    seq: int
    event_id: str
    ts: str
    actor_id: str | None = None
    actor_label: str | None = None
    actor_role: str | None = None
    actor_bureau: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    before_json: str | None = None
    after_json: str | None = None
    remarks: str | None = None
    payload_hash: str
    prev_hash: str
    hash: str


class AuditPage(Out):
    items: list[AuditRow]
    total: int
    page: int
    page_size: int
    actions: list[str]
    note: str = ("Tamper-evident within this prototype: each event hashes its content and the previous hash. "
                 "Whoever controls the database file could rewrite the whole chain; production needs an external anchor "
                 "(e.g. periodic publication of the head hash or WORM storage).")


@router.get("/audit", query=AuditFilter, response=AuditPage, perm="audit.view")
def list_audit(ctx: Ctx, q: AuditFilter):
    """Search audit events by date, actor, role, action, entity and Bureau/Cell."""
    where, p = ["1=1"], []
    if q.date_from:
        where.append("ts >= ?")
        p.append(q.date_from.isoformat())
    if q.date_to:
        where.append("ts <= ?")
        p.append(q.date_to.isoformat() + "T23:59:59.999999Z")
    if q.actor:
        where.append("(actor_id LIKE ? OR actor_label LIKE ?)")
        p.extend([f"%{q.actor}%"] * 2)
    if q.role:
        where.append(f"actor_role IN ({','.join('?' for _ in q.role)})")
        p.extend(q.role)
    if q.action:
        where.append("action LIKE ?")
        p.append(f"%{q.action}%")
    if q.entity_id:
        where.append("entity_id LIKE ?")
        p.append(f"%{q.entity_id}%")
    if q.bureau:
        where.append("actor_bureau = ?")
        p.append(q.bureau)
    w = " AND ".join(where)
    total = ctx.db.val(f"SELECT COUNT(*) FROM audit_events WHERE {w}", p, 0)
    rows = ctx.db.all(f"SELECT * FROM audit_events WHERE {w} ORDER BY seq DESC LIMIT ? OFFSET ?",
                      (*p, q.page_size, (q.page - 1) * q.page_size))
    actions = [r["action"] for r in ctx.db.all("SELECT DISTINCT action FROM audit_events ORDER BY action")]
    return {"items": rows, "total": total, "page": q.page, "page_size": q.page_size, "actions": actions}


class VerifyOut(Out):
    ok: bool
    checked: int
    first_bad_seq: int | None = None
    reason: str | None = None
    head_hash: str | None = None
    last_good_seq: int | None = None


class VerifyIn(In):
    record: bool = True


@router.post("/audit/verify", response=VerifyOut, perm="audit.verify")
def verify(ctx: Ctx):
    """Recompute the full hash chain; the verification itself is recorded."""
    result = chain.verify(ctx.db)
    with ctx.db.tx():
        chain.record(ctx.db, ctx.user, "AUDIT_VERIFIED", "audit_chain", None, after={k: result[k] for k in ("ok", "checked",
                     "first_bad_seq")})
    return result
