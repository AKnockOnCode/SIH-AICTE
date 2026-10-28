"""Command Dashboard endpoint."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..core.api import APIRouter, Ctx
from ..core.schemas import In, Out
from .service import dashboard

router = APIRouter("/api", tags=["dashboard"])


class DashboardQuery(In):
    date_from: date | None = None
    date_to: date | None = None
    bureau: list[str] | None = None
    region: list[str] | None = None
    state: list[str] | None = None
    category: list[str] | None = None


class Kpis(Out):
    received: int
    pending: int
    under_process: int
    transferred: int
    escalated: int
    disposed: int
    open_total: int
    overdue: int
    disposed_in_time: int
    disposal_rate: float
    sla_compliance: float
    avg_disposal_days: float
    ever_transferred: int
    ever_escalated: int


class BureauLoad(Out):
    code: str
    name: str
    received: int
    pending: int
    under_process: int
    transferred: int
    escalated: int
    disposed: int
    open_total: int
    overdue: int
    officers: int
    open_per_officer: float | None = None


class TrendPoint(Out):
    month: str
    received: int
    disposed: int
    disposal_ratio: float | None = None
    in_time_share: float | None = None


class AgeBucket(Out):
    bucket: str
    count: int
    by_bureau: dict[str, int]


class DashboardOut(Out):
    generated_at: str
    as_of: str
    filters: dict[str, Any]
    data_mode: str
    kpis: Kpis
    by_bureau: list[BureauLoad]
    priority_mix: list[dict[str, Any]]
    by_region: list[dict[str, Any]]
    by_state: list[dict[str, Any]]
    ageing: list[AgeBucket]
    trend: list[TrendPoint]
    by_category: list[dict[str, Any]]
    overlaps: dict[str, Any]
    multi_bureau_institutions: list[dict[str, Any]]
    multi_bureau_count: int
    recent_alerts: list[dict[str, Any]]
    triage: dict[str, Any]
    demo: dict[str, Any]


@router.get("/dashboard", query=DashboardQuery, response=DashboardOut, perm="dashboard.view")
def get_dashboard(ctx: Ctx, q: DashboardQuery):
    """KPIs, Bureau workload, priority mix, region/state, ageing, disposal trend, overlaps and alerts (live SQL)."""
    return dashboard(ctx.db, ctx.user, q.model_dump())
