"""Reports endpoints and audited CSV/XLSX exports (exports use exactly the filters applied)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from starlette.responses import Response

from ..audit import chain
from ..core import clock
from ..core.api import APIRouter, Ctx
from ..core.errors import forbidden
from ..core.provenance import data_disclaimer
from ..core.schemas import In, Out
from ..core.util import safe_filename
from . import service as svc

router = APIRouter("/api", tags=["reports"])

Report = Literal["summary", "ageing", "performance", "sla", "overlaps"]


class ReportQuery(In):
    group_by: Literal["bureau", "region", "state", "institution", "category", "status", "month", "quarter"] = "bureau"
    period: Literal["month", "quarter"] = "month"
    date_from: date | None = None
    date_to: date | None = None
    bureau: list[str] | None = None
    region: list[str] | None = None
    state: list[str] | None = None
    category: list[str] | None = None
    status: list[str] | None = None
    institution_id: str | None = None


class Column(Out):
    key: str
    label: str


class ReportTable(Out):
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    generated_at: str
    filters: dict[str, Any]
    disclaimer: str


def _build(ctx: Ctx, report: str, q: ReportQuery) -> dict[str, Any]:
    f = q.model_dump(exclude={"group_by", "period", "report", "fmt"})
    if report == "summary":
        table = svc.summary(ctx.db, ctx.user, q.group_by, f)
    elif report == "ageing":
        table = svc.ageing(ctx.db, ctx.user, f)
    elif report == "performance":
        table = svc.performance(ctx.db, ctx.user, q.period, f)
    elif report == "sla":
        table = svc.sla_report(ctx.db, ctx.user, f)
    else:
        table = svc.overlaps_report(ctx.db, ctx.user, f)
    table["disclaimer"] = data_disclaimer(ctx.db)
    return table


@router.get("/reports/summary", query=ReportQuery, response=ReportTable, perm="report.view")
def report_summary(ctx: Ctx, q: ReportQuery):
    """Bureau/region/state/institution/category/status/month/quarter summary with disposal rate and SLA compliance."""
    return _build(ctx, "summary", q)


@router.get("/reports/ageing", query=ReportQuery, response=ReportTable, perm="report.view")
def report_ageing(ctx: Ctx, q: ReportQuery):
    """Pending-case ageing buckets by Bureau/Cell."""
    return _build(ctx, "ageing", q)


@router.get("/reports/performance", query=ReportQuery, response=ReportTable, perm="report.view")
def report_performance(ctx: Ctx, q: ReportQuery):
    """Monthly or quarterly received/disposed/SLA-compliance performance."""
    return _build(ctx, "performance", q)


@router.get("/reports/sla", query=ReportQuery, response=ReportTable, perm="report.view")
def report_sla(ctx: Ctx, q: ReportQuery):
    """SLA compliance by Bureau/Cell and category."""
    return _build(ctx, "sla", q)


@router.get("/reports/overlaps", query=ReportQuery, response=ReportTable, perm="report.view")
def report_overlaps(ctx: Ctx, q: ReportQuery):
    """Overlap/duplicate/conflict alert counts and Master Cases."""
    return _build(ctx, "overlaps", q)


class ExportQuery(ReportQuery):
    report: Report = "summary"
    fmt: Literal["csv", "xlsx"] = "csv"


@router.get("/reports/export", query=ExportQuery, perm="report.view", media="text/csv")
def export_report(ctx: Ctx, q: ExportQuery):
    """Download the report (CSV or Excel) with the same filters; the export is audited."""
    if not ctx.user.has("report.export"):
        raise forbidden(f"{ctx.user.role_label} may not export reports.")
    table = _build(ctx, q.report, q)
    stamp = clock.now_iso().replace(":", "").replace("-", "")[:15]
    name = safe_filename(f"agnidrishti_{q.report}_{q.group_by if q.report == 'summary' else q.period}_{stamp}")
    with ctx.db.tx():
        chain.record(ctx.db, ctx.user, "REPORT_EXPORTED", "report", q.report,
                     after={"format": q.fmt, "filters": table["filters"], "rows": len(table["rows"]), "title": table["title"]})
    if q.fmt == "xlsx":
        return Response(svc.to_xlsx(table, ctx.user),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    return Response(svc.to_csv(table, ctx.user).encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
