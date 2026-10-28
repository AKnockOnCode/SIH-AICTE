"""Case workflow operations: actions, status, assignment, transfer, escalation, disposal,
documents and priority overrides. Every operation checks object-level permissions, writes a
timeline action, refreshes cached fields and appends to the audit chain in one transaction.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

from ..alerts.notify import close_alerts, raise_alert
from ..audit import chain
from ..core import clock
from ..core.constants import (
    ACTION_TYPES,
    MANUAL_ACTIONS,
    OPEN_STATUSES,
    OUTCOMES,
    PRIORITY_BANDS,
    REGULATORY_ACTIONS,
    STATUS_LABELS,
    STATUS_TRANSITIONS,
)
from ..core.errors import bad_request, conflict, not_found, unprocessable
from ..core.security import User, assert_can_view_case, assert_case_op
from ..core.util import dumps, next_id, safe_filename
from ..scoring import priority as priority_mod

AUDIT_FIELDS = ("status", "bureau_code", "assigned_officer_id", "escalation_level", "transfer_count", "outcome",
                "disposed_date", "priority_override_band", "next_action", "next_action_due", "institution_id",
                "match_status", "category_code", "master_case_id")


def get_case(db, case_id: str) -> dict[str, Any]:
    row = db.one("SELECT * FROM complaints WHERE id = ?", (case_id,))
    if row is None:
        raise not_found("Case", case_id)
    return row


def _snapshot(case: dict[str, Any]) -> dict[str, Any]:
    return {k: case.get(k) for k in AUDIT_FIELDS}


def actor_label(user: User) -> str:
    if user.officer_id:
        return f"{user.display_name} [{user.officer_id}]"
    return user.display_name


def append_action(db, case: dict[str, Any], action_type: str, user: User, *, remarks: str | None = None,
                  from_value: str | None = None, to_value: str | None = None, next_action: str | None = None,
                  next_action_due: str | None = None, doc_ids: list[str] | None = None) -> int:
    now = clock.now_iso()
    action_id = db.insert("case_actions", {
        "case_id": case["id"], "action_type": action_type, "action_at": now, "actor_id": user.id,
        "actor_label": actor_label(user), "actor_role": user.role, "bureau_code": user.bureau_code or case["bureau_code"],
        "officer_id": user.officer_id, "remarks": remarks, "from_value": from_value, "to_value": to_value,
        "next_action": next_action, "next_action_due": next_action_due, "doc_ids_json": dumps(doc_ids or []),
        "is_synthetic": 0, "created_at": now,
    })
    summary = ACTION_TYPES.get(action_type, action_type) + (f": {remarks}" if remarks else "")
    changes: dict[str, Any] = {"last_action_type": action_type, "last_action_at": now,
                               "last_action_summary": summary[:300], "updated_at": now}
    if next_action is not None:
        changes["next_action"] = next_action
        changes["next_action_due"] = next_action_due
    db.update("complaints", "id", case["id"], changes)
    case.update(changes)
    return action_id


def _refresh_priority(db, case_id: str) -> None:
    priority_mod.recompute_all(db, case_ids=[case_id])


def _require_remarks(remarks: str | None, what: str) -> str:
    if not remarks or len(remarks.strip()) < 5:
        raise unprocessable(f"Remarks (at least 5 characters) are mandatory for {what}.")
    return remarks.strip()


# ----------------------------------------------------------------------------- actions
def add_action(db, user: User, case_id: str, action_type: str, remarks: str | None = None,
               next_action: str | None = None, next_action_due: date | None = None,
               doc_ids: list[str] | None = None) -> dict[str, Any]:
    if action_type not in MANUAL_ACTIONS and action_type not in REGULATORY_ACTIONS:
        raise bad_request(f"Action type '{action_type}' cannot be added directly. Allowed: "
                          f"{', '.join(MANUAL_ACTIONS + REGULATORY_ACTIONS)}")
    with db.tx():
        case = get_case(db, case_id)
        assert_can_view_case(user, case)
        if action_type in REGULATORY_ACTIONS:
            op = "regulatory_action"
        elif action_type == "REMARK":
            op = "remark"
        else:
            op = "status"
        assert_case_op(user, case, op)
        if case["status"] == "DISPOSED" and action_type != "REMARK":
            raise conflict(f"Case {case_id} is disposed; re-open it before adding '{action_type}'.")
        if action_type == "REMARK" and not (remarks or "").strip():
            raise unprocessable("A remark needs text.")
        before = _snapshot(case)
        act_id = append_action(db, case, action_type, user, remarks=remarks, next_action=next_action,
                               next_action_due=next_action_due.isoformat() if next_action_due else None, doc_ids=doc_ids)
        chain.record(db, user, f"CASE_ACTION_{action_type}", "case", case_id, before=before,
                     after={**_snapshot(case), "action_id": act_id}, remarks=remarks)
        overlaps: list[dict[str, Any]] = []
        if action_type in REGULATORY_ACTIONS:
            from ..conflicts.detector import detect_for_case

            overlaps = detect_for_case(db, case_id, trigger_type="ACTION_ADDED",
                                       trigger_action={"id": act_id, "action_type": action_type,
                                                       "action_at": case["last_action_at"],
                                                       "bureau_code": user.bureau_code or case["bureau_code"]},
                                       actor=user)
        _refresh_priority(db, case_id)
    return {"action_id": act_id, "case_id": case_id, "overlap_alerts": overlaps}


def change_status(db, user: User, case_id: str, new_status: str, remarks: str | None = None) -> dict[str, Any]:
    with db.tx():
        case = get_case(db, case_id)
        assert_can_view_case(user, case)
        assert_case_op(user, case, "status")
        allowed = STATUS_TRANSITIONS.get(case["status"], set())
        if new_status not in allowed:
            raise conflict(f"Cannot change status from {STATUS_LABELS[case['status']]} to "
                           f"{STATUS_LABELS.get(new_status, new_status)}. Use transfer/escalate/dispose for those steps.",
                           {"allowed": sorted(allowed)})
        before = _snapshot(case)
        db.update("complaints", "id", case_id, {"status": new_status})
        case["status"] = new_status
        append_action(db, case, "STATUS_CHANGED", user, remarks=remarks, from_value=before["status"], to_value=new_status)
        chain.record(db, user, "CASE_STATUS_CHANGED", "case", case_id, before=before, after=_snapshot(case), remarks=remarks)
        _refresh_priority(db, case_id)
    return {"case_id": case_id, "status": new_status}


def assign(db, user: User, case_id: str, officer_id: str, remarks: str | None = None) -> dict[str, Any]:
    with db.tx():
        case = get_case(db, case_id)
        assert_can_view_case(user, case)
        assert_case_op(user, case, "assign")
        officer = db.one("SELECT * FROM officers WHERE id = ? AND active = 1", (officer_id,))
        if officer is None:
            raise not_found("Officer", officer_id)
        if officer["bureau_code"] != case["bureau_code"]:
            raise unprocessable(f"Officer {officer_id} belongs to {officer['bureau_code']}, but the case is with "
                                f"{case['bureau_code']}. Transfer the case first.")
        if case["status"] == "DISPOSED":
            raise conflict("Disposed cases cannot be reassigned.")
        before = _snapshot(case)
        changes: dict[str, Any] = {"assigned_officer_id": officer_id}
        if case["status"] in ("RECEIVED", "TRANSFERRED"):
            changes["status"] = "PENDING"
        db.update("complaints", "id", case_id, changes)
        case.update(changes)
        append_action(db, case, "ASSIGNED", user, remarks=remarks or f"Assigned to {officer['display_name']}.",
                      from_value=before["assigned_officer_id"], to_value=officer_id)
        chain.record(db, user, "CASE_ASSIGNED", "case", case_id, before=before, after=_snapshot(case), remarks=remarks)
    return {"case_id": case_id, "assigned_officer_id": officer_id, "status": case["status"]}


def transfer(db, user: User, case_id: str, to_bureau: str, remarks: str | None) -> dict[str, Any]:
    remarks = _require_remarks(remarks, "a transfer")
    with db.tx():
        case = get_case(db, case_id)
        assert_can_view_case(user, case)
        assert_case_op(user, case, "transfer")
        if db.one("SELECT 1 FROM bureaus WHERE code = ?", (to_bureau,)) is None:
            raise not_found("Bureau/Cell", to_bureau)
        if to_bureau == case["bureau_code"]:
            raise unprocessable("The case is already with that Bureau/Cell.")
        if case["status"] == "DISPOSED":
            raise conflict("Disposed cases cannot be transferred.")
        before = _snapshot(case)
        changes = {"bureau_code": to_bureau, "status": "TRANSFERRED", "assigned_officer_id": None,
                   "transfer_count": int(case["transfer_count"]) + 1}
        db.update("complaints", "id", case_id, changes)
        case.update(changes)
        append_action(db, case, "TRANSFERRED", user, remarks=remarks, from_value=before["bureau_code"], to_value=to_bureau,
                      next_action="Receiving Bureau/Cell to accept transfer and assign officer",
                      next_action_due=(clock.today() + timedelta(days=3)).isoformat())
        raise_alert(db, alert_type="PENDING_REMINDER", severity="WARNING",
                    title=f"Case {case_id} transferred to {to_bureau}",
                    message=f"Transferred from {before['bureau_code']} by {user.display_name}: {remarks}",
                    dedupe_key=f"TRANSFER:{case_id}:{case['transfer_count']}", institution_id=case["institution_id"],
                    case_id=case_id, target_bureau=to_bureau, target_region=case["region_code"])
        chain.record(db, user, "CASE_TRANSFERRED", "case", case_id, before=before, after=_snapshot(case), remarks=remarks)
        from ..conflicts.detector import detect_for_case

        overlaps = detect_for_case(db, case_id, trigger_type="CASE_UPDATED", actor=user)
        _refresh_priority(db, case_id)
    return {"case_id": case_id, "bureau_code": to_bureau, "status": "TRANSFERRED", "overlap_alerts": overlaps}


def escalate(db, user: User, case_id: str, remarks: str | None) -> dict[str, Any]:
    remarks = _require_remarks(remarks, "an escalation")
    with db.tx():
        case = get_case(db, case_id)
        assert_can_view_case(user, case)
        assert_case_op(user, case, "escalate")
        if case["status"] == "DISPOSED":
            raise conflict("Disposed cases cannot be escalated.")
        before = _snapshot(case)
        level = int(case["escalation_level"]) + 1
        changes = {"status": "ESCALATED", "escalation_level": level}
        db.update("complaints", "id", case_id, changes)
        case.update(changes)
        append_action(db, case, "ESCALATED", user, remarks=remarks, from_value=before["status"],
                      to_value="COMPETENT_AUTHORITY", next_action="Competent Authority to review escalation",
                      next_action_due=(clock.today() + timedelta(days=7)).isoformat())
        for target in (None, case["bureau_code"]):
            raise_alert(db, alert_type="ESCALATION", severity="CRITICAL",
                        title=f"Escalation (level {level}): case {case_id}",
                        message=f"Escalated by {user.display_name} ({user.role_label}): {remarks}",
                        dedupe_key=f"ESCALATION:{case_id}:{level}:{target}", institution_id=case["institution_id"],
                        case_id=case_id, target_bureau=target, target_region=case["region_code"])
        chain.record(db, user, "CASE_ESCALATED", "case", case_id, before=before, after=_snapshot(case), remarks=remarks)
        _refresh_priority(db, case_id)
    return {"case_id": case_id, "status": "ESCALATED", "escalation_level": level}


def deescalate(db, user: User, case_id: str, remarks: str | None) -> dict[str, Any]:
    remarks = _require_remarks(remarks, "reviewing an escalation")
    with db.tx():
        case = get_case(db, case_id)
        assert_case_op(user, case, "deescalate")
        if case["status"] != "ESCALATED":
            raise conflict("Only escalated cases can be de-escalated.")
        before = _snapshot(case)
        db.update("complaints", "id", case_id, {"status": "UNDER_PROCESS"})
        case["status"] = "UNDER_PROCESS"
        append_action(db, case, "DEESCALATED", user, remarks=remarks, from_value="ESCALATED", to_value="UNDER_PROCESS")
        close_alerts(db, where="case_id = ? AND alert_type = 'ESCALATION'", params=(case_id,), state="RESOLVED",
                     actor_id=user.id, remarks=f"Escalation reviewed: {remarks}")
        chain.record(db, user, "CASE_DEESCALATED", "case", case_id, before=before, after=_snapshot(case), remarks=remarks)
    return {"case_id": case_id, "status": "UNDER_PROCESS"}


def dispose(db, user: User, case_id: str, outcome: str, remarks: str | None) -> dict[str, Any]:
    remarks = _require_remarks(remarks, "disposal")
    if outcome not in OUTCOMES:
        raise unprocessable(f"Outcome must be one of {OUTCOMES}.")
    with db.tx():
        case = get_case(db, case_id)
        assert_can_view_case(user, case)
        assert_case_op(user, case, "dispose")
        if case["status"] == "DISPOSED":
            raise conflict("Case is already disposed.")
        before = _snapshot(case)
        today = clock.today().isoformat()
        changes = {"status": "DISPOSED", "disposed_date": today, "outcome": outcome, "outcome_remarks": remarks,
                   "next_action": None, "next_action_due": None}
        db.update("complaints", "id", case_id, changes)
        case.update(changes)
        append_action(db, case, "DISPOSED", user, remarks=remarks, from_value=before["status"], to_value=outcome)
        close_alerts(db, where="case_id = ? AND alert_type IN ('SLA_WARNING','SLA_OVERDUE','PENDING_REMINDER','PREDICTED_BREACH','ESCALATION')",
                     params=(case_id,), state="RESOLVED", actor_id=user.id, remarks="Case disposed.")
        chain.record(db, user, "CASE_DISPOSED", "case", case_id, before=before, after=_snapshot(case), remarks=remarks)
        _refresh_priority(db, case_id)
    return {"case_id": case_id, "status": "DISPOSED", "outcome": outcome}


def reopen(db, user: User, case_id: str, remarks: str | None) -> dict[str, Any]:
    remarks = _require_remarks(remarks, "re-opening")
    with db.tx():
        case = get_case(db, case_id)
        if not user.is_authority:
            assert_case_op(user, case, "deescalate")
        if case["status"] != "DISPOSED":
            raise conflict("Only disposed cases can be re-opened.")
        before = _snapshot(case)
        changes = {"status": "UNDER_PROCESS", "disposed_date": None, "outcome": None, "outcome_remarks": None}
        db.update("complaints", "id", case_id, changes)
        case.update(changes)
        append_action(db, case, "REOPENED", user, remarks=remarks, from_value="DISPOSED", to_value="UNDER_PROCESS")
        chain.record(db, user, "CASE_REOPENED", "case", case_id, before=before, after=_snapshot(case), remarks=remarks)
        _refresh_priority(db, case_id)
    return {"case_id": case_id, "status": "UNDER_PROCESS"}


ALLOWED_UPLOADS = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".txt": "text/plain"}


def add_document(db, user: User, case_id: str, doc_type: str, title: str, reference_no: str | None = None,
                 file_name: str | None = None, content: bytes | None = None) -> dict[str, Any]:
    from ..core.config import get_settings

    if doc_type not in ("LETTER", "REPORT", "EVIDENCE", "NOTICE", "REPLY", "ORDER", "OTHER"):
        raise unprocessable("doc_type must be LETTER, REPORT, EVIDENCE, NOTICE, REPLY, ORDER or OTHER.")
    if not title or len(title.strip()) < 3:
        raise unprocessable("A document title is required.")
    stored_name = mime = sha = None
    size = None
    if content is not None:
        settings = get_settings()
        ext = "." + (file_name or "").rsplit(".", 1)[-1].lower() if file_name and "." in file_name else ""
        if ext not in ALLOWED_UPLOADS:
            raise unprocessable(f"File type not allowed. Allowed: {', '.join(sorted(ALLOWED_UPLOADS))}.")
        if len(content) > settings.max_upload_mb * 1024 * 1024:
            raise unprocessable(f"File larger than {settings.max_upload_mb} MB.")
        if not content:
            raise unprocessable("Uploaded file is empty.")
        sha = hashlib.sha256(content).hexdigest()
        size = len(content)
        mime = ALLOWED_UPLOADS[ext]
    with db.tx():
        case = get_case(db, case_id)
        assert_can_view_case(user, case)
        assert_case_op(user, case, "document")
        doc_id = next_id(db, "doc", "DOC-", 6)
        if content is not None:
            settings = get_settings()
            folder = settings.storage_dir / "documents" / safe_filename(case_id)
            folder.mkdir(parents=True, exist_ok=True)
            stored_name = f"{doc_id}{ext}"
            (folder / stored_name).write_bytes(content)
        db.insert("case_documents", {
            "id": doc_id, "case_id": case_id, "doc_type": doc_type, "title": title.strip()[:200],
            "reference_no": (reference_no or "").strip()[:100] or None,
            "file_name": safe_filename(file_name) if file_name else None, "stored_name": stored_name,
            "mime_type": mime, "size_bytes": size, "sha256": sha, "added_by": user.id, "added_role": user.role,
            "is_synthetic": 0, "created_at": clock.now_iso(),
        })
        if doc_type == "EVIDENCE":
            db.run("UPDATE complaints SET evidence_count = evidence_count + 1 WHERE id = ?", (case_id,))
        append_action(db, case, "DOCUMENT_ADDED", user, remarks=f"{doc_type.title()}: {title.strip()[:120]}"
                      + (f" (ref {reference_no})" if reference_no else ""), doc_ids=[doc_id])
        chain.record(db, user, "DOCUMENT_ADDED", "case", case_id,
                     after={"document_id": doc_id, "doc_type": doc_type, "title": title, "reference_no": reference_no,
                            "sha256": sha, "size_bytes": size})
        _refresh_priority(db, case_id)
    return {"document_id": doc_id, "case_id": case_id, "stored": stored_name is not None, "sha256": sha}


def override_priority(db, user: User, case_id: str, band: str | None, reason: str | None) -> dict[str, Any]:
    reason = _require_remarks(reason, "a priority override")
    if band is not None and band not in PRIORITY_BANDS:
        raise unprocessable(f"band must be one of {PRIORITY_BANDS} (or null to clear the override).")
    with db.tx():
        case = get_case(db, case_id)
        assert_can_view_case(user, case)
        assert_case_op(user, case, "priority_override")
        computed = priority_mod.compute_for_case(db, case)
        previous = case["priority_override_band"] or computed["band"]
        db.insert("priority_overrides", {
            "case_id": case_id, "previous_band": previous, "previous_score": computed["score"], "new_band": band,
            "reason": reason, "actor_id": user.id, "actor_role": user.role,
            "bureau_code": user.bureau_code or case["bureau_code"], "created_at": clock.now_iso(),
        })
        db.update("complaints", "id", case_id, {"priority_override_band": band, "priority_override_reason": reason if band else None})
        case["priority_override_band"] = band
        append_action(db, case, "PRIORITY_OVERRIDE", user, remarks=reason, from_value=previous,
                      to_value=band or f"(cleared — computed {computed['band']})")
        chain.record(db, user, "PRIORITY_OVERRIDE", "case", case_id,
                     before={"band": previous, "score": computed["score"]},
                     after={"band": band or computed["band"], "override": band}, remarks=reason)
    return {"case_id": case_id, "previous_band": previous, "new_band": band or computed["band"], "override": band}


def is_open(case: dict[str, Any]) -> bool:
    return case["status"] in OPEN_STATUSES
