"""Case endpoints: search/list, detail, intake preview/create, workflow operations, documents."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field
from starlette.responses import FileResponse

from ..core.api import APIRouter, Ctx
from ..core.config import get_settings
from ..core.errors import bad_request, not_found
from ..core.schemas import BreachPrediction, CasePage, CaseRow, In, Out, PageQuery, PriorityExplanation, SlaState
from ..core.security import assert_can_view_case
from ..core.util import safe_filename
from ..workflow import service as wf
from . import queries
from . import service as svc

router = APIRouter("/api", tags=["cases"])

Status = Literal["RECEIVED", "PENDING", "UNDER_PROCESS", "TRANSFERRED", "ESCALATED", "DISPOSED"]
Band = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class CaseFilter(PageQuery):
    q: str | None = Field(None, description="Free text: case ID, source/external reference, subject, institution")
    case_id: str | None = None
    institution_id: str | None = None
    institution: str | None = Field(None, description="Institution name/alias (fuzzy, via entity resolution)")
    permanent_id: str | None = None
    bureau: list[str] | None = None
    region: list[str] | None = None
    state: list[str] | None = None
    category: list[str] | None = None
    status: list[Status] | None = None
    priority: list[Band] | None = None
    match_status: list[str] | None = None
    overdue: bool | None = None
    open_only: bool | None = None
    has_overlap: bool | None = None
    synthetic: bool | None = None
    date_from: date | None = None
    date_to: date | None = None
    master_case_id: str | None = None
    demo_tag: str | None = None
    sort: Literal["received_desc", "received_asc", "priority_desc", "due_asc", "id", "status"] = "received_desc"


@router.get("/cases", query=CaseFilter, response=CasePage, perm="case.view")
def list_cases(ctx: Ctx, q: CaseFilter):
    """Search cases by any combination of the required filters (paginated)."""
    f = q.model_dump(exclude={"page", "page_size", "sort"})
    return queries.list_cases(ctx.db, ctx.user, f, q.page, q.page_size, q.sort)


class TimelineEntry(Out):
    id: str
    action_type: str
    action_at: str
    actor_label: str
    actor_role: str | None = None
    bureau_code: str | None = None
    officer_id: str | None = None
    remarks: str | None = None
    from_value: str | None = None
    to_value: str | None = None
    next_action: str | None = None
    next_action_due: str | None = None
    doc_ids: list[str] = []
    is_synthetic: int = 0


class DocumentOut(Out):
    id: str
    doc_type: str
    title: str
    reference_no: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    added_by: str | None = None
    added_role: str | None = None
    created_at: str
    downloadable: bool = False
    is_synthetic: int = 0


class LinkOut(Out):
    id: str
    case_a: str
    case_b: str
    link_type: str
    overlap_alert_id: str | None = None
    active: int
    remarks: str | None = None
    created_by: str | None = None
    created_at: str
    removed_by: str | None = None
    removed_at: str | None = None
    removed_remarks: str | None = None


class CaseOverlapRef(Out):
    id: str
    tier: str
    headline: str
    status: str
    score: float
    recommended_lead: str | None = None
    decided_lead: str | None = None
    created_at: str


class OfficerOut(Out):
    id: str
    display_name: str
    designation: str


class CaseDetail(Out):
    case: CaseRow
    description: str
    institution: dict[str, Any] | None = None
    rule: dict[str, Any]
    priority: PriorityExplanation
    sla: SlaState
    breach: BreachPrediction
    timeline: list[TimelineEntry]
    documents: list[DocumentOut]
    links: list[LinkOut]
    overlap_alerts: list[CaseOverlapRef]
    master_case: dict[str, Any] | None = None
    priority_overrides: list[dict[str, Any]]
    officers: list[OfficerOut]
    match_review: dict[str, Any] | None = None
    allowed_ops: list[str]
    complainant: dict[str, Any]


@router.get("/cases/{case_id}", response=CaseDetail, perm="case.view")
def get_case(ctx: Ctx, case_id: str):
    """Case detail: fields, priority 'why' chips, SLA facts, breach prediction, timeline, links, permitted operations."""
    return queries.case_detail(ctx.db, ctx.user, case_id)


class EvidenceRef(In):
    title: str = Field(..., min_length=3, max_length=200)
    reference_no: str | None = Field(None, max_length=100)


class IntakeIn(In):
    institution_name: str = Field(..., min_length=3, max_length=300)
    permanent_id: str | None = Field(None, max_length=40)
    address: str | None = Field(None, max_length=300)
    pincode: str | None = Field(None, max_length=10)
    state: str | None = Field(None, max_length=60)
    district: str | None = Field(None, max_length=60)
    category_code: str
    subject: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=20, max_length=5000)
    received_date: date
    bureau_code: str
    channel: str = "INTAKE"
    source_ref: str | None = Field(None, max_length=60)
    external_ref: str | None = Field(None, max_length=60)
    complainant_count: int = Field(1, ge=1, le=100000)
    complainant_type: str = "STUDENT"
    evidence_count: int = Field(0, ge=0, le=500)
    evidence_note: str | None = Field(None, max_length=500)
    evidence_refs: list[EvidenceRef] = []
    reference_flag: Literal["NONE", "COURT", "VIP", "PARLIAMENT"] = "NONE"
    reference_note: str | None = Field(None, max_length=300)
    assigned_officer_id: str | None = None
    institution_id: str | None = None
    match_decision: Literal["CONFIRM", "CREATE", "UNMATCHED"] = "CONFIRM"
    acknowledge_duplicates: bool = False


class IntakePreview(Out):
    institution_match: dict[str, Any]
    selected_institution: dict[str, Any] | None = None
    priority: PriorityExplanation
    ml_suggestion: dict[str, Any]
    sla: dict[str, Any]
    potential_overlaps: list[dict[str, Any]]
    duplicate_warning: bool
    duplicates: list[dict[str, Any]]
    open_cases_at_institution: list[dict[str, Any]]


class OverlapRef(Out):
    alert_id: str
    tier: str
    created: bool
    cases: list[str]


class CreatedCase(Out):
    case_id: str
    institution_id: str | None = None
    match_status: str
    overlap_alerts: list[OverlapRef]


def _intake_dict(body: IntakeIn) -> dict[str, Any]:
    d = body.model_dump()
    d["evidence_refs"] = [e for e in d["evidence_refs"]]
    return d


@router.post("/cases/preview", body=IntakeIn, response=IntakePreview, perm="case.create")
def preview_case(ctx: Ctx, body: IntakeIn):
    """Live intake check: institution candidates, priority estimate with reasons, possible duplicates/overlaps."""
    return svc.preview(ctx.db, ctx.user, _intake_dict(body))


@router.post("/cases", body=IntakeIn, response=CreatedCase, perm="case.create", status_code=201)
def create_case(ctx: Ctx, body: IntakeIn):
    """Register a complaint (audited); runs overlap detection immediately."""
    return svc.create(ctx.db, ctx.user, _intake_dict(body))


class ActionIn(In):
    action_type: str
    remarks: str | None = Field(None, max_length=2000)
    next_action: str | None = Field(None, max_length=300)
    next_action_due: date | None = None


class ActionResult(Out):
    action_id: int
    case_id: str
    overlap_alerts: list[OverlapRef] = []


@router.post("/cases/{case_id}/actions", body=ActionIn, response=ActionResult, perm="case.update")
def add_action(ctx: Ctx, case_id: str, body: ActionIn):
    """Add a timeline action (remark, notice, reply, inspection, hearing, scrutiny or a regulatory action)."""
    return wf.add_action(ctx.db, ctx.user, case_id, body.action_type, body.remarks, body.next_action,
                         body.next_action_due)


class StatusIn(In):
    status: Status
    remarks: str | None = Field(None, max_length=2000)


@router.post("/cases/{case_id}/status", body=StatusIn, perm="case.update")
def change_status(ctx: Ctx, case_id: str, body: StatusIn):
    """Change status within the allowed transitions (transfer/escalate/dispose have their own endpoints)."""
    return wf.change_status(ctx.db, ctx.user, case_id, body.status, body.remarks)


class AssignIn(In):
    officer_id: str
    remarks: str | None = Field(None, max_length=2000)


@router.post("/cases/{case_id}/assign", body=AssignIn, perm="case.update")
def assign(ctx: Ctx, case_id: str, body: AssignIn):
    """Assign or reassign the officer (must belong to the case's Bureau/Cell)."""
    return wf.assign(ctx.db, ctx.user, case_id, body.officer_id, body.remarks)


class TransferIn(In):
    to_bureau: str
    remarks: str = Field(..., min_length=5, max_length=2000)


@router.post("/cases/{case_id}/transfer", body=TransferIn, perm="case.transfer")
def transfer(ctx: Ctx, case_id: str, body: TransferIn):
    """Transfer to another Bureau/Cell (remarks mandatory)."""
    return wf.transfer(ctx.db, ctx.user, case_id, body.to_bureau, body.remarks)


class RemarksIn(In):
    remarks: str = Field(..., min_length=5, max_length=2000)


@router.post("/cases/{case_id}/escalate", body=RemarksIn, perm="case.escalate")
def escalate(ctx: Ctx, case_id: str, body: RemarksIn):
    """Escalate to the Competent Authority (remarks mandatory)."""
    return wf.escalate(ctx.db, ctx.user, case_id, body.remarks)


@router.post("/cases/{case_id}/deescalate", body=RemarksIn, perm="case.update")
def deescalate(ctx: Ctx, case_id: str, body: RemarksIn):
    """Review an escalation and return the case to processing (Competent Authority)."""
    return wf.deescalate(ctx.db, ctx.user, case_id, body.remarks)


class DisposeIn(In):
    outcome: Literal["SUBSTANTIATED", "PARTIALLY_SUBSTANTIATED", "UNSUBSTANTIATED", "WITHDRAWN", "NOT_MAINTAINABLE",
                     "PROCESS_COMPLETED"]
    remarks: str = Field(..., min_length=5, max_length=2000)


@router.post("/cases/{case_id}/dispose", body=DisposeIn, perm="case.dispose")
def dispose(ctx: Ctx, case_id: str, body: DisposeIn):
    """Dispose with an outcome (remarks mandatory); closes the case's SLA alerts."""
    return wf.dispose(ctx.db, ctx.user, case_id, body.outcome, body.remarks)


@router.post("/cases/{case_id}/reopen", body=RemarksIn, perm="case.update")
def reopen(ctx: Ctx, case_id: str, body: RemarksIn):
    """Re-open a disposed case (Competent Authority)."""
    return wf.reopen(ctx.db, ctx.user, case_id, body.remarks)


class OverrideIn(In):
    band: Band | None = Field(None, description="New band, or null to clear an override")
    reason: str = Field(..., min_length=5, max_length=1000)


@router.post("/cases/{case_id}/priority-override", body=OverrideIn, perm="case.priority_override")
def override_priority(ctx: Ctx, case_id: str, body: OverrideIn):
    """Override the computed priority band (logged with previous/new value, reason, officer, bureau, time)."""
    return wf.override_priority(ctx.db, ctx.user, case_id, body.band, body.reason)


@router.get("/cases/{case_id}/priority", response=PriorityExplanation, perm="case.view")
def explain_priority(ctx: Ctx, case_id: str):
    """Priority score with every contributing 'why' chip."""
    from ..scoring import priority

    case = wf.get_case(ctx.db, case_id)
    assert_can_view_case(ctx.user, case)
    return priority.compute_for_case(ctx.db, case)


@router.post("/cases/{case_id}/documents", multipart=True, perm="case.document", status_code=201)
def add_document(ctx: Ctx, case_id: str):
    """Add a document reference, optionally with a small file (PDF/PNG/JPG/TXT, size-limited)."""
    form = ctx.form
    doc_type = str(form.get("doc_type") or "OTHER")
    title = str(form.get("title") or "")
    ref = form.get("reference_no")
    upload = form.get("file")
    content = name = None
    if upload is not None and hasattr(upload, "file"):
        limit = get_settings().max_upload_mb * 1024 * 1024
        content = upload.file.read(limit + 1)
        name = upload.filename
        if not content:
            content = None
    return wf.add_document(ctx.db, ctx.user, case_id, doc_type, title, str(ref) if ref else None, name, content)


@router.get("/documents/{doc_id}/download", perm="case.view", media="application/octet-stream")
def download_document(ctx: Ctx, doc_id: str):
    """Download a stored document (only files uploaded through AgniDrishti; seeded documents are metadata only)."""
    doc = ctx.db.one("SELECT * FROM case_documents WHERE id = ?", (doc_id,))
    if doc is None:
        raise not_found("Document", doc_id)
    case = wf.get_case(ctx.db, doc["case_id"])
    assert_can_view_case(ctx.user, case)
    if not doc["stored_name"]:
        raise bad_request("This document is a reference only; no file was uploaded.")
    folder = get_settings().storage_dir / "documents" / safe_filename(doc["case_id"])
    path = (folder / safe_filename(doc["stored_name"])).resolve()
    if folder.resolve() not in path.parents or not path.exists():
        raise not_found("Document file", doc_id)
    return FileResponse(path, media_type=doc["mime_type"] or "application/octet-stream",
                        filename=safe_filename(doc["file_name"] or doc["stored_name"]))
