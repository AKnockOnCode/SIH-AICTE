"""Editable rule configuration: category severity/SLA table and engine settings.

Rules live in the database (`category_rules`, `app_settings`), not in code, so AICTE can
adapt them to real policy. The defaults here are documented starting points only; the
SLA durations in particular are illustrative and must be validated by AICTE.
"""

from __future__ import annotations

import copy
from typing import Any

from ..core.clock import now_iso
from ..core.errors import unprocessable
from ..core.util import canonical_json, dumps, loads, sha256_hex

# code, label, family, severity_level (1-5), severity_weight, sla_days, default_bureau, keywords
DEFAULT_CATEGORY_RULES: list[dict[str, Any]] = [
    {"code": "RAGGING", "label": "Ragging", "family": "SAFETY", "severity_level": 5, "severity_weight": 5.0,
     "sla_days": 7, "default_bureau": "PGRC",
     "keywords": ["ragging", "ragged", "hazing", "seniors forced", "bullied by seniors", "anti-ragging"],
     "description": "Ragging incidents reported by students or parents (highest severity)."},
    {"code": "SEXUAL_HARASSMENT", "label": "Sexual harassment", "family": "SAFETY", "severity_level": 5,
     "severity_weight": 5.0, "sla_days": 7, "default_bureau": "PGRC",
     "keywords": ["sexual harassment", "molest", "inappropriate touching", "stalking", "lewd", "indecent"],
     "description": "Sexual harassment complaints (highest severity)."},
    {"code": "CAMPUS_CRIME", "label": "Campus crime / violence", "family": "SAFETY", "severity_level": 5,
     "severity_weight": 5.0, "sla_days": 7, "default_bureau": "RB",
     "keywords": ["assault", "attacked", "beaten", "theft", "robbery", "weapon", "narcotics", "knife"],
     "description": "Crime or violence on campus (highest severity)."},
    {"code": "VIOLENT_STRIKE", "label": "Violent strike / unrest", "family": "SAFETY", "severity_level": 5,
     "severity_weight": 5.0, "sla_days": 7, "default_bureau": "RB",
     "keywords": ["violent strike", "vandalism", "vandalised", "arson", "stone pelting", "mob"],
     "description": "Violent strikes or unrest affecting students or staff (highest severity)."},
    {"code": "FAKE_UNAPPROVED", "label": "Fake / unapproved course or institution", "family": "REGULATORY",
     "severity_level": 4, "severity_weight": 4.0, "sla_days": 30, "default_bureau": "RB",
     "keywords": ["unapproved", "not approved by aicte", "fake course", "fake degree", "without aicte approval", "bogus"],
     "description": "Courses or institutions operating without required approval (high severity)."},
    {"code": "REGULATORY_NONCOMPLIANCE", "label": "Regulatory non-compliance", "family": "REGULATORY",
     "severity_level": 4, "severity_weight": 4.0, "sla_days": 30, "default_bureau": "RB",
     "keywords": ["faculty shortage", "infrastructure", "mandatory disclosure", "lab equipment", "no library", "approval conditions"],
     "description": "Institution-related regulatory concerns: norms, faculty, infrastructure (high severity)."},
    {"code": "FEE_FRAUD", "label": "Fee fraud / excess fee", "family": "FINANCIAL", "severity_level": 3,
     "severity_weight": 3.0, "sla_days": 15, "default_bureau": "PGRC",
     "keywords": ["excess fee", "capitation", "donation", "refund", "fee hike", "extra fees", "caution deposit"],
     "description": "Excess or unreceipted fees, capitation, refund denial (medium-high)."},
    {"code": "WITHHELD_CERTIFICATES", "label": "Withheld certificates / documents", "family": "FINANCIAL",
     "severity_level": 3, "severity_weight": 3.0, "sla_days": 15, "default_bureau": "PGRC",
     "keywords": ["original certificates", "withheld", "not returning documents", "transfer certificate", "marksheet"],
     "description": "Original certificates or documents withheld by the institution (medium-high)."},
    {"code": "SCHOLARSHIP", "label": "Scholarship / fee reimbursement", "family": "ACADEMIC", "severity_level": 2,
     "severity_weight": 2.0, "sla_days": 15, "default_bureau": "SDC",
     "keywords": ["scholarship", "fee reimbursement", "stipend", "freeship"],
     "description": "Scholarship or reimbursement issues (medium)."},
    {"code": "EXAMINATION", "label": "Examination / results", "family": "ACADEMIC", "severity_level": 2,
     "severity_weight": 2.0, "sla_days": 15, "default_bureau": "PGRC",
     "keywords": ["examination", "exam", "result", "revaluation", "hall ticket", "marks"],
     "description": "Examination conduct, results and revaluation (medium)."},
    {"code": "APPROVAL_RENEWAL", "label": "Approval / renewal file (regulatory)", "family": "REGULATORY_PROCESS",
     "severity_level": 2, "severity_weight": 2.0, "sla_days": 30, "default_bureau": "RB",
     "keywords": ["extension of approval", "renewal", "intake increase", "approval process"],
     "description": "Regulatory process files such as Extension of Approval or intake change (added category; "
                    "not a grievance)."},
    {"code": "GENERAL_ENQUIRY", "label": "General / other enquiry", "family": "GENERAL", "severity_level": 1,
     "severity_weight": 1.0, "sla_days": 30, "default_bureau": "PGRC", "keywords": [],
     "description": "General or other enquiries (lowest)."},
]

SEVERITY_LABELS = {5: "Highest", 4: "High", 3: "Medium-high", 2: "Medium", 1: "Lowest"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "priority": {
        "modifiers": {
            "complainants": {"weight": 0.30, "cap_count": 100,
                             "help": "log10(count)/log10(cap_count), 1 complainant = 0"},
            "evidence": {"weight": 0.20, "help": "1 if at least one evidence item/document is attached"},
            "reference": {"weight": 0.40, "court": 1.0, "parliament": 1.0, "vip": 0.75,
                          "help": "Court / Parliament / VIP reference flag"},
            "age": {"weight": 0.40, "full_at_sla_multiple": 2.0,
                    "help": "age_days / (sla_days x multiple), capped at 1"},
        },
        "modifier_cap": 1.0,
        "max_severity_weight": 5.0,
        "keyword_escalation": True,
        "bands": {"CRITICAL": 50.0, "HIGH": 35.0, "MEDIUM": 20.0},
    },
    "matching": {"auto_link_threshold": 0.90, "review_threshold": 0.55, "max_candidates": 5},
    "conflict": {
        "duplicate_window_days": 60,
        "duplicate_text_min": 0.45,
        "duplicate_strong_text": 0.75,
        "duplicate_strong_window_days": 150,
        "related_window_days": 365,
        "related_text_min": 0.30,
        "favourable_actions": ["RENEWAL_INITIATED", "APPROVAL_GRANTED", "EXTENSION_OF_APPROVAL",
                               "INTAKE_INCREASE_PROPOSED", "INTAKE_INCREASE_APPROVED", "NOC_ISSUED"],
        "adverse_actions": ["SHOW_CAUSE_NOTICE", "CLOSURE_ORDER", "WITHDRAWAL_OF_APPROVAL", "PENALTY_IMPOSED"],
        "action_window_days": 120,
        "open_min_severity": 3,
        "substantiated_lookback_days": 730,
        "substantiated_min_severity": 4,
    },
    "lead": {
        "competence_weight": 1.0,
        "current_handler_weight": 0.5,
        "regulatory_action_weight": 2.0,
        "workload_sensitivity": 0.6,
        "workload_min_factor": 0.5,
        "workload_max_factor": 1.2,
    },
    "sla": {
        "warning_days_before_due": 3,
        "pending_reminder_idle_days": 14,
        "predicted_breach_threshold": 0.6,
    },
    "risk": {
        "half_life_days": 365,
        "outcome_factors": {"SUBSTANTIATED": 1.0, "PARTIALLY_SUBSTANTIATED": 0.7, "OPEN": 0.6,
                            "UNSUBSTANTIATED": 0.2, "WITHDRAWN": 0.1, "NOT_MAINTAINABLE": 0.1},
        "intake_fallback": 600,
        "prior_strength_students": 500,
        "bands": {"HIGH": 65.0, "ELEVATED": 57.0},
        "serious_min_severity": 4,
    },
}

SETTINGS_KEYS = tuple(DEFAULT_SETTINGS)


def default_category_rows(now: str) -> list[dict[str, Any]]:
    rows = []
    for i, r in enumerate(DEFAULT_CATEGORY_RULES):
        rows.append({
            "code": r["code"], "label": r["label"], "description": r["description"], "family": r["family"],
            "severity_level": r["severity_level"], "severity_weight": r["severity_weight"],
            "sla_days": r["sla_days"], "default_bureau": r["default_bureau"],
            "keywords_json": dumps(r["keywords"]), "active": 1, "sort_order": i,
            "updated_at": now, "updated_by": "default",
        })
    return rows


def seed_rules(db, now: str | None = None) -> None:
    now = now or now_iso()
    for row in default_category_rows(now):
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        db.run(f"INSERT OR IGNORE INTO category_rules ({cols}) VALUES ({marks})", tuple(row.values()))
    for key, value in DEFAULT_SETTINGS.items():
        db.run("INSERT OR IGNORE INTO app_settings(key, value_json, updated_at, updated_by) VALUES (?,?,?,?)",
               (key, dumps(value), now, "default"))


# ---------------------------------------------------------------------------- reads
_cache: dict[str, Any] = {}


_CATEGORY_ROW = ("printf('%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s', code, label, description, family, severity_level, "
                 "severity_weight, sla_days, default_bureau, keywords_json, active, sort_order, updated_at)")


def _stamp(db) -> str:
    """Content fingerprint of the editable rules. Any edit changes it, whatever the clock says
    (a timestamp-based stamp missed edits made with a frozen date earlier in the day than the seed)."""
    cats = db.val(f"SELECT group_concat(s, ';') FROM (SELECT {_CATEGORY_ROW} AS s FROM category_rules ORDER BY code)",
                  default="")
    settings = db.val("SELECT group_concat(s, ';') FROM (SELECT key || '=' || value_json AS s FROM app_settings ORDER BY key)",
                      default="")
    return sha256_hex(f"{cats}#{settings}")


def get_settings_block(db, key: str) -> dict[str, Any]:
    row = db.one("SELECT value_json FROM app_settings WHERE key = ?", (key,))
    if row is None:
        return copy.deepcopy(DEFAULT_SETTINGS[key])
    merged = copy.deepcopy(DEFAULT_SETTINGS.get(key, {}))
    merged.update(loads(row["value_json"], {}))
    return merged


def all_settings(db) -> dict[str, Any]:
    return {k: get_settings_block(db, k) for k in SETTINGS_KEYS}


def category_rules(db) -> dict[str, dict[str, Any]]:
    """Category rules keyed by code (cached per settings stamp)."""
    stamp = _stamp(db)
    if _cache.get("cat_stamp") == stamp and "cat" in _cache:
        return _cache["cat"]
    rules = {}
    for r in db.all("SELECT * FROM category_rules ORDER BY sort_order"):
        r["keywords"] = loads(r.pop("keywords_json"), [])
        rules[r["code"]] = r
    _cache["cat"] = rules
    _cache["cat_stamp"] = stamp
    return rules


def rules_version(db) -> str:
    return _stamp(db)


# ---------------------------------------------------------------------------- validation
def validate_category_update(body: dict[str, Any], bureaus: set[str]) -> list[str]:
    errors = []
    lvl = body.get("severity_level")
    if lvl is not None and not (1 <= int(lvl) <= 5):
        errors.append("severity_level must be between 1 and 5")
    w = body.get("severity_weight")
    if w is not None and not (0.1 <= float(w) <= 10):
        errors.append("severity_weight must be between 0.1 and 10")
    sla = body.get("sla_days")
    if sla is not None and not (1 <= int(sla) <= 365):
        errors.append("sla_days must be between 1 and 365")
    b = body.get("default_bureau")
    if b is not None and b not in bureaus:
        errors.append(f"default_bureau must be one of {sorted(bureaus)}")
    kws = body.get("keywords")
    if kws is not None:
        if not isinstance(kws, list) or any(not isinstance(k, str) or not k.strip() or len(k) > 60 for k in kws):
            errors.append("keywords must be a list of non-empty strings (max 60 chars each)")
        elif len(kws) > 40:
            errors.append("at most 40 keywords per category")
    return errors


def _num(errors: list[str], path: str, value: Any, lo: float, hi: float) -> None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        errors.append(f"{path} must be a number")
        return
    if not (lo <= v <= hi):
        errors.append(f"{path} must be between {lo} and {hi}")


def validate_settings_block(key: str, value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if key == "priority":
        mods = value.get("modifiers", {})
        for name in ("complainants", "evidence", "reference", "age"):
            if name not in mods:
                errors.append(f"modifiers.{name} is required")
                continue
            _num(errors, f"modifiers.{name}.weight", mods[name].get("weight"), 0, 2)
        if "complainants" in mods:
            _num(errors, "modifiers.complainants.cap_count", mods["complainants"].get("cap_count", 100), 2, 100000)
        if "age" in mods:
            _num(errors, "modifiers.age.full_at_sla_multiple", mods["age"].get("full_at_sla_multiple", 2), 0.5, 10)
        _num(errors, "modifier_cap", value.get("modifier_cap"), 0, 3)
        bands = value.get("bands", {})
        try:
            c, h, m = float(bands["CRITICAL"]), float(bands["HIGH"]), float(bands["MEDIUM"])
            if not (100 >= c > h > m > 0):
                errors.append("bands must satisfy 100 >= CRITICAL > HIGH > MEDIUM > 0")
        except (KeyError, TypeError, ValueError):
            errors.append("bands.CRITICAL, bands.HIGH and bands.MEDIUM are required numbers")
    elif key == "matching":
        _num(errors, "auto_link_threshold", value.get("auto_link_threshold"), 0.5, 1.0)
        _num(errors, "review_threshold", value.get("review_threshold"), 0.1, 0.99)
        try:
            if float(value["review_threshold"]) >= float(value["auto_link_threshold"]):
                errors.append("review_threshold must be lower than auto_link_threshold")
        except (KeyError, TypeError, ValueError):
            pass
        _num(errors, "max_candidates", value.get("max_candidates", 5), 1, 20)
    elif key == "conflict":
        for f, lo, hi in (("duplicate_window_days", 1, 730), ("duplicate_text_min", 0, 1),
                          ("duplicate_strong_text", 0, 1), ("duplicate_strong_window_days", 1, 1095),
                          ("related_window_days", 1, 1825), ("related_text_min", 0, 1),
                          ("action_window_days", 1, 730), ("open_min_severity", 1, 5),
                          ("substantiated_lookback_days", 1, 3650), ("substantiated_min_severity", 1, 5)):
            _num(errors, f, value.get(f), lo, hi)
        for f in ("favourable_actions", "adverse_actions"):
            if not isinstance(value.get(f), list):
                errors.append(f"{f} must be a list of action types")
    elif key == "lead":
        for f, lo, hi in (("competence_weight", 0, 10), ("current_handler_weight", 0, 10),
                          ("regulatory_action_weight", 0, 20), ("workload_sensitivity", 0, 3),
                          ("workload_min_factor", 0.05, 1), ("workload_max_factor", 1, 3)):
            _num(errors, f, value.get(f), lo, hi)
    elif key == "sla":
        _num(errors, "warning_days_before_due", value.get("warning_days_before_due"), 0, 60)
        _num(errors, "pending_reminder_idle_days", value.get("pending_reminder_idle_days"), 1, 365)
        _num(errors, "predicted_breach_threshold", value.get("predicted_breach_threshold"), 0.05, 0.99)
    elif key == "risk":
        _num(errors, "half_life_days", value.get("half_life_days"), 30, 3650)
        _num(errors, "intake_fallback", value.get("intake_fallback"), 10, 100000)
        _num(errors, "prior_strength_students", value.get("prior_strength_students"), 0, 100000)
        bands = value.get("bands", {})
        try:
            if not (100 > float(bands["HIGH"]) > float(bands["ELEVATED"]) > 0):
                errors.append("risk bands must satisfy 100 > HIGH > ELEVATED > 0")
        except (KeyError, TypeError, ValueError):
            errors.append("risk bands HIGH and ELEVATED are required numbers")
    else:
        errors.append(f"unknown settings block '{key}'")
    return errors


def save_settings_block(db, key: str, value: dict[str, Any], actor_id: str) -> tuple[dict, dict]:
    errors = validate_settings_block(key, value)
    if errors:
        raise unprocessable("Rule validation failed.", errors)
    before = get_settings_block(db, key)
    db.run(
        "INSERT INTO app_settings(key, value_json, updated_at, updated_by) VALUES (?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at, "
        "updated_by = excluded.updated_by",
        (key, dumps(value), now_iso(micro=True), actor_id),
    )
    return before, value


def settings_equal(a: Any, b: Any) -> bool:
    return canonical_json(a) == canonical_json(b)
