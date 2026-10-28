"""Institution Master endpoints: list, profile, entity matching and the match-review queue."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..complaints.queries import BASE_SELECT, shape_row
from ..core import clock
from ..core.api import APIRouter, Ctx
from ..core.errors import not_found
from ..core.schemas import CaseRow, In, Out, PageQuery
from ..core.security import assert_can_view_institution, region_scope
from ..core.util import loads
from ..risk import index as risk_index
from ..scoring.rules import category_rules, get_settings_block
from . import matcher
from . import service as svc

router = APIRouter("/api", tags=["institutions"])


class InstitutionFilter(PageQuery):
    q: str | None = Field(None, description="Name, alias or Permanent ID (fuzzy)")
    region: list[str] | None = None
    state: list[str] | None = None
    trust_id: str | None = None
    risk_band: list[Literal["HIGH", "ELEVATED", "NORMAL"]] | None = None
    sort: Literal["name", "risk_desc", "open_desc", "overdue_desc"] = "risk_desc"


class InstitutionRow(Out):
    id: str
    permanent_id: str | None = None
    name: str
    district: str | None = None
    state: str
    region_code: str
    trust_id: str | None = None
    trust_name: str | None = None
    intake_total: int | None = None
    total_cases: int = 0
    open_cases: int = 0
    overdue_cases: int = 0
    open_bureaus: list[str] = []
    risk_score: float | None = None
    risk_band: str | None = None
    risk_trend: str | None = None
    open_overlaps: int = 0
    match_confidence: float | None = None
    match_band: str | None = None
    is_synthetic: bool = True
    demo_tag: str | None = None


class InstitutionPage(Out):
    items: list[InstitutionRow]
    total: int
    page: int
    page_size: int


def institution_rows(db, user, ids: list[str] | None = None) -> list[dict[str, Any]]:
    today = clock.today()
    risk = risk_index.compute_all(db, today)["institutions"]
    where, params = "1=1", []
    scope = region_scope(user)
    if scope:
        where += " AND i.region_code = ?"
        params.append(scope)
    if ids is not None:
        if not ids:
            return []
        where += f" AND i.id IN ({','.join('?' for _ in ids)})"
        params.extend(ids)
    rows = db.all(f"SELECT i.*, t.name AS trust_name FROM institutions i LEFT JOIN trusts t ON t.id = i.trust_id WHERE {where}",
                  params)
    stats = {r["institution_id"]: r for r in db.all(
        "SELECT institution_id, COUNT(*) total, SUM(status != 'DISPOSED') open_c, "
        "SUM(status != 'DISPOSED' AND expected_disposal_date < ?) overdue_c, "
        "GROUP_CONCAT(DISTINCT CASE WHEN status != 'DISPOSED' THEN bureau_code END) bureaus "
        "FROM complaints WHERE institution_id IS NOT NULL GROUP BY institution_id", (today.isoformat(),))}
    ovl = {r["institution_id"]: r["n"] for r in db.all(
        "SELECT institution_id, COUNT(*) n FROM overlap_alerts WHERE status IN ('OPEN','UNDER_REVIEW') GROUP BY institution_id")}
    out = []
    for r in rows:
        s = stats.get(r["id"], {})
        rk = risk.get(r["id"], {})
        out.append({**r, "total_cases": s.get("total") or 0, "open_cases": s.get("open_c") or 0,
                    "overdue_cases": s.get("overdue_c") or 0,
                    "open_bureaus": sorted(b for b in (s.get("bureaus") or "").split(",") if b),
                    "risk_score": rk.get("score"), "risk_band": rk.get("band"), "risk_trend": rk.get("trend"),
                    "open_overlaps": ovl.get(r["id"], 0), "is_synthetic": bool(r["is_synthetic"])})
    return out


@router.get("/institutions", query=InstitutionFilter, response=InstitutionPage, perm="institution.view")
def list_institutions(ctx: Ctx, q: InstitutionFilter):
    """Institution Master with case counts, open Bureaus/Cells, risk band and open overlaps."""
    ids = None
    conf: dict[str, dict[str, Any]] = {}
    if q.q:
        res = matcher.match(ctx.db, matcher.Query(q.q), limit=10)
        conf = {c["institution_id"]: c for c in res["candidates"] if c["confidence"] >= 0.2}
        like = ctx.db.all("SELECT DISTINCT i.id FROM institutions i LEFT JOIN institution_aliases a ON a.institution_id = i.id "
                          "WHERE i.name LIKE ? OR i.permanent_id LIKE ? OR a.alias LIKE ?", (f"%{q.q}%",) * 3)
        ids = sorted(set(conf) | {r["id"] for r in like})
    rows = institution_rows(ctx.db, ctx.user, ids)
    for r in rows:
        c = conf.get(r["id"])
        if c:
            r["match_confidence"], r["match_band"] = c["confidence"], c["band"]
    if q.region:
        rows = [r for r in rows if r["region_code"] in q.region]
    if q.state:
        rows = [r for r in rows if r["state"] in q.state]
    if q.trust_id:
        rows = [r for r in rows if r["trust_id"] == q.trust_id]
    if q.risk_band:
        rows = [r for r in rows if r["risk_band"] in q.risk_band]
    keyf = {"name": lambda r: r["name"], "risk_desc": lambda r: -(r["risk_score"] or 0),
            "open_desc": lambda r: -r["open_cases"], "overdue_desc": lambda r: -r["overdue_cases"]}[q.sort]
    if q.q:
        rows.sort(key=lambda r: (-(r.get("match_confidence") or 0), keyf(r)))
    else:
        rows.sort(key=keyf)
    start = (q.page - 1) * q.page_size
    return {"items": rows[start:start + q.page_size], "total": len(rows), "page": q.page, "page_size": q.page_size}


class RiskComponents(Out):
    severity_weighted_load: float
    recent_12m_share: float
    cases_considered: int
    cases_by_severity: dict[str, int]
    outcomes: dict[str, int]
    outcome_coverage: float
    exposure_thousand_students: float
    intake_known: bool
    raw_rate: float
    shrunk_rate: float
    population_rate: float
    median_rate: float
    credibility: float
    prior_strength: float
    half_life_days: float
    serious_last_12m: int
    first_case: str | None = None
    last_case: str | None = None


class Forecast(Out):
    status: str
    n_events: int
    horizon_days: float
    probability: float
    interval_80: list[float]
    expected_events: float
    params: dict[str, float]
    intensity_now_per_year: float
    intensity_6m_ago_per_year: float
    trend: str
    trend_ratio: float
    events_last_6m: int
    events_prev_6m: int
    confidence: str
    notes: list[str]
    relative_likelihood: float | None = None


class RiskOut(Out):
    institution_id: str
    score: float
    band: str
    score_6m_ago: float
    delta_6m: float
    trend: str
    delta_vs_median_change: float = 0.0
    confidence: str
    components: RiskComponents
    forecast: Forecast
    caveats: list[str]
    explanation: str | None = None
    disclaimer: str = "SYNTHETIC DATA — risk and forecast are computed from synthetic complaint history, not AICTE findings."


class ResponsibilityRow(Out):
    bureau_code: str
    bureau_name: str
    open_cases: int
    officers: list[str]
    case_ids: list[str]


class YearPoint(Out):
    year: str
    cases: int
    max_severity: int
    serious: int


class InstitutionDetail(Out):
    institution: dict[str, Any]
    aliases: list[dict[str, Any]]
    trust: dict[str, Any] | None = None
    sister_institutions: list[dict[str, Any]]
    risk: RiskOut
    cases: list[CaseRow]
    responsibility: list[ResponsibilityRow]
    timeline: list[dict[str, Any]]
    overlaps: list[dict[str, Any]]
    public_signals: list[dict[str, Any]]
    match_reviews: list[dict[str, Any]]
    history_by_year: list[YearPoint]
    master_cases: list[dict[str, Any]]


@router.get("/institutions/{inst_id}", response=InstitutionDetail, perm="institution.view")
def get_institution(ctx: Ctx, inst_id: str):
    """Institution profile: identifiers, aliases, trust, consolidated cases and timeline, risk, overlaps, signals."""
    db = ctx.db
    inst = svc.get_institution(db, inst_id)
    assert_can_view_institution(ctx.user, inst)
    today = clock.today()
    rules = category_rules(db)
    inst["courses"] = loads(inst.pop("courses_json"), [])
    inst["provenance"] = loads(inst.pop("provenance_json"), {})
    aliases = db.all("SELECT alias, alias_type, source, created_at FROM institution_aliases WHERE institution_id = ? ORDER BY id",
                     (inst_id,))
    trust = db.one("SELECT * FROM trusts WHERE id = ?", (inst["trust_id"],)) if inst["trust_id"] else None
    sisters = db.all("SELECT id, name, state, district FROM institutions WHERE trust_id = ? AND id != ?",
                     (inst["trust_id"], inst_id)) if inst["trust_id"] else []
    rows = db.all(f"{BASE_SELECT} WHERE c.institution_id = ? ORDER BY c.received_date DESC", (inst_id,))
    cases = [shape_row(r, rules, today) for r in rows]
    resp: dict[str, dict[str, Any]] = {}
    names = {r["code"]: r["name"] for r in db.all("SELECT code, name FROM bureaus")}
    for c in cases:
        if c["status"] == "DISPOSED":
            continue
        e = resp.setdefault(c["bureau_code"], {"bureau_code": c["bureau_code"], "bureau_name": names[c["bureau_code"]],
                                               "open_cases": 0, "officers": set(), "case_ids": []})
        e["open_cases"] += 1
        e["case_ids"].append(c["id"])
        if c.get("officer_name"):
            e["officers"].add(c["officer_name"])
    responsibility = [{**v, "officers": sorted(v["officers"])} for v in sorted(resp.values(), key=lambda x: -x["open_cases"])]
    ids = [c["id"] for c in cases]
    timeline = db.all(
        f"SELECT a.case_id, a.action_type, a.action_at, a.actor_label, a.actor_role, a.bureau_code, a.remarks "
        f"FROM case_actions a WHERE a.case_id IN ({','.join('?' for _ in ids)}) ORDER BY a.action_at DESC LIMIT 60",
        ids) if ids else []
    overlaps = db.all("SELECT id, tier, headline, status, score, recommended_lead, decided_lead, bureaus_json, created_at "
                      "FROM overlap_alerts WHERE institution_id = ? ORDER BY CASE status WHEN 'OPEN' THEN 0 WHEN 'UNDER_REVIEW' "
                      "THEN 1 ELSE 2 END, CASE tier WHEN 'CONFLICT' THEN 0 WHEN 'DUPLICATE' THEN 1 ELSE 2 END, created_at DESC",
                      (inst_id,))
    for o in overlaps:
        o["bureaus"] = loads(o.pop("bureaus_json"), [])
        o["cases"] = [r["case_id"] for r in db.all("SELECT case_id FROM overlap_alert_cases WHERE alert_id = ?", (o["id"],))]
    signals = db.all("SELECT id, signal_type, verification, title, publisher, source_url, published_date, match_status, "
                     "match_confidence FROM public_signals WHERE institution_id = ?", (inst_id,))
    # Only reviews where this institution is a plausible match (at or above the review threshold).
    review_t = float(get_settings_block(db, "matching")["review_threshold"])
    reviews = db.all("SELECT id, raw_name, status, best_confidence, source_ref FROM match_reviews "
                     "WHERE best_institution_id = ? AND status = 'PENDING' AND best_confidence >= ?", (inst_id, review_t))
    years: dict[str, dict[str, int]] = {}
    for c in rows:
        rule = rules[c["category_code"]]
        if rule["family"] == "REGULATORY_PROCESS":
            continue
        y = years.setdefault(c["received_date"][:4], {"cases": 0, "max_severity": 0, "serious": 0})
        y["cases"] += 1
        y["max_severity"] = max(y["max_severity"], int(rule["severity_level"]))
        y["serious"] += int(int(rule["severity_level"]) >= 4)
    history = [{"year": k, **v} for k, v in sorted(years.items())]
    risk = risk_index.for_institution(db, inst_id, today)
    if risk is None:
        raise not_found("Risk record", inst_id)
    risk = {**risk, "explanation": risk_index.explain_text(risk)}
    masters = db.all("SELECT * FROM master_cases WHERE institution_id = ? ORDER BY created_at DESC", (inst_id,))
    return {"institution": inst, "aliases": aliases, "trust": trust, "sister_institutions": sisters, "risk": risk,
            "cases": cases, "responsibility": responsibility, "timeline": timeline, "overlaps": overlaps,
            "public_signals": signals, "match_reviews": reviews, "history_by_year": history, "master_cases": masters}


@router.get("/institutions/{inst_id}/risk", response=RiskOut, perm="risk.view")
def get_risk(ctx: Ctx, inst_id: str):
    """Risk Index components, 6-month change and serious-complaint forecast for one institution."""
    inst = svc.get_institution(ctx.db, inst_id)
    assert_can_view_institution(ctx.user, inst)
    r = risk_index.for_institution(ctx.db, inst_id, clock.today())
    return {**r, "explanation": risk_index.explain_text(r)}


class MatchIn(In):
    name: str = Field(..., min_length=2, max_length=300)
    address: str | None = Field(None, max_length=300)
    pincode: str | None = Field(None, max_length=10)
    state: str | None = Field(None, max_length=60)
    permanent_id: str | None = Field(None, max_length=40)


class MatchCandidate(Out):
    institution_id: str
    name: str
    permanent_id: str | None = None
    district: str | None = None
    state: str | None = None
    pincode: str | None = None
    confidence: float
    band: str
    factors: list[dict[str, Any]]
    features: dict[str, float]
    score_source: str


class MatchResult(Out):
    query: dict[str, Any]
    candidates: list[MatchCandidate]
    decision: str
    reason: str
    thresholds: dict[str, float]
    model: dict[str, Any]
    note: str


@router.post("/institutions/match", body=MatchIn, response=MatchResult, perm="institution.view")
def match_institution(ctx: Ctx, body: MatchIn):
    """Entity resolution: ranked candidates with confidence, reasons and AUTO_LINK / REVIEW / NO_MATCH routing."""
    return matcher.match(ctx.db, matcher.Query(body.name, raw_address=body.address, raw_pincode=body.pincode,
                                               raw_state=body.state, raw_permanent_id=body.permanent_id))


class ReviewFilter(PageQuery):
    status: list[Literal["PENDING", "CONFIRMED", "REJECTED", "NEW_INSTITUTION"]] | None = None


class ReviewRow(Out):
    id: str
    raw_name: str
    raw_address: str | None = None
    raw_pincode: str | None = None
    raw_state: str | None = None
    raw_permanent_id: str | None = None
    source_type: str
    source_ref: str | None = None
    best_institution_id: str | None = None
    best_institution_name: str | None = None
    best_confidence: float | None = None
    candidates: list[dict[str, Any]] = []
    status: str
    decided_institution_id: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    remarks: str | None = None
    created_at: str
    case_subject: str | None = None
    case_category: str | None = None


class ReviewPage(Out):
    items: list[ReviewRow]
    total: int
    page: int
    page_size: int
    counts: dict[str, int]


@router.get("/match-reviews", query=ReviewFilter, response=ReviewPage, perm="institution.view")
def list_reviews(ctx: Ctx, q: ReviewFilter):
    """Human review queue for uncertain institution matches."""
    where, params = "1=1", []
    if q.status:
        where += f" AND r.status IN ({','.join('?' for _ in q.status)})"
        params.extend(q.status)
    scope = region_scope(ctx.user)
    if scope:
        where += " AND (c.region_code = ? OR c.region_code IS NULL)"
        params.append(scope)
    base = ("FROM match_reviews r LEFT JOIN complaints c ON c.id = r.source_ref "
            "LEFT JOIN institutions i ON i.id = r.best_institution_id")
    total = ctx.db.val(f"SELECT COUNT(*) {base} WHERE {where}", params, 0)
    rows = ctx.db.all(f"SELECT r.*, i.name AS best_institution_name, c.subject AS case_subject, c.category_code AS case_category "
                      f"{base} WHERE {where} ORDER BY CASE r.status WHEN 'PENDING' THEN 0 ELSE 1 END, r.created_at DESC "
                      f"LIMIT ? OFFSET ?", (*params, q.page_size, (q.page - 1) * q.page_size))
    for r in rows:
        r["candidates"] = loads(r.pop("candidates_json"), [])
    counts = {r["status"]: r["n"] for r in ctx.db.all("SELECT status, COUNT(*) n FROM match_reviews GROUP BY status")}
    return {"items": rows, "total": total, "page": q.page, "page_size": q.page_size, "counts": counts}


class ConfirmIn(In):
    institution_id: str
    remarks: str | None = Field(None, max_length=1000)


class RejectIn(In):
    institution_id: str
    remarks: str = Field(..., min_length=5, max_length=1000)


class NewInstitutionIn(In):
    name: str | None = Field(None, max_length=300)
    state: str = Field(..., min_length=2, max_length=60)
    district: str | None = Field(None, max_length=60)
    pincode: str | None = Field(None, max_length=10)
    permanent_id: str | None = Field(None, max_length=40)
    address: str | None = Field(None, max_length=300)
    remarks: str | None = Field(None, max_length=1000)


@router.post("/match-reviews/{review_id}/confirm", body=ConfirmIn, perm="match.review")
def confirm_review(ctx: Ctx, review_id: str, body: ConfirmIn):
    """Confirm a match: links the case, stores the alias for future matching, audits the decision."""
    return svc.confirm(ctx.db, ctx.user, review_id, body.institution_id, body.remarks)


@router.post("/match-reviews/{review_id}/reject", body=RejectIn, perm="match.review")
def reject_review(ctx: Ctx, review_id: str, body: RejectIn):
    """Reject a candidate: stored as negative feedback that down-weights this pairing next time."""
    return svc.reject(ctx.db, ctx.user, review_id, body.institution_id, body.remarks)


@router.post("/match-reviews/{review_id}/new-institution", body=NewInstitutionIn, perm="match.review")
def new_institution(ctx: Ctx, review_id: str, body: NewInstitutionIn):
    """No candidate is right: create a new Institution Master record and link the case to it."""
    fields = body.model_dump(exclude={"remarks"})
    return svc.resolve_with_new_institution(ctx.db, ctx.user, review_id, fields, body.remarks)
