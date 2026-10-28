"""System endpoints: health, status/mode, demo identity, permissions, reference data, global search."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .. import __version__
from ..audit import chain
from ..core import clock
from ..core.api import APIRouter, Ctx
from ..core.config import get_settings
from ..core.constants import (
    ACTION_TYPES,
    CHANNELS,
    MANUAL_ACTIONS,
    OUTCOME_LABELS,
    REGULATORY_ACTIONS,
    STATUS_LABELS,
)
from ..core.provenance import data_disclaimer
from ..core.schemas import In, Out
from ..core.security import ROLE_LABELS, ROLE_PERMISSIONS, permission_matrix, region_scope
from ..core.util import loads
from ..institutions import matcher
from ..scoring import classifier
from ..scoring.rules import SEVERITY_LABELS, category_rules

router = APIRouter("/api", tags=["system"])


class Health(Out):
    status: str
    version: str
    today: str


@router.get("/health", response=Health)
def health(ctx: Ctx):
    """Liveness check."""
    return {"status": "ok", "version": __version__, "today": clock.today().isoformat()}


class DemoUserOut(Out):
    id: str
    display_name: str
    role: str
    role_label: str
    bureau_code: str | None = None
    region_code: str | None = None
    officer_id: str | None = None
    description: str | None = None


class MeOut(Out):
    user: DemoUserOut
    permissions: list[str]
    region_scope: str | None = None
    notice: str = "Prototype role simulation via the X-Demo-User header — not real authentication."


@router.get("/system/me", response=MeOut)
def me(ctx: Ctx):
    """The active demo user and its permissions (server-side source of truth)."""
    u = ctx.user
    row = ctx.db.one("SELECT * FROM demo_users WHERE id = ?", (u.id,))
    return {"user": {**row, "role_label": u.role_label}, "permissions": sorted(ROLE_PERMISSIONS.get(u.role, [])),
            "region_scope": region_scope(u)}


@router.get("/system/users", response=list[DemoUserOut])
def users(ctx: Ctx):
    """Demo users for the role switcher (prototype simulation)."""
    rows = ctx.db.all("SELECT * FROM demo_users ORDER BY sort_order")
    return [{**r, "role_label": ROLE_LABELS[r["role"]]} for r in rows]


class PermRow(Out):
    permission: str
    description: str
    roles: dict[str, bool]


@router.get("/system/permissions", response=list[PermRow])
def permissions(ctx: Ctx):
    """Permission matrix enforced by the backend."""
    return permission_matrix()


class Reference(Out):
    bureaus: list[dict[str, Any]]
    regions: list[dict[str, Any]]
    states: list[dict[str, Any]]
    categories: list[dict[str, Any]]
    officers: list[dict[str, Any]]
    statuses: dict[str, str]
    outcomes: dict[str, str]
    action_types: dict[str, str]
    manual_actions: list[str]
    regulatory_actions: list[str]
    channels: dict[str, str]
    severity_labels: dict[str, str]
    trusts: list[dict[str, Any]]
    disclaimer: str
    today: str
    date_frozen: bool


@router.get("/system/reference", response=Reference)
def reference(ctx: Ctx):
    """Vocabularies for forms and filters (bureaus, regions, states, categories, officers, statuses ...)."""
    db = ctx.db
    cats = [{k: v for k, v in r.items()} for r in category_rules(db).values()]
    return {
        "bureaus": db.all("SELECT code, name, kind, description FROM bureaus ORDER BY sort_order"),
        "regions": db.all("SELECT code, name FROM regions ORDER BY sort_order"),
        "states": db.all("SELECT name, region_code FROM states ORDER BY name"),
        "categories": cats,
        "officers": db.all("SELECT id, display_name, designation, bureau_code, region_code FROM officers WHERE active = 1 ORDER BY id"),
        "statuses": STATUS_LABELS, "outcomes": OUTCOME_LABELS, "action_types": ACTION_TYPES,
        "manual_actions": MANUAL_ACTIONS, "regulatory_actions": REGULATORY_ACTIONS, "channels": CHANNELS,
        "severity_labels": {str(k): v for k, v in SEVERITY_LABELS.items()},
        "trusts": db.all("SELECT id, name, state FROM trusts ORDER BY name"),
        "disclaimer": data_disclaimer(db),
        "today": clock.today().isoformat(), "date_frozen": bool(get_settings().today_override),
    }


class StatusOut(Out):
    app: dict[str, Any]
    data: dict[str, Any]
    models: dict[str, Any]
    llm: dict[str, Any]
    audit: dict[str, Any]
    imports: dict[str, Any]
    disclaimer: str


@router.get("/system/status", response=StatusOut, perm="audit.view")
def status(ctx: Ctx):
    """Application/data/model mode, local model status, optional LLM availability (no key exposed), seed and import info."""
    db = ctx.db
    s = get_settings()
    seed = db.one("SELECT * FROM seed_runs ORDER BY id DESC LIMIT 1")
    counts = {t: db.val(f"SELECT COUNT(*) FROM {t}", default=0) for t in (
        "institutions", "complaints", "case_actions", "overlap_alerts", "alerts", "audit_events", "public_signals",
        "match_reviews", "master_cases", "import_jobs")}
    real = db.val("SELECT COUNT(*) FROM complaints WHERE is_synthetic = 0", default=0)
    matcher_model = matcher.load_model()
    breach_meta = None
    bpath = s.models_dir / "breach_model.json"
    if bpath.exists():
        breach_meta = loads(bpath.read_text(encoding="utf-8"))
    last_import = db.one("SELECT id, kind, file_name, status, committed_at, uploaded_by, uploaded_role FROM import_jobs "
                         "ORDER BY created_at DESC LIMIT 1")
    head = db.one("SELECT seq, hash, ts FROM audit_events ORDER BY seq DESC LIMIT 1")
    return {
        "app": {"name": "AgniDrishti", "version": __version__, "today": clock.today().isoformat(),
                "date_frozen": bool(s.today_override), "database": "SQLite (local file)",
                "api_framework": "Starlette + Pydantic (FastAPI-style typed routes, OpenAPI 3.1)", "offline": True},
        "data": {"mode": "SYNTHETIC" if real == 0 else "SYNTHETIC + USER-ENTERED/IMPORTED", "counts": counts,
                 "non_synthetic_cases": real,
                 "seed": {"seed": seed["seed"], "anchor_date": seed["anchor_date"], "generator_version": seed["generator_version"],
                          "fingerprint": seed["fingerprint"], "created_at": seed["created_at"]} if seed else None},
        "models": {
            "classifier": classifier.status(),
            "matcher": {"available": matcher_model is not None,
                        **({"trained_at": matcher_model["trained_at"], "metrics": matcher_model["metrics"]} if matcher_model else {})},
            "breach": {"available": breach_meta is not None, **(breach_meta or {})},
            "risk": {"method": "severity x recency decay x outcome factor, intake-normalised, empirical-Bayes shrinkage"},
            "forecast": {"method": "univariate Hawkes (exponential kernel) MLE with pooled/baseline fallbacks"},
        },
        "llm": {"configured": s.llm_enabled, "model": s.anthropic_model if s.llm_enabled else None,
                "used_for": ["optional dossier narrative wording", "optional category suggestion"],
                "note": "Optional. Core features never require it; the key stays on the server."},
        "audit": {"events": counts["audit_events"], "head_seq": head["seq"] if head else 0,
                  "head_hash": head["hash"] if head else chain.GENESIS_HASH, "last_event_at": head["ts"] if head else None},
        "imports": {"last": last_import},
        "disclaimer": data_disclaimer(db),
    }


class SearchQuery(In):
    q: str = Field(..., min_length=2, max_length=200)


class SearchOut(Out):
    query: str
    institutions: list[dict[str, Any]]
    cases: list[dict[str, Any]]
    master_cases: list[dict[str, Any]]
    note: str


@router.get("/search", query=SearchQuery, response=SearchOut, perm="case.view", tags=["search"])
def search(ctx: Ctx, q: SearchQuery):
    """Global search: institutions (fuzzy via entity resolution, uncertain matches labelled), cases and Master Cases."""
    db = ctx.db
    text = q.q.strip()
    scope = region_scope(ctx.user)
    res = matcher.match(db, matcher.Query(text), limit=6)
    inst_hits: dict[str, dict[str, Any]] = {}
    for c in res["candidates"]:
        if c["confidence"] >= 0.15:
            inst_hits[c["institution_id"]] = {"id": c["institution_id"], "name": c["name"], "permanent_id": c["permanent_id"],
                                              "state": c["state"], "confidence": c["confidence"], "band": c["band"],
                                              "match": "FUZZY", "uncertain": c["band"] != "HIGH"}
    for r in db.all("SELECT DISTINCT i.id, i.name, i.permanent_id, i.state FROM institutions i LEFT JOIN institution_aliases a "
                    "ON a.institution_id = i.id WHERE i.permanent_id = ? OR i.name LIKE ? OR a.alias LIKE ? LIMIT 10",
                    (text.upper(), f"%{text}%", f"%{text}%")):
        exact = r["permanent_id"] == text.upper()
        inst_hits[r["id"]] = {**r, "confidence": 1.0, "band": "HIGH", "match": "PERMANENT_ID" if exact else "TEXT",
                              "uncertain": False}
    if scope:
        allowed = {r["id"] for r in db.all("SELECT id FROM institutions WHERE region_code = ?", (scope,))}
        inst_hits = {k: v for k, v in inst_hits.items() if k in allowed}
    where = "(c.id LIKE ? OR c.source_ref LIKE ? OR c.external_ref LIKE ? OR c.subject LIKE ?)"
    params: list[Any] = [f"%{text}%"] * 4
    if scope:
        where += " AND c.region_code = ?"
        params.append(scope)
    cases = db.all(f"SELECT c.id, c.subject, c.status, c.bureau_code, c.received_date, c.institution_id, i.name institution_name "
                   f"FROM complaints c LEFT JOIN institutions i ON i.id = c.institution_id WHERE {where} "
                   f"ORDER BY CASE WHEN c.id = ? THEN 0 ELSE 1 END, c.received_date DESC LIMIT 15", (*params, text.upper()))
    masters = db.all("SELECT id, title, status, institution_id FROM master_cases WHERE id LIKE ? OR title LIKE ? LIMIT 5",
                     (f"%{text}%", f"%{text}%"))
    ranked = sorted(inst_hits.values(), key=lambda x: -x["confidence"])[:8]
    return {"query": text, "institutions": ranked, "cases": cases, "master_cases": masters,
            "note": "Institution matches below the auto-link threshold are labelled uncertain (confidence, not certainty)."}
