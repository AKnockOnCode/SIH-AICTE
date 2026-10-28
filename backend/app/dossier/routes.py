"""Pre-decision dossier endpoints (JSON for the printable view, and PDF)."""

from __future__ import annotations

from typing import Any, Literal

from starlette.responses import Response

from ..audit import chain
from ..core.api import APIRouter, Ctx
from ..core.schemas import In, Out
from ..core.util import safe_filename
from . import pdf
from . import service as svc

router = APIRouter("/api", tags=["dossier"])


class DossierQuery(In):
    narrative: Literal["template", "ai"] = "template"


class DossierOut(Out):
    institution: dict[str, Any]
    aliases: list[str]
    summary: dict[str, Any]
    open_cases: list[dict[str, Any]]
    case_history: list[dict[str, Any]]
    recent_actions: list[dict[str, Any]]
    overlaps: list[dict[str, Any]]
    risk: dict[str, Any] | None = None
    pending_sla: list[dict[str, Any]]
    predicted_breaches: list[dict[str, Any]]
    escalations: list[dict[str, Any]]
    recommendations: list[str]
    public_signals: list[dict[str, Any]]
    narrative: dict[str, Any]
    provenance: dict[str, Any]
    disclaimer: str


def _audit(ctx: Ctx, inst_id: str, fmt: str, source: str) -> None:
    with ctx.db.tx():
        chain.record(ctx.db, ctx.user, "DOSSIER_GENERATED", "institution", inst_id, after={"format": fmt, "narrative": source})


@router.get("/institutions/{inst_id}/dossier", query=DossierQuery, response=DossierOut, perm="dossier.view")
def get_dossier(ctx: Ctx, inst_id: str, q: DossierQuery):
    """Structured dossier (deterministic template narrative; optional validated AI wording if a key is configured)."""
    d = svc.build(ctx.db, ctx.user, inst_id, q.narrative)
    _audit(ctx, inst_id, "json", d["narrative"]["source"])
    return d


@router.get("/institutions/{inst_id}/dossier.pdf", query=DossierQuery, perm="dossier.view", media="application/pdf")
def get_dossier_pdf(ctx: Ctx, inst_id: str, q: DossierQuery):
    """Download the dossier as a PDF (rendered locally with ReportLab)."""
    d = svc.build(ctx.db, ctx.user, inst_id, q.narrative)
    data = pdf.render(d)
    _audit(ctx, inst_id, "pdf", d["narrative"]["source"])
    name = safe_filename(f"AgniDrishti_dossier_{inst_id}_{d['provenance']['as_of']}.pdf")
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})
