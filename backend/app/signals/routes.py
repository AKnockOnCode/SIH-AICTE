"""Public Signals layer: official notices / news context, kept separate from complaints."""

from __future__ import annotations

import json
from typing import Any, Literal

from ..core.api import APIRouter, Ctx
from ..core.config import BACKEND_DIR
from ..core.schemas import In, Out

router = APIRouter("/api", tags=["signals"])

DISCLAIMER = ("A public signal is context only. It is NOT a verified complaint, an adjudication or an AICTE case, and AgniDrishti "
              "never creates or changes a case because a notice or news story exists.")


class SignalQuery(In):
    signal_type: list[Literal["OFFICIAL_NOTICE", "NEWS_REPORT", "SYNTHETIC_DEMO"]] | None = None
    verification: list[Literal["VERIFIED_SOURCE", "UNVERIFIED", "SYNTHETIC"]] | None = None
    institution_id: str | None = None
    match_status: list[Literal["MATCHED", "UNCERTAIN", "NO_MATCH"]] | None = None


class SignalRow(Out):
    id: str
    signal_type: str
    verification: str
    scope: str
    title: str
    publisher: str | None = None
    source_url: str | None = None
    published_date: str | None = None
    retrieved_at: str | None = None
    summary: str
    raw_institution_text: str | None = None
    institution_id: str | None = None
    institution_name: str | None = None
    match_confidence: float | None = None
    match_status: str
    notes: str | None = None
    import_job_id: str | None = None


class SignalList(Out):
    items: list[SignalRow]
    counts: dict[str, int]
    disclaimer: str = DISCLAIMER
    sources: dict[str, Any]


def _sources() -> dict[str, Any]:
    meta: dict[str, Any] = {}
    path = BACKEND_DIR / "data" / "public" / "public_signals.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = {"description": data.get("description"), "retrieval_note": data.get("retrieval_note"),
                "verified_count": len(data.get("signals", []))}
    cache = BACKEND_DIR / "var" / "public_cache" / "manifest.json"
    meta["cache"] = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {
        "status": "not cached", "how": "python scripts/acquire_public_data.py (needs internet; checks robots.txt)"}
    return meta


@router.get("/signals", query=SignalQuery, response=SignalList, perm="signals.view")
def list_signals(ctx: Ctx, q: SignalQuery):
    """Public signals with source links, retrieval provenance and entity-match status."""
    where, p = ["1=1"], []
    for col, vals in (("s.signal_type", q.signal_type), ("s.verification", q.verification), ("s.match_status", q.match_status)):
        if vals:
            where.append(f"{col} IN ({','.join('?' for _ in vals)})")
            p.extend(vals)
    if q.institution_id:
        where.append("s.institution_id = ?")
        p.append(q.institution_id)
    rows = ctx.db.all(f"SELECT s.*, i.name AS institution_name FROM public_signals s LEFT JOIN institutions i ON i.id = s.institution_id "
                      f"WHERE {' AND '.join(where)} ORDER BY CASE s.verification WHEN 'VERIFIED_SOURCE' THEN 0 WHEN 'UNVERIFIED' "
                      f"THEN 1 ELSE 2 END, s.published_date DESC", p)
    counts = {r["verification"]: r["n"] for r in ctx.db.all("SELECT verification, COUNT(*) n FROM public_signals GROUP BY verification")}
    return {"items": rows, "counts": counts, "sources": _sources()}
