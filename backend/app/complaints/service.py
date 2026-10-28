"""Complaint intake: live preview (matching, priority, overlaps) and transactional creation."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..audit import chain
from ..conflicts.detector import detect_for_case, evaluate_pairs
from ..core import clock
from ..core.constants import CHANNELS, COMPLAINANT_TYPES, REFERENCE_FLAGS
from ..core.errors import conflict, forbidden, not_found, unprocessable
from ..core.security import User, region_scope
from ..core.util import next_id
from ..institutions import matcher
from ..institutions import service as inst_service
from ..scoring import classifier, priority
from ..scoring.rules import category_rules, get_settings_block
from ..workflow.service import append_action


def _query(p: dict[str, Any]) -> matcher.Query:
    return matcher.Query(raw_name=p["institution_name"], raw_address=p.get("address"), raw_pincode=p.get("pincode"),
                         raw_state=p.get("state"), raw_permanent_id=p.get("permanent_id"))


def _pseudo_case(db, p: dict[str, Any], inst: dict[str, Any] | None, today: date) -> dict[str, Any]:
    rules = category_rules(db)
    rule = rules[p["category_code"]]
    received = p["received_date"]
    return {
        "id": "NEW", "category_code": p["category_code"], "subject": p.get("subject") or "", "description": p.get("description") or "",
        "received_date": received.isoformat(), "bureau_code": p["bureau_code"], "status": "RECEIVED",
        "external_ref": p.get("external_ref"), "complainant_count": p.get("complainant_count", 1),
        "evidence_count": p.get("evidence_count", 0) + len(p.get("evidence_refs") or []),
        "reference_flag": p.get("reference_flag", "NONE"), "sla_days": rule["sla_days"],
        "expected_disposal_date": (received + timedelta(days=int(rule["sla_days"]))).isoformat(),
        "disposed_date": None, "outcome": None, "institution_id": inst["id"] if inst else None,
        "priority_override_band": None, "transfer_count": 0,
    }


def validate_payload(db, p: dict[str, Any], today: date) -> None:
    errors = []
    rules = category_rules(db)
    if p.get("category_code") not in rules:
        errors.append(f"category_code must be one of {sorted(rules)}")
    if not db.one("SELECT 1 FROM bureaus WHERE code = ?", (p.get("bureau_code"),)):
        errors.append("bureau_code is not a known Bureau/Cell")
    rd = p.get("received_date")
    if rd is None or rd > today or rd < date(2000, 1, 1):
        errors.append("received_date must be between 2000-01-01 and today")
    if len((p.get("description") or "").strip()) < 20:
        errors.append("description must be at least 20 characters")
    if len((p.get("subject") or "").strip()) < 5:
        errors.append("subject must be at least 5 characters")
    if len((p.get("institution_name") or "").strip()) < 3:
        errors.append("institution_name is required")
    if p.get("reference_flag", "NONE") not in REFERENCE_FLAGS:
        errors.append(f"reference_flag must be one of {REFERENCE_FLAGS}")
    if p.get("complainant_type", "STUDENT") not in COMPLAINANT_TYPES:
        errors.append(f"complainant_type must be one of {COMPLAINANT_TYPES}")
    if int(p.get("complainant_count", 1)) < 1:
        errors.append("complainant_count must be at least 1")
    if p.get("channel", "INTAKE") not in CHANNELS:
        errors.append(f"channel must be one of {sorted(CHANNELS)}")
    if errors:
        raise unprocessable("Complaint validation failed.", errors)


def preview(db, user: User, p: dict[str, Any]) -> dict[str, Any]:
    today = clock.today()
    validate_payload(db, p, today)
    match = matcher.match(db, _query(p))
    inst = None
    chosen = p.get("institution_id")
    if chosen:
        inst = inst_service.get_institution(db, chosen)
    elif match["decision"] == "AUTO_LINK":
        inst = inst_service.get_institution(db, match["candidates"][0]["institution_id"])
    case = _pseudo_case(db, p, inst, today)
    text = f"{case['subject']}. {case['description']}"
    ml = classifier.predict(text)
    prio = priority.compute(case, category_rules(db), get_settings_block(db, "priority"), today,
                            {"category": ml[0]["category"], "probability": ml[0]["probability"]} if ml else None)
    overlaps: list[dict[str, Any]] = []
    existing: list[dict[str, Any]] = []
    if inst:
        others = db.all("SELECT * FROM complaints WHERE institution_id = ? AND (status != 'DISPOSED' OR received_date >= ?)",
                        (inst["id"], (today - timedelta(days=730)).isoformat()))
        overlaps = evaluate_pairs(db, case, others, today)
        existing = [{k: o[k] for k in ("id", "category_code", "status", "bureau_code", "received_date", "subject")}
                    for o in others if o["status"] != "DISPOSED"]
    duplicates = [o for o in overlaps if o["tier"] == "DUPLICATE"]
    if p.get("source_ref"):
        clash = db.one("SELECT id FROM complaints WHERE source_ref = ? AND source_system = ?",
                       (p["source_ref"], p.get("channel", "INTAKE")))
        if clash:
            duplicates.append({"b": clash["id"], "tier": "DUPLICATE", "rules": [
                {"code": "SRC", "text": f"Source reference {p['source_ref']} already registered as {clash['id']}"}]})
    return {
        "institution_match": match,
        "selected_institution": {k: inst[k] for k in ("id", "name", "permanent_id", "state", "district", "region_code")} if inst else None,
        "priority": prio,
        "ml_suggestion": {"top": ml, "label": "Recommendation only (local TF-IDF + Logistic Regression on synthetic data)"},
        "sla": {"sla_days": case["sla_days"], "due_date": case["expected_disposal_date"]},
        "potential_overlaps": overlaps, "duplicate_warning": bool(duplicates), "duplicates": duplicates,
        "open_cases_at_institution": existing,
    }


def create(db, user: User, p: dict[str, Any]) -> dict[str, Any]:
    """Register a complaint. Match decision: CONFIRM (institution_id), CREATE (new institution) or UNMATCHED."""
    today = clock.today()
    validate_payload(db, p, today)
    if not user.has("case.create"):
        raise forbidden(f"{user.role_label} may not register complaints.")
    if user.role in ("RB_OFFICER", "PGRC_OFFICER") and p["bureau_code"] != user.bureau_code:
        raise forbidden(f"{user.role_label} can register cases for {user.bureau_code} only; route others via that "
                        "Bureau/Cell or the Competent Authority.")
    decision = p.get("match_decision", "CONFIRM")
    if decision not in ("CONFIRM", "CREATE", "UNMATCHED"):
        raise unprocessable("match_decision must be CONFIRM, CREATE or UNMATCHED.")
    with db.tx():
        match = matcher.match(db, _query(p))
        inst = None
        if decision == "CONFIRM":
            if not p.get("institution_id"):
                raise unprocessable("Select the matching institution (institution_id) or choose CREATE / UNMATCHED.")
            inst = inst_service.get_institution(db, p["institution_id"])
        elif decision == "CREATE":
            inst = inst_service.create_institution(db, user, {
                "name": p["institution_name"], "state": p.get("state"), "district": p.get("district"),
                "pincode": p.get("pincode"), "permanent_id": p.get("permanent_id"), "address": p.get("address"),
            }, source="INTAKE")
        scope = region_scope(user)
        region = inst["region_code"] if inst else None
        if region is None and p.get("state"):
            region = db.val("SELECT region_code FROM states WHERE lower(name) = lower(?)", (p["state"],))
        if scope and region != scope:
            raise forbidden("Regional Office users can register complaints only for institutions in their region.")
        if p.get("source_ref") and db.one("SELECT 1 FROM complaints WHERE source_ref = ? AND source_system = ?",
                                          (p["source_ref"], p.get("channel", "INTAKE"))):
            raise conflict(f"Source reference {p['source_ref']} is already registered.")
        if inst and not p.get("acknowledge_duplicates"):
            others = db.all("SELECT * FROM complaints WHERE institution_id = ? AND (status != 'DISPOSED' OR received_date >= ?)",
                            (inst["id"], (today - timedelta(days=730)).isoformat()))
            dups = [o for o in evaluate_pairs(db, _pseudo_case(db, p, inst, today), others, today) if o["tier"] == "DUPLICATE"]
            if dups:
                raise conflict("Possible duplicate of an existing case. Review it, then resubmit with acknowledge_duplicates=true "
                               "if this is a separate complaint.", {"duplicates": [{"case_id": d["b"], "rules": d["rules"]} for d in dups]})
        officer = p.get("assigned_officer_id")
        if officer:
            orow = db.one("SELECT * FROM officers WHERE id = ?", (officer,))
            if orow is None:
                raise not_found("Officer", officer)
            if orow["bureau_code"] != p["bureau_code"]:
                raise unprocessable("Assigned officer must belong to the selected Bureau/Cell.")
        rules = category_rules(db)
        rule = rules[p["category_code"]]
        bureau = p["bureau_code"]
        case_id = next_id(db, f"case:{bureau}", f"{bureau}-", 4, start=10001)
        received = p["received_date"]
        now = clock.now_iso()
        ml = classifier.predict(f"{p['subject']}. {p['description']}", top=1)[0]
        best = match["candidates"][0] if match["candidates"] else None
        conf = None
        if inst and best and best["institution_id"] == inst["id"]:
            conf = best["confidence"]
        state = inst["state"] if inst else p.get("state")
        evidence_refs = p.get("evidence_refs") or []
        row = {
            "id": case_id, "source_system": p.get("channel", "INTAKE"), "source_ref": p.get("source_ref"),
            "external_ref": p.get("external_ref"), "channel": p.get("channel", "INTAKE"),
            "institution_id": inst["id"] if inst else None, "institution_name_raw": p["institution_name"].strip(),
            "institution_address_raw": p.get("address"), "institution_pincode_raw": p.get("pincode"),
            "permanent_id_raw": p.get("permanent_id"),
            "match_status": "CONFIRMED" if inst else "PENDING_REVIEW", "match_confidence": conf,
            "category_code": p["category_code"], "subject": p["subject"].strip(), "description": p["description"].strip(),
            "received_date": received.isoformat(), "bureau_code": bureau, "origin_bureau_code": bureau,
            "assigned_officer_id": officer, "status": "PENDING" if officer else "RECEIVED", "escalation_level": 0,
            "transfer_count": 0, "complainant_count": int(p.get("complainant_count", 1)),
            "complainant_type": p.get("complainant_type", "STUDENT"),
            "evidence_count": int(p.get("evidence_count", 0)) + len(evidence_refs), "evidence_note": p.get("evidence_note"),
            "reference_flag": p.get("reference_flag", "NONE"), "reference_note": p.get("reference_note"),
            "sla_days": int(rule["sla_days"]),
            "expected_disposal_date": (received + timedelta(days=int(rule["sla_days"]))).isoformat(),
            "disposed_date": None, "outcome": None, "outcome_remarks": None, "last_action_type": None,
            "last_action_at": None, "last_action_summary": None,
            "next_action": "Issue notice to institution" if officer else "Acknowledge and assign an officer",
            "next_action_due": (today + timedelta(days=3 if officer else 2)).isoformat(),
            "priority_score": None, "priority_band": None, "priority_computed_at": None, "priority_override_band": None,
            "priority_override_reason": None, "ml_category": ml["category"], "ml_confidence": ml["probability"],
            "master_case_id": None, "region_code": region, "state": state, "is_synthetic": 0, "demo_tag": None,
            "created_at": now, "updated_at": now, "created_by": user.id,
        }
        db.insert("complaints", row)
        doc_ids = []
        for ref in evidence_refs:
            doc_id = next_id(db, "doc", "DOC-", 6)
            db.insert("case_documents", {
                "id": doc_id, "case_id": case_id, "doc_type": "EVIDENCE", "title": (ref.get("title") or "Evidence")[:200],
                "reference_no": ref.get("reference_no"), "file_name": None, "stored_name": None, "mime_type": None,
                "size_bytes": None, "sha256": None, "added_by": user.id, "added_role": user.role, "is_synthetic": 0,
                "created_at": now})
            doc_ids.append(doc_id)
        append_action(db, row, "CREATED", user, remarks=f"Registered via {CHANNELS[row['channel']]} by {user.display_name}.",
                      doc_ids=doc_ids, next_action=row["next_action"], next_action_due=row["next_action_due"])
        if officer:
            append_action(db, row, "ASSIGNED", user, remarks="Assigned at intake.", to_value=officer)
        q = _query(p)
        if inst:
            inst_service.record_review(db, q, match, "INTAKE", case_id, status="CONFIRMED", decided={
                "decided_institution_id": inst["id"], "decided_by": user.id, "decided_role": user.role,
                "decided_at": now, "remarks": "Decided at intake" if decision == "CONFIRM" else "New institution created at intake"})
        else:
            inst_service.record_review(db, q, match, "INTAKE", case_id, status="PENDING")
        priority.recompute_all(db, case_ids=[case_id])
        chain.record(db, user, "CASE_CREATED", "case", case_id, after={
            "institution_id": row["institution_id"], "match_decision": decision, "match_confidence": conf,
            "category_code": row["category_code"], "bureau_code": bureau, "received_date": row["received_date"],
            "ml_category": ml["category"], "ml_confidence": ml["probability"]})
        overlaps = detect_for_case(db, case_id, trigger_type="CASE_CREATED", actor=user) if inst else []
    return {"case_id": case_id, "institution_id": row["institution_id"], "match_status": row["match_status"],
            "overlap_alerts": overlaps}
