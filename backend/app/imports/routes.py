"""Data import wizard endpoints: templates, data dictionary, upload, sheet, mapping, dry run, commit."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field
from starlette.responses import Response

from ..core.api import APIRouter, Ctx
from ..core.config import get_settings
from ..core.constants import OUTCOME_LABELS, STATUS_LABELS
from ..core.errors import bad_request
from ..core.schemas import In, Out, PageQuery
from ..scoring.rules import category_rules
from . import service as svc
from .spec import FIELDS

router = APIRouter("/api", tags=["imports"])
Kind = Literal["INSTITUTIONS", "COMPLAINTS", "PUBLIC_SIGNALS"]


class DictionaryOut(Out):
    fields: dict[str, list[dict[str, Any]]]
    accepted_values: dict[str, Any]
    policy: str


@router.get("/imports/dictionary", response=DictionaryOut, perm="import.view")
def dictionary(ctx: Ctx):
    """Target fields, types, accepted header names and accepted values per import kind."""
    return {"fields": FIELDS, "accepted_values": {
        "categories": {k: v["label"] for k, v in category_rules(ctx.db).items()},
        "bureaus": {r["code"]: r["name"] for r in ctx.db.all("SELECT code, name FROM bureaus")},
        "statuses": STATUS_LABELS, "outcomes": OUTCOME_LABELS, "reference_flags": ["NONE", "COURT", "VIP", "PARLIAMENT"],
        "states": [r["name"] for r in ctx.db.all("SELECT name FROM states ORDER BY name")],
        "date_formats": ["DD-MM-YYYY", "DD/MM/YYYY", "YYYY-MM-DD", "DD Mon YYYY", "Excel date cells"]},
        "policy": "Invalid rows are listed row by row. You may commit the valid rows only after explicitly acknowledging "
                  "how many rows will be skipped; otherwise fix the file and upload again. Commits are transactional."}


class TemplateQuery(In):
    kind: Kind
    fmt: Literal["csv", "xlsx"] = "csv"


@router.get("/imports/template", query=TemplateQuery, perm="import.view", media="text/csv")
def template(ctx: Ctx, q: TemplateQuery):
    """Downloadable template with the expected headers, an example row and (xlsx) a data dictionary sheet."""
    data, media = svc.template_bytes(q.kind, q.fmt)
    name = f"agnidrishti_{q.kind.lower()}_template.{q.fmt}"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


class JobOut(Out):
    id: str
    kind: str
    status: str
    file_name: str
    file_type: str
    file_sha256: str
    size_bytes: int
    sheet_name: str | None = None
    row_count: int
    mapping_hash: str | None = None
    policy: str
    uploaded_by: str | None = None
    uploaded_role: str | None = None
    created_at: str
    updated_at: str
    validated_at: str | None = None
    committed_at: str | None = None
    mapping: dict[str, str] | None = None
    validation: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None


class UploadOut(Out):
    job: JobOut
    sheets: list[str]
    sheet: str | None = None
    columns: list[str]
    row_count: int
    preview: list[dict[str, str]]
    suggested_mapping: dict[str, str]
    fields: list[dict[str, Any]]


class UploadQuery(In):
    kind: Kind


@router.post("/imports/upload", query=UploadQuery, multipart=True, response=UploadOut, perm="import.run", status_code=201)
def upload(ctx: Ctx, q: UploadQuery):
    """Upload a CSV/XLSX file: returns sheets, columns, a 10-row preview and a suggested column mapping."""
    up = ctx.form.get("file") if ctx.form is not None else None
    if up is None or not hasattr(up, "file"):
        raise bad_request("Attach the file in a multipart field named 'file'.")
    content = up.file.read(get_settings().max_upload_mb * 1024 * 1024 + 1)
    return svc.upload(ctx.db, ctx.user, q.kind, up.filename or "upload", content)


@router.get("/imports/{job_id}", response=UploadOut, perm="import.view")
def get_job(ctx: Ctx, job_id: str):
    """Job status with provenance (file, sheet, time, uploader role), mapping, validation and summary."""
    return svc.describe(ctx.db, job_id)


class SheetIn(In):
    sheet: str


@router.post("/imports/{job_id}/sheet", body=SheetIn, response=UploadOut, perm="import.run")
def select_sheet(ctx: Ctx, job_id: str, body: SheetIn):
    """Choose a different worksheet (xlsx)."""
    return svc.select_sheet(ctx.db, ctx.user, job_id, body.sheet)


class MappingIn(In):
    mapping: dict[str, str | None] = Field(..., description="target field -> source column")


class ValidateOut(Out):
    job: JobOut
    counts: dict[str, int]
    mapping_hash: str
    rows: list[dict[str, Any]]
    issues: list[dict[str, Any]]


@router.post("/imports/{job_id}/validate", body=MappingIn, response=ValidateOut, perm="import.run")
def validate(ctx: Ctx, job_id: str, body: MappingIn):
    """Dry run: validates types/required fields/duplicates and shows what would be inserted/updated/matched/skipped."""
    return svc.validate(ctx.db, ctx.user, job_id, {k: v for k, v in body.mapping.items() if v})


class CommitIn(In):
    mapping_hash: str
    acknowledge_skipped: bool = False


class CommitOut(Out):
    job: JobOut
    summary: dict[str, Any]


@router.post("/imports/{job_id}/commit", body=CommitIn, response=CommitOut, perm="import.run")
def commit(ctx: Ctx, job_id: str, body: CommitIn):
    """Commit the validated import in one transaction (re-validated); audited with mapping and counts."""
    return svc.commit(ctx.db, ctx.user, job_id, body.mapping_hash, body.acknowledge_skipped)


class IssueQuery(PageQuery):
    severity: Literal["ERROR", "WARNING"] | None = None


class IssuePage(Out):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


@router.get("/imports/{job_id}/issues", query=IssueQuery, response=IssuePage, perm="import.view")
def issues(ctx: Ctx, job_id: str, q: IssueQuery):
    """Row-level validation issues (paginated)."""
    where, p = "job_id = ?", [job_id]
    if q.severity:
        where += " AND severity = ?"
        p.append(q.severity)
    total = ctx.db.val(f"SELECT COUNT(*) FROM import_row_issues WHERE {where}", p, 0)
    rows = ctx.db.all(f"SELECT row_number, field, severity, code, message, value FROM import_row_issues WHERE {where} "
                      f"ORDER BY row_number, id LIMIT ? OFFSET ?", (*p, q.page_size, (q.page - 1) * q.page_size))
    return {"items": rows, "total": total, "page": q.page, "page_size": q.page_size}


class JobList(Out):
    items: list[JobOut]


@router.get("/imports", response=JobList, perm="import.view")
def list_jobs(ctx: Ctx):
    """Import history (newest first)."""
    rows = ctx.db.all("SELECT * FROM import_jobs ORDER BY created_at DESC LIMIT 100")
    return {"items": [svc.public_job(r) for r in rows]}
