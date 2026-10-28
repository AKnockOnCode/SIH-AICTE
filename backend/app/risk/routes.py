"""Risk Index, forecast, watch-list and trust/society graph endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..core import clock
from ..core.api import APIRouter, Ctx
from ..core.schemas import In, Out
from ..core.security import region_scope
from ..graph.service import build as build_graph
from . import index as risk_index
from . import watchlist

router = APIRouter("/api", tags=["risk"])

DISCLAIMER = ("SYNTHETIC DATA — risk scores, trends and forecasts are computed from synthetic complaint history; "
              "they are decision-support indicators, not AICTE findings about any institution.")


class RiskRow(Out):
    institution_id: str
    name: str
    region_code: str
    state: str
    score: float
    band: str
    delta_6m: float
    trend: str
    confidence: str
    forecast_probability: float
    forecast_status: str
    forecast_trend: str
    cases_considered: int


class RiskList(Out):
    as_of: str
    items: list[RiskRow]
    pooled_forecast_params: dict[str, Any]
    bands: dict[str, float] = {}
    disclaimer: str = DISCLAIMER


class RiskQuery(In):
    region: list[str] | None = None
    band: list[Literal["HIGH", "ELEVATED", "NORMAL"]] | None = None


@router.get("/risk", query=RiskQuery, response=RiskList, perm="risk.view")
def list_risk(ctx: Ctx, q: RiskQuery):
    """Risk Index for all visible institutions, highest first."""
    from ..scoring.rules import get_settings_block

    data = risk_index.compute_all(ctx.db, clock.today())
    scope = region_scope(ctx.user)
    meta = {i["id"]: i for i in ctx.db.all("SELECT id, name, region_code, state FROM institutions")}
    rows = []
    for iid, r in data["institutions"].items():
        m = meta[iid]
        if scope and m["region_code"] != scope:
            continue
        if q.region and m["region_code"] not in q.region:
            continue
        if q.band and r["band"] not in q.band:
            continue
        rows.append({"institution_id": iid, "name": m["name"], "region_code": m["region_code"], "state": m["state"],
                     "score": r["score"], "band": r["band"], "delta_6m": r["delta_6m"], "trend": r["trend"],
                     "confidence": r["confidence"], "forecast_probability": r["forecast"]["probability"],
                     "forecast_status": r["forecast"]["status"], "forecast_trend": r["forecast"]["trend"],
                     "cases_considered": r["components"]["cases_considered"]})
    rows.sort(key=lambda x: -x["score"])
    return {"as_of": data["as_of"], "items": rows, "pooled_forecast_params": data["pooled"],
            "bands": get_settings_block(ctx.db, "risk")["bands"]}


class WatchReason(Out):
    code: str
    label: str


class WatchInstitution(Out):
    institution_id: str
    name: str
    state: str
    district: str | None = None
    region_code: str
    trust_id: str | None = None
    trust_name: str | None = None
    demo_tag: str | None = None
    reasons: list[WatchReason]
    attention_score: int
    risk_score: float
    risk_band: str
    trend: str
    delta_6m: float
    risk_confidence: str
    forecast_probability: float
    forecast_interval: list[float]
    forecast_status: str
    forecast_confidence: str
    open_cases: int
    overdue_cases: int
    last_activity: str | None = None
    next_review: str


class WatchCase(Out):
    case_id: str
    institution_id: str | None = None
    institution_name: str | None = None
    bureau_code: str
    category_code: str
    status: str
    due_date: str
    days_remaining: int
    probability: float
    band: str
    top_factor: str | None = None
    historical: str | None = None
    priority_band: str | None = None


class WatchlistOut(Out):
    as_of: str
    institutions: list[WatchInstitution]
    cases: list[WatchCase]
    reason_counts: dict[str, int]
    disclaimer: str = DISCLAIMER


class WatchQuery(In):
    reason: list[str] | None = Field(None, description="Filter by reason code, e.g. HIGH_RISK, RISING_RISK, CONFLICT")
    region: list[str] | None = None


@router.get("/watchlist", query=WatchQuery, response=WatchlistOut, perm="risk.view")
def get_watchlist(ctx: Ctx, q: WatchQuery):
    """Institutions needing attention (with reasons and next review date) and open cases likely to breach SLA."""
    today = clock.today()
    insts = watchlist.institutions(ctx.db, ctx.user, today)
    counts: dict[str, int] = {}
    for i in insts:
        for r in i["reasons"]:
            counts[r["code"]] = counts.get(r["code"], 0) + 1
    if q.reason:
        insts = [i for i in insts if any(r["code"] in q.reason for r in i["reasons"])]
    if q.region:
        insts = [i for i in insts if i["region_code"] in q.region]
    return {"as_of": today.isoformat(), "institutions": insts, "cases": watchlist.cases_at_risk(ctx.db, ctx.user, today),
            "reason_counts": counts}


class GraphQuery(In):
    trust_id: str | None = None
    hide_standalone: bool = False


class GraphOut(Out):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    groups: list[dict[str, Any]]
    stats: dict[str, int]
    legend: dict[str, str]
    provenance: str


@router.get("/graph", query=GraphQuery, response=GraphOut, perm="graph.view", tags=["graph"])
def get_graph(ctx: Ctx, q: GraphQuery):
    """Trust/society graph (NetworkX): stored OPERATED_BY relationships, risk/case indicators, group patterns."""
    return build_graph(ctx.db, ctx.user, clock.today(), min_members=2 if q.hide_standalone else 1, trust_id=q.trust_id)
