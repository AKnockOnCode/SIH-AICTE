"""Institution Master operations and the human match-review workflow."""

from __future__ import annotations

from typing import Any

from ..alerts.notify import close_alerts, raise_alert
from ..audit import chain
from ..core import clock
from ..core.errors import conflict, forbidden, not_found, unprocessable
from ..core.security import User, region_scope
from ..core.util import dumps, loads, next_id
from ..scoring.rules import get_settings_block
from . import matcher
from .normalize import normalize_name, normalize_permanent_id, normalize_pincode


def get_institution(db, inst_id: str) -> dict[str, Any]:
    row = db.one("SELECT * FROM institutions WHERE id = ?", (inst_id,))
    if row is None:
        raise not_found("Institution", inst_id)
    return row


def record_review(db, q: matcher.Query, result: dict[str, Any], source_type: str, source_ref: str | None,
                  status: str = "PENDING", decided: dict[str, Any] | None = None) -> str:
    review_id = next_id(db, "review", "MR-", 5)
    best = result["candidates"][0] if result["candidates"] else None
    row = {
        "id": review_id, "raw_name": q.raw_name, "raw_norm": normalize_name(q.raw_name), "raw_address": q.raw_address,
        "raw_pincode": q.raw_pincode, "raw_state": q.raw_state, "raw_permanent_id": q.raw_permanent_id,
        "source_type": source_type, "source_ref": source_ref, "best_institution_id": best["institution_id"] if best else None,
        "best_confidence": best["confidence"] if best else None, "candidates_json": dumps(result["candidates"]),
        "status": status, "decided_institution_id": None, "decided_by": None, "decided_role": None, "decided_at": None,
        "remarks": None, "created_at": clock.now_iso(),
    }
    if decided:
        row.update(decided)
    db.insert("match_reviews", row)
    if status == "PENDING":
        region = None
        if source_ref:
            region = db.val("SELECT region_code FROM complaints WHERE id = ?", (source_ref,))
        raise_alert(db, alert_type="MATCH_REVIEW", severity="INFO",
                    title=f"Institution match needs review: '{q.raw_name[:60]}'",
                    message=(f"Best candidate {best['name']} ({best['confidence']:.0%})" if best else "No reliable candidate")
                    + f" — {result['reason']}. Source {source_type} {source_ref or ''}.",
                    dedupe_key=f"MATCH_REVIEW:{review_id}", case_id=source_ref if source_type != "IMPORT" else None,
                    target_region=region)
    return review_id


def get_review(db, review_id: str) -> dict[str, Any]:
    row = db.one("SELECT * FROM match_reviews WHERE id = ?", (review_id,))
    if row is None:
        raise not_found("Match review", review_id)
    row["candidates"] = loads(row.pop("candidates_json"), [])
    return row


def _check_review_access(user: User, review: dict[str, Any], db) -> None:
    if not user.has("match.review"):
        raise forbidden(f"{user.role_label} may not decide institution matches.")
    scope = region_scope(user)
    if scope and review.get("source_ref"):
        region = db.val("SELECT region_code FROM complaints WHERE id = ?", (review["source_ref"],))
        if region and region != scope:
            raise forbidden("This match review concerns a case outside your region.")


def link_case(db, user: User, case_id: str, inst: dict[str, Any], status: str, confidence: float | None,
              remarks: str | None = None) -> list[dict[str, Any]]:
    from ..workflow.service import append_action, get_case

    case = get_case(db, case_id)
    before = {"institution_id": case["institution_id"], "match_status": case["match_status"]}
    db.update("complaints", "id", case_id, {"institution_id": inst["id"], "match_status": status,
                                            "match_confidence": confidence, "region_code": inst["region_code"],
                                            "state": inst["state"]})
    append_action(db, case, "INSTITUTION_MATCH", user, remarks=f"Linked to {inst['name']} ({inst['id']})"
                  + (f": {remarks}" if remarks else ""), from_value=before["institution_id"], to_value=inst["id"])
    chain.record(db, user, "CASE_INSTITUTION_LINKED", "case", case_id, before=before,
                 after={"institution_id": inst["id"], "match_status": status, "confidence": confidence}, remarks=remarks)
    from ..conflicts.detector import detect_for_case

    return detect_for_case(db, case_id, trigger_type="CASE_UPDATED", actor=user)


def _candidate_conf(review: dict[str, Any], inst_id: str) -> float | None:
    for c in review["candidates"]:
        if c["institution_id"] == inst_id:
            return c["confidence"]
    return None


def confirm(db, user: User, review_id: str, institution_id: str, remarks: str | None = None) -> dict[str, Any]:
    with db.tx():
        review = get_review(db, review_id)
        _check_review_access(user, review, db)
        if review["status"] not in ("PENDING", "REJECTED"):
            raise conflict(f"Review {review_id} is already {review['status']}.")
        inst = get_institution(db, institution_id)
        now = clock.now_iso()
        db.update("match_reviews", "id", review_id, {
            "status": "CONFIRMED", "decided_institution_id": institution_id, "decided_by": user.id,
            "decided_role": user.role, "decided_at": now, "remarks": remarks})
        alias_norm = normalize_name(review["raw_name"])
        if alias_norm and alias_norm != inst["name_norm"]:
            db.run("INSERT OR IGNORE INTO institution_aliases(institution_id, alias, alias_norm, alias_type, source, created_by, "
                   "created_at) VALUES (?,?,?,?,?,?,?)",
                   (institution_id, review["raw_name"], alias_norm, "CONFIRMED_MATCH", review_id, user.id, now))
        db.insert("match_feedback", {"raw_norm": alias_norm, "institution_id": institution_id, "decision": "CONFIRM",
                                     "review_id": review_id, "decided_by": user.id, "created_at": now})
        overlaps: list[dict[str, Any]] = []
        if review["source_ref"] and db.one("SELECT 1 FROM complaints WHERE id = ?", (review["source_ref"],)):
            overlaps = link_case(db, user, review["source_ref"], inst, "CONFIRMED", _candidate_conf(review, institution_id),
                                 remarks or f"Match review {review_id} confirmed")
        close_alerts(db, where="dedupe_key = ?", params=(f"MATCH_REVIEW:{review_id}",), state="RESOLVED",
                     actor_id=user.id, remarks="Match confirmed")
        chain.record(db, user, "MATCH_CONFIRMED", "match_review", review_id,
                     before={"status": review["status"]},
                     after={"institution_id": institution_id, "raw_name": review["raw_name"],
                            "confidence": _candidate_conf(review, institution_id), "alias_added": alias_norm != inst["name_norm"]},
                     remarks=remarks)
    return {"review_id": review_id, "status": "CONFIRMED", "institution_id": institution_id, "overlap_alerts": overlaps}


def reject(db, user: User, review_id: str, institution_id: str, remarks: str | None = None) -> dict[str, Any]:
    if not remarks or len(remarks.strip()) < 5:
        raise unprocessable("Remarks are mandatory when rejecting a match (they train future matching).")
    with db.tx():
        review = get_review(db, review_id)
        _check_review_access(user, review, db)
        if review["status"] not in ("PENDING", "REJECTED"):
            raise conflict(f"Review {review_id} is already {review['status']}.")
        get_institution(db, institution_id)
        now = clock.now_iso()
        db.insert("match_feedback", {"raw_norm": normalize_name(review["raw_name"]), "institution_id": institution_id,
                                     "decision": "REJECT", "review_id": review_id, "decided_by": user.id, "created_at": now})
        remaining = [c for c in review["candidates"] if c["institution_id"] != institution_id]
        review_t = float(get_settings_block(db, "matching")["review_threshold"])
        still_plausible = [c for c in remaining if c["confidence"] >= review_t]
        new_status = "PENDING" if still_plausible else "REJECTED"
        best = remaining[0] if remaining else None
        db.update("match_reviews", "id", review_id, {
            "status": new_status, "candidates_json": dumps(remaining),
            "best_institution_id": best["institution_id"] if best else None,
            "best_confidence": best["confidence"] if best else None,
            "remarks": ((review["remarks"] or "") + f" | rejected {institution_id}: {remarks}").strip(" |")})
        chain.record(db, user, "MATCH_REJECTED", "match_review", review_id,
                     before={"status": review["status"]}, after={"rejected_institution_id": institution_id, "status": new_status},
                     remarks=remarks)
    return {"review_id": review_id, "status": new_status, "remaining_candidates": len(remaining)}


def create_institution(db, user: User, fields: dict[str, Any], source: str) -> dict[str, Any]:
    name = (fields.get("name") or "").strip()
    state = (fields.get("state") or "").strip()
    if len(name) < 4:
        raise unprocessable("Institution name is required.")
    st = db.one("SELECT * FROM states WHERE lower(name) = lower(?)", (state,))
    if st is None:
        raise unprocessable(f"State '{state}' is not recognised. Use one of the configured states.")
    pid = normalize_permanent_id(fields.get("permanent_id"))
    if pid and db.one("SELECT id FROM institutions WHERE permanent_id = ?", (pid,)):
        raise conflict(f"Permanent ID {pid} already exists in the Institution Master.")
    inst_id = next_id(db, "institution", "INS-", 4, start=int(db.val("SELECT COUNT(*) FROM institutions", default=0)) + 1)
    while db.one("SELECT 1 FROM institutions WHERE id = ?", (inst_id,)):
        inst_id = next_id(db, "institution", "INS-", 4)
    now = clock.now_iso()
    row = {
        "id": inst_id, "permanent_id": pid, "name": name, "name_norm": normalize_name(name),
        "institution_type": fields.get("institution_type"), "address_line": fields.get("address"),
        "city": fields.get("city") or fields.get("district"), "district": fields.get("district"), "state": st["name"],
        "region_code": st["region_code"], "pincode": normalize_pincode(fields.get("pincode")),
        "established_year": fields.get("established_year"), "intake_total": fields.get("intake_total"),
        "intake_source": fields.get("intake_source") or (source if fields.get("intake_total") else None),
        "courses_json": dumps(fields.get("courses") or []), "trust_id": fields.get("trust_id"),
        "trust_relation_source": fields.get("trust_relation_source"), "status": "ACTIVE",
        "is_synthetic": int(bool(fields.get("is_synthetic", False))),
        "provenance_json": dumps(fields.get("provenance") or {"source": source, "created_by": user.id}),
        "demo_tag": None, "created_at": now, "updated_at": now,
    }
    db.insert("institutions", row)
    chain.record(db, user, "INSTITUTION_CREATED", "institution", inst_id, after={k: row[k] for k in (
        "name", "permanent_id", "state", "district", "pincode", "intake_total")}, remarks=f"source={source}")
    return row


def resolve_with_new_institution(db, user: User, review_id: str, fields: dict[str, Any], remarks: str | None) -> dict[str, Any]:
    with db.tx():
        review = get_review(db, review_id)
        _check_review_access(user, review, db)
        if review["status"] not in ("PENDING", "REJECTED"):
            raise conflict(f"Review {review_id} is already {review['status']}.")
        fields = {"name": review["raw_name"], **{k: v for k, v in fields.items() if v not in (None, "")}}
        inst = create_institution(db, user, fields, source=f"MATCH_REVIEW:{review_id}")
        now = clock.now_iso()
        db.update("match_reviews", "id", review_id, {"status": "NEW_INSTITUTION", "decided_institution_id": inst["id"],
                                                    "decided_by": user.id, "decided_role": user.role, "decided_at": now,
                                                    "remarks": remarks})
        overlaps: list[dict[str, Any]] = []
        if review["source_ref"] and db.one("SELECT 1 FROM complaints WHERE id = ?", (review["source_ref"],)):
            overlaps = link_case(db, user, review["source_ref"], inst, "CONFIRMED", None,
                                 remarks or "New institution created from match review")
        close_alerts(db, where="dedupe_key = ?", params=(f"MATCH_REVIEW:{review_id}",), state="RESOLVED",
                     actor_id=user.id, remarks="New institution created")
        chain.record(db, user, "MATCH_NEW_INSTITUTION", "match_review", review_id,
                     after={"institution_id": inst["id"], "name": inst["name"]}, remarks=remarks)
    return {"review_id": review_id, "status": "NEW_INSTITUTION", "institution_id": inst["id"], "overlap_alerts": overlaps}
