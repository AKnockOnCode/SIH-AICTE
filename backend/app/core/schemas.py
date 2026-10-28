"""Shared Pydantic schemas (request bases, pagination and common rows)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Out(BaseModel):
    """Response models ignore extra keys so service dicts can be returned directly."""

    model_config = ConfigDict(extra="ignore")


class In(BaseModel):
    """Request models reject unknown fields to catch client mistakes early."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PageQuery(In):
    page: int = Field(1, ge=1, description="1-based page number")
    page_size: int = Field(25, ge=1, le=200, description="Rows per page (max 200)")


class Remarks(In):
    remarks: str | None = Field(None, max_length=2000)


class Ok(Out):
    ok: bool = True
    detail: str | None = None


class CaseRow(Out):
    id: str
    source_ref: str | None = None
    external_ref: str | None = None
    institution_id: str | None = None
    institution_name: str | None = None
    institution_name_raw: str
    permanent_id: str | None = None
    match_status: str
    match_confidence: float | None = None
    category_code: str
    category_label: str | None = None
    subject: str
    received_date: str
    bureau_code: str
    assigned_officer_id: str | None = None
    officer_name: str | None = None
    status: str
    priority_score: float | None = None
    priority_band: str | None = None
    effective_band: str | None = None
    expected_disposal_date: str
    disposed_date: str | None = None
    outcome: str | None = None
    overdue: bool = False
    days_remaining: int | None = None
    age_days: int | None = None
    region_code: str | None = None
    state: str | None = None
    last_action_type: str | None = None
    last_action_at: str | None = None
    next_action: str | None = None
    next_action_due: str | None = None
    master_case_id: str | None = None
    escalation_level: int = 0
    transfer_count: int = 0
    is_synthetic: bool = True
    demo_tag: str | None = None


class CasePage(Out):
    items: list[CaseRow]
    total: int
    page: int
    page_size: int
    filters: dict[str, Any] = {}


class Chip(Out):
    key: str
    kind: str
    label: str
    detail: str | None = None
    points: float = 0.0


class PriorityExplanation(Out):
    score: float
    band: str
    effective_band: str
    overridden: bool
    chips: list[Chip]
    formula: str
    explanation: str
    inputs: dict[str, Any] = {}


class SlaState(Out):
    due_date: str
    sla_days: int
    age_days: int
    days_remaining: int | None = None
    overdue: bool
    overdue_by_days: int
    pct_used: int
    state: str
    is_open: bool
    label: str


class BreachFactor(Out):
    factor: str
    label: str
    hazard_ratio: float
    effect: str
    direction: str


class BreachPrediction(Out):
    applicable: bool
    is_fact: bool = False
    reason: str | None = None
    probability: float | None = None
    band: str | None = None
    threshold: float | None = None
    age_days: int | None = None
    due_in_days: int | None = None
    factors: list[BreachFactor] = []
    historical_reference: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    model: dict[str, Any] | None = None
    disclaimer: str | None = None


class DateRange(In):
    date_from: date | None = Field(None, description="Received on/after (YYYY-MM-DD)")
    date_to: date | None = Field(None, description="Received on/before (YYYY-MM-DD)")
