"""One-click Pre-Decision Dossier.

Deterministic and template-based by default. If ANTHROPIC_API_KEY is configured and AI wording
is requested, the model may only *rephrase* the template narrative: every case ID and number in
its text must already exist in the structured facts, otherwise it is rejected and the template
text is used. Structured sections always come straight from the database.
"""

from __future__ import annotations

import re
from typing import Any

from .. import __version__
from ..complaints.queries import BASE_SELECT
from ..core import clock
from ..core.constants import ACTION_TYPES, OUTCOME_LABELS, STATUS_LABELS
from ..core.provenance import data_disclaimer
from ..core.security import User, assert_can_view_institution
from ..core.util import loads
from ..institutions.service import get_institution
from ..llm import client as llm
from ..risk import index as risk_index
from ..scoring.rules import category_rules
from ..sla import breach
from ..sla.engine import sla_state

CASE_ID_RE = re.compile(r"\b(?:RB|PGRC|AB|SDC|LC|RO|OVL|MC|INS)-\d{3,5}\b")
NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def build(db, user: User, inst_id: str, narrative_mode: str = "template") -> dict[str, Any]:
    inst = get_institution(db, inst_id)
    assert_can_view_institution(user, inst)
    today = clock.today()
    rules = category_rules(db)
    trust = db.one("SELECT * FROM trusts WHERE id = ?", (inst["trust_id"],)) if inst["trust_id"] else None
    cases = db.all(f"{BASE_SELECT} WHERE c.institution_id = ? ORDER BY c.received_date DESC", (inst_id,))
    model = breach.get_model(db, today)
    open_cases, history = [], []
    for c in cases:
        rule = rules[c["category_code"]]
        st = sla_state(c, today)
        row = {"id": c["id"], "category": rule["label"], "severity": rule["severity_level"], "bureau": c["bureau_code"],
               "status": STATUS_LABELS[c["status"]], "received": c["received_date"], "disposed": c["disposed_date"],
               "outcome": OUTCOME_LABELS.get(c["outcome"] or "", None), "priority": c["priority_override_band"] or c["priority_band"],
               "sla": st["label"], "master_case_id": c["master_case_id"]}
        history.append(row)
        if c["status"] != "DISPOSED":
            p = breach.predict(db, c, today, model)
            open_cases.append({**row, "officer": c["officer_name"] or "Unassigned", "last_action": c["last_action_summary"],
                               "last_action_at": (c["last_action_at"] or "")[:10], "next_action": c["next_action"],
                               "next_action_due": c["next_action_due"], "sla_state": st["state"], "due_date": st["due_date"],
                               "breach_probability": p.get("probability"), "breach_band": p.get("band"),
                               "escalation_level": c["escalation_level"]})
    ids = [c["id"] for c in cases]
    recent = db.all(f"SELECT case_id, action_type, action_at, actor_label, bureau_code, remarks FROM case_actions WHERE case_id IN "
                    f"({','.join('?' for _ in ids)}) ORDER BY action_at DESC LIMIT 15", ids) if ids else []
    for a in recent:
        a["label"] = ACTION_TYPES.get(a["action_type"], a["action_type"])
    overlaps = db.all("SELECT * FROM overlap_alerts WHERE institution_id = ? AND status IN ('OPEN','UNDER_REVIEW') ORDER BY "
                      "CASE tier WHEN 'CONFLICT' THEN 0 WHEN 'DUPLICATE' THEN 1 ELSE 2 END, score DESC", (inst_id,))
    ov = []
    for o in overlaps:
        members = [r["case_id"] for r in db.all("SELECT case_id FROM overlap_alert_cases WHERE alert_id = ?", (o["id"],))]
        sig = loads(o["signals_json"], {})
        ov.append({"id": o["id"], "tier": o["tier"], "headline": o["headline"], "status": o["status"], "cases": members,
                   "rules": [r["text"] for p in sig.get("pairs", []) for r in p["rules"]][:6],
                   "recommended_lead": o["recommended_lead"], "decided_lead": o["decided_lead"], "next_step": o["next_step"]})
    risk = risk_index.for_institution(db, inst_id, today)
    escalations = [c for c in open_cases if c["escalation_level"]]
    pending_sla = [c for c in open_cases if c["sla_state"] in ("OVERDUE", "DUE_SOON")]
    predicted = [c for c in open_cases if c["breach_band"] == "HIGH"]
    recs = []
    for o in ov:
        if o["next_step"]:
            recs.append(f"{o['id']} ({o['tier'].lower()}): {o['next_step']}")
    if pending_sla:
        recs.append(f"{len(pending_sla)} open case(s) overdue or due within 3 days — expedite or record reasons.")
    if risk and risk["band"] == "HIGH":
        recs.append("High complaint-burden index: consider an inspection/fact-finding before favourable regulatory decisions.")
    if not recs:
        recs.append("No open coordination concerns recorded for this institution.")
    signals = db.all("SELECT title, publisher, source_url, verification, match_status FROM public_signals WHERE institution_id = ?",
                     (inst_id,))
    seed = db.one("SELECT seed, anchor_date, fingerprint FROM seed_runs ORDER BY id DESC LIMIT 1")
    facts = {
        "institution": {"id": inst["id"], "name": inst["name"], "permanent_id": inst["permanent_id"], "address": inst["address_line"],
                        "district": inst["district"], "state": inst["state"], "region": inst["region_code"],
                        "pincode": inst["pincode"], "intake_total": inst["intake_total"], "intake_source": inst["intake_source"],
                        "courses": loads(inst["courses_json"], []), "established_year": inst["established_year"],
                        "trust": trust["name"] if trust else None,
                        "trust_provenance": trust["provenance"] if trust else None,
                        "synthetic": bool(inst["is_synthetic"]), "demo_tag": inst["demo_tag"]},
        "aliases": [a["alias"] for a in db.all("SELECT alias FROM institution_aliases WHERE institution_id = ?", (inst_id,))],
        "summary": {"total_cases": len(cases), "open_cases": len(open_cases),
                    "overdue_open": sum(1 for c in open_cases if c["sla_state"] == "OVERDUE"),
                    "bureaus_with_open_cases": sorted({c["bureau"] for c in open_cases})},
        "open_cases": open_cases, "case_history": history, "recent_actions": recent, "overlaps": ov,
        "risk": risk, "pending_sla": pending_sla, "predicted_breaches": predicted, "escalations": escalations,
        "recommendations": recs, "public_signals": signals,
    }
    narrative = template_narrative(facts)
    narrative_out = {"text": narrative, "source": "TEMPLATE", "validation": None}
    if narrative_mode == "ai":
        narrative_out = ai_narrative(facts, narrative)
    return {
        **facts, "narrative": narrative_out,
        "provenance": {"generated_at": clock.now_iso(), "generated_by": f"{user.display_name} ({user.role_label})",
                       "as_of": today.isoformat(), "app_version": __version__,
                       "data": "Synthetic demo dataset (seeded) plus any records entered/imported in this instance",
                       "seed": seed, "risk_method": "severity x recency x outcome, intake-normalised, empirical-Bayes shrinkage",
                       "forecast_method": "Hawkes (exponential kernel) MLE with pooled/baseline fallback",
                       "breach_method": "Cox proportional hazards on case history"},
        "disclaimer": data_disclaimer(db) + " This dossier supports a decision; it does not decide legal or regulatory outcomes.",
    }


def template_narrative(f: dict[str, Any]) -> str:
    i, s, risk = f["institution"], f["summary"], f["risk"]
    parts = [f"{i['name']} ({i['permanent_id'] or 'no Permanent ID'}), {i['district']}, {i['state']}"
             + (f", operated by {i['trust']}" if i["trust"] else "") + "."]
    parts.append(f"{s['total_cases']} case record(s) on file, {s['open_cases']} open"
                 + (f" with {', '.join(s['bureaus_with_open_cases'])}" if s["bureaus_with_open_cases"] else "")
                 + (f"; {s['overdue_open']} beyond SLA." if s["overdue_open"] else "."))
    for o in f["overlaps"][:2]:
        lead = o["decided_lead"] or o["recommended_lead"]
        parts.append(f"{o['id']} ({o['tier'].lower()}): {o['headline']} — cases {', '.join(o['cases'])}; "
                     f"{'agreed' if o['decided_lead'] else 'recommended'} lead {lead}.")
    if risk:
        fc = risk["forecast"]
        parts.append(f"Risk Index {risk['score']:.0f}/100 ({risk['band'].lower()}, {risk['trend'].lower()}, "
                     f"{risk['delta_6m']:+.0f} in 6 months); forecast probability of a serious complaint in the next 6 months "
                     f"{round(fc['probability'] * 100)}% ({fc['status'].replace('_', ' ').lower()}, {fc['confidence'].lower()} confidence).")
    if f["predicted_breaches"]:
        parts.append(f"Likely SLA breach: {', '.join(c['id'] for c in f['predicted_breaches'])}.")
    parts.append("Recommended before any decision: " + " ".join(f["recommendations"][:2]))
    return " ".join(parts)


def _allowed_numbers(blob: str) -> set[float]:
    """Numbers grounded in the facts, plus the renderings the template uses (rounded values,
    probabilities shown as percentages)."""
    out: set[float] = set()
    for n in NUM_RE.findall(blob):
        v = float(n)
        out.update({round(v, 2), float(round(v))})
        if v <= 1:
            out.add(float(round(v * 100)))
    return out


def validate_ai_text(text: str, facts: dict[str, Any], template: str = "") -> dict[str, Any]:
    """Reject AI wording that mentions a case/overlap ID or a number (> 12) not present in the
    structured facts or the deterministic template built from them."""
    blob = repr(facts) + " " + template
    ids_ok, nums_ok = set(CASE_ID_RE.findall(blob)), _allowed_numbers(blob)
    bad_ids = sorted(set(CASE_ID_RE.findall(text)) - ids_ok)
    bad_nums = sorted({n for n in NUM_RE.findall(text) if float(n) > 12 and round(float(n), 2) not in nums_ok})
    return {"ok": not bad_ids and not bad_nums, "unknown_ids": bad_ids, "unknown_numbers": bad_nums}


def ai_narrative(facts: dict[str, Any], template: str) -> dict[str, Any]:
    if not llm.available():
        return {"text": template, "source": "TEMPLATE", "validation": {"ok": True, "note": "ANTHROPIC_API_KEY not configured; "
                                                                                          "template narrative used."}}
    out = llm.complete(
        "Rewrite the given institution summary for a senior AICTE official in clear, neutral English (max 170 words). "
        "Use ONLY facts, IDs and numbers that appear in the input. Do not add allegations, conclusions or recommendations "
        "beyond the input. Mention that the data is synthetic.",
        template, max_tokens=400)
    if not out:
        return {"text": template, "source": "TEMPLATE", "validation": {"ok": True, "note": "LLM unavailable; template used."}}
    check = validate_ai_text(out, facts, template)
    if not check["ok"]:
        return {"text": template, "source": "TEMPLATE",
                "validation": {**check, "note": "AI wording rejected: it introduced IDs/numbers not in the database."}}
    return {"text": out, "source": "AI_ASSISTED", "validation": {**check, "note": "AI-assisted wording, validated against "
                                                                               "database facts. Structured sections unchanged."}}
