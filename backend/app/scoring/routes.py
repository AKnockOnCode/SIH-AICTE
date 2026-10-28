"""Priority Rules editor: categories (severity, SLA, keywords, default Bureau), modifier weights/caps,
bands, matching thresholds, conflict/lead/SLA/risk parameters — with impact preview, validation,
permission checks, persistence, audit of before/after values and a safe reset to defaults."""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import Field

from ..audit import chain
from ..core import clock
from ..core.api import APIRouter, Ctx
from ..core.errors import not_found, unprocessable
from ..core.schemas import In, Out
from ..core.util import dumps
from . import priority as priority_mod
from .rules import (
    DEFAULT_CATEGORY_RULES,
    DEFAULT_SETTINGS,
    SETTINGS_KEYS,
    all_settings,
    category_rules,
    default_category_rows,
    save_settings_block,
    validate_category_update,
    validate_settings_block,
)

router = APIRouter("/api", tags=["rules"])
Block = Literal["priority", "matching", "conflict", "lead", "sla", "risk"]


class RulesOut(Out):
    categories: list[dict[str, Any]]
    settings: dict[str, Any]
    defaults: dict[str, Any]
    editable_by: str = "COMPETENT_AUTHORITY"
    note: str = ("Illustrative defaults (e.g. 15-day SLA for standard student grievances) must be validated against AICTE "
                 "policy before real use.")


@router.get("/rules", response=RulesOut, perm="rules.view")
def get_rules(ctx: Ctx):
    """Current rule configuration (stored in the database, not in code) with defaults for comparison."""
    cats = list(category_rules(ctx.db).values())
    return {"categories": cats, "settings": all_settings(ctx.db),
            "defaults": {"categories": DEFAULT_CATEGORY_RULES, "settings": DEFAULT_SETTINGS}}


class CategoryUpdate(In):
    label: str | None = Field(None, min_length=3, max_length=80)
    severity_level: int | None = Field(None, ge=1, le=5)
    severity_weight: float | None = Field(None, ge=0.1, le=10)
    sla_days: int | None = Field(None, ge=1, le=365)
    default_bureau: str | None = None
    keywords: list[str] | None = None
    active: bool | None = None
    apply_sla_to_open: bool = Field(False, description="Recompute due dates of open cases in this category")


class PreviewIn(In):
    categories: dict[str, CategoryUpdate] = {}
    settings: dict[Block, dict[str, Any]] = {}


class PreviewOut(Out):
    valid: bool
    errors: list[str]
    open_cases: int
    band_changes: int
    band_matrix: dict[str, dict[str, int]]
    examples: list[dict[str, Any]]
    due_date_changes: int
    review_routing: dict[str, int] | None = None


def _apply(rules: dict[str, Any], cats: dict[str, CategoryUpdate]) -> dict[str, Any]:
    new = copy.deepcopy(rules)
    for code, upd in cats.items():
        if code not in new:
            raise not_found("Category", code)
        for k, v in upd.model_dump(exclude_none=True, exclude={"apply_sla_to_open"}).items():
            new[code][k] = v
    return new


@router.post("/rules/preview", body=PreviewIn, response=PreviewOut, perm="rules.view")
def preview(ctx: Ctx, body: PreviewIn):
    """Show what a rule change would affect before saving (no data is modified)."""
    db = ctx.db
    errors: list[str] = []
    bureaus = {r["code"] for r in db.all("SELECT code FROM bureaus")}
    for code, upd in body.categories.items():
        errors += [f"{code}: {e}" for e in validate_category_update(upd.model_dump(exclude_none=True), bureaus)]
    current = all_settings(db)
    proposed = copy.deepcopy(current)
    for block, value in body.settings.items():
        merged = {**current[block], **value}
        errors += [f"{block}: {e}" for e in validate_settings_block(block, merged)]
        proposed[block] = merged
    rules = category_rules(db)
    try:
        new_rules = _apply(rules, body.categories)
    except Exception as exc:  # unknown category
        return {"valid": False, "errors": [str(exc)], "open_cases": 0, "band_changes": 0, "band_matrix": {}, "examples": [],
                "due_date_changes": 0}
    today = clock.today()
    cases = db.all("SELECT * FROM complaints WHERE status != 'DISPOSED'")
    matrix: dict[str, dict[str, int]] = {}
    examples = []
    changes = due_changes = 0
    if not errors:
        for c in cases:
            old = priority_mod.compute(c, rules, current["priority"], today)
            new_case = c
            upd = body.categories.get(c["category_code"])
            if upd and upd.apply_sla_to_open and upd.sla_days:
                new_case = {**c, "sla_days": upd.sla_days}
                if upd.sla_days != c["sla_days"]:
                    due_changes += 1
            new = priority_mod.compute(new_case, new_rules, proposed["priority"], today)
            matrix.setdefault(old["band"], {}).setdefault(new["band"], 0)
            matrix[old["band"]][new["band"]] += 1
            if old["band"] != new["band"]:
                changes += 1
                if len(examples) < 10:
                    examples.append({"case_id": c["id"], "category_code": c["category_code"], "old_band": old["band"],
                                     "new_band": new["band"], "old_score": old["score"], "new_score": new["score"]})
    routing = None
    if "matching" in body.settings and not errors:
        auto_t = float(proposed["matching"]["auto_link_threshold"])
        review_t = float(proposed["matching"]["review_threshold"])
        routing = {"auto_link": 0, "review": 0, "no_match": 0}
        for r in db.all("SELECT best_confidence FROM match_reviews WHERE status = 'PENDING'"):
            conf = r["best_confidence"] or 0
            routing["auto_link" if conf >= auto_t else "review" if conf >= review_t else "no_match"] += 1
    return {"valid": not errors, "errors": errors, "open_cases": len(cases), "band_changes": changes, "band_matrix": matrix,
            "examples": examples, "due_date_changes": due_changes, "review_routing": routing}


@router.put("/rules/categories/{code}", body=CategoryUpdate, perm="rules.edit")
def update_category(ctx: Ctx, code: str, body: CategoryUpdate):
    """Edit one category rule (validated, audited with before/after; priorities recomputed)."""
    db = ctx.db
    bureaus = {r["code"] for r in db.all("SELECT code FROM bureaus")}
    data = body.model_dump(exclude_none=True, exclude={"apply_sla_to_open"})
    errors = validate_category_update(data, bureaus)
    if errors:
        raise unprocessable("Rule validation failed.", errors)
    with db.tx():
        before = db.one("SELECT * FROM category_rules WHERE code = ?", (code,))
        if before is None:
            raise not_found("Category", code)
        changes = {k: v for k, v in data.items() if k != "keywords"}
        if "keywords" in data:
            changes["keywords_json"] = dumps(sorted({k.strip().lower() for k in data["keywords"] if k.strip()}))
        if "active" in changes:
            changes["active"] = int(changes["active"])
        changes["updated_at"] = clock.now_iso(micro=True)
        changes["updated_by"] = ctx.user.id
        db.update("category_rules", "code", code, changes)
        moved = 0
        if body.apply_sla_to_open and body.sla_days:
            for c in db.all("SELECT id, received_date FROM complaints WHERE category_code = ? AND status != 'DISPOSED'", (code,)):
                due = (date.fromisoformat(c["received_date"]) + timedelta(days=body.sla_days)).isoformat()
                db.run("UPDATE complaints SET sla_days = ?, expected_disposal_date = ? WHERE id = ?", (body.sla_days, due, c["id"]))
                moved += 1
        after = db.one("SELECT * FROM category_rules WHERE code = ?", (code,))
        n = priority_mod.recompute_all(db)
        chain.record(db, ctx.user, "RULE_CATEGORY_UPDATED", "category_rule", code, before=before, after=after,
                     remarks=f"priorities recomputed for {n} cases; due dates moved for {moved} open cases")
    return {"code": code, "recomputed": n, "due_dates_moved": moved}


class SettingsIn(In):
    value: dict[str, Any]


@router.put("/rules/settings/{block}", body=SettingsIn, perm="rules.edit")
def update_settings(ctx: Ctx, block: str, body: SettingsIn):
    """Replace one settings block (priority, matching, conflict, lead, sla, risk) after validation."""
    if block not in SETTINGS_KEYS:
        raise not_found("Settings block", block)
    with ctx.db.tx():
        current = all_settings(ctx.db)[block]
        before, after = save_settings_block(ctx.db, block, {**current, **body.value}, ctx.user.id)
        n = priority_mod.recompute_all(ctx.db) if block == "priority" else 0
        chain.record(ctx.db, ctx.user, "RULE_SETTINGS_UPDATED", "settings", block, before=before, after=after,
                     remarks=f"priorities recomputed for {n} cases" if n else None)
    return {"block": block, "recomputed": n}


class ResetIn(In):
    confirm: Literal["RESET"]
    scope: Literal["all", "categories", "settings"] = "all"


@router.post("/rules/reset", body=ResetIn, perm="rules.edit")
def reset_rules(ctx: Ctx, body: ResetIn):
    """Restore documented defaults (requires typing RESET); audited with the previous configuration."""
    db = ctx.db
    with db.tx():
        before = {"categories": list(category_rules(db).values()), "settings": all_settings(db)}
        now = clock.now_iso(micro=True)
        if body.scope in ("all", "categories"):
            for row in default_category_rows(now):
                row["updated_by"] = ctx.user.id
                code = row.pop("code")
                db.update("category_rules", "code", code, row)
        if body.scope in ("all", "settings"):
            for key, value in DEFAULT_SETTINGS.items():
                db.run("UPDATE app_settings SET value_json = ?, updated_at = ?, updated_by = ? WHERE key = ?",
                       (dumps(value), now, ctx.user.id, key))
        n = priority_mod.recompute_all(db)
        chain.record(db, ctx.user, "RULES_RESET", "rules", body.scope, before=before, after={"scope": body.scope},
                     remarks=f"Reset to documented defaults; priorities recomputed for {n} cases")
    return {"reset": body.scope, "recomputed": n}


class ClassifyIn(In):
    text: str = Field(..., min_length=10, max_length=5000)
    use_llm: bool = False


class ClassifyOut(Out):
    local: list[dict[str, Any]]
    local_model: dict[str, Any]
    llm: dict[str, Any] | None = None
    note: str = "Recommendations only. Officers choose the category; the score uses the selected category and keyword rules."


@router.post("/classify", body=ClassifyIn, response=ClassifyOut, perm="case.view")
def classify(ctx: Ctx, body: ClassifyIn):
    """Suggest a category from complaint text (local TF-IDF + Logistic Regression; optional Anthropic if configured)."""
    from ..llm import client as llm
    from . import classifier

    out: dict[str, Any] = {"local": classifier.predict(body.text), "local_model": classifier.status()}
    if body.use_llm:
        if not llm.available():
            out["llm"] = {"available": False, "detail": "ANTHROPIC_API_KEY is not configured; local model used."}
        else:
            cats = {k: v["label"] for k, v in category_rules(ctx.db).items()}
            res = llm.suggest_category(body.text, cats)
            out["llm"] = {"available": True, "suggestion": res, "label": "AI-assisted (Anthropic) — recommendation only"} if res \
                else {"available": True, "suggestion": None, "detail": "LLM call failed or returned an invalid category."}
    return out
