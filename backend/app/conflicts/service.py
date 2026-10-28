"""Coordination workflows on overlap alerts: link, Master Case merge/unmerge, lead-Bureau
decisions and alert status. Nothing is ever deleted: original cases keep their IDs,
timelines and audit history; links and memberships are deactivated, not removed.
"""

from __future__ import annotations

from typing import Any

from ..alerts.notify import close_alerts
from ..audit import chain
from ..core import clock
from ..core.errors import bad_request, conflict, forbidden, not_found, unprocessable
from ..core.security import User, region_scope
from ..core.util import loads, next_id
from ..workflow.service import append_action, get_case


def get_alert(db, alert_id: str) -> dict[str, Any]:
    row = db.one("SELECT * FROM overlap_alerts WHERE id = ?", (alert_id,))
    if row is None:
        raise not_found("Overlap alert", alert_id)
    return row


def alert_members(db, alert_id: str) -> list[dict[str, Any]]:
    return db.all("SELECT c.* , oc.role AS alert_role FROM overlap_alert_cases oc JOIN complaints c ON c.id = oc.case_id "
                  "WHERE oc.alert_id = ? ORDER BY oc.role DESC, c.received_date", (alert_id,))


def _involved(user: User, members: list[dict[str, Any]]) -> bool:
    return user.bureau_code is not None and any(m["bureau_code"] == user.bureau_code for m in members)


def _check_view(user: User, alert: dict[str, Any], db) -> None:
    scope = region_scope(user)
    if scope:
        inst = db.one("SELECT region_code FROM institutions WHERE id = ?", (alert["institution_id"],))
        if inst and inst["region_code"] != scope:
            raise forbidden(f"Overlap alert {alert['id']} concerns an institution outside your region.")


def _check_act(user: User, alert: dict[str, Any], members: list[dict[str, Any]], db) -> None:
    """Link / mark-for-review: Competent Authority, an officer of an involved Bureau, or the region's office."""
    user_ok = user.is_authority or (user.has("overlap.act") and (
        _involved(user, members) or (user.role == "REGIONAL_OFFICE" and region_scope(user) is not None)))
    if not user_ok:
        raise forbidden(f"{user.role_label} is not involved in overlap alert {alert['id']}.")
    _check_view(user, alert, db)


def _check_decide(user: User, alert: dict[str, Any], members: list[dict[str, Any]]) -> None:
    """Lead decision / resolve / dismiss. CONFLICT tier: Competent Authority only."""
    if user.is_authority:
        return
    if alert["tier"] == "CONFLICT":
        raise forbidden("Final decisions on cross-bureau CONFLICT alerts are reserved for the Competent Authority.")
    if not (user.has("overlap.decide") and _involved(user, members)):
        raise forbidden(f"{user.role_label} may not decide overlap alert {alert['id']} (not an involved Bureau/Cell).")


def _note_on_members(db, members: list[dict[str, Any]], user: User, text: str, kind: str = "COORDINATION_NOTE") -> None:
    for m in members:
        append_action(db, dict(m), kind, user, remarks=text)


# ----------------------------------------------------------------------------- links
def link_cases(db, user: User, case_a: str, case_b: str, link_type: str, remarks: str | None,
               alert_id: str | None = None) -> dict[str, Any]:
    if link_type not in ("DUPLICATE", "RELATED", "CONFLICT"):
        raise unprocessable("link_type must be DUPLICATE, RELATED or CONFLICT.")
    if case_a == case_b:
        raise unprocessable("A case cannot be linked to itself.")
    a, b = sorted((case_a, case_b))
    with db.tx():
        ca, cb = get_case(db, a), get_case(db, b)
        if ca["institution_id"] is None or ca["institution_id"] != cb["institution_id"]:
            raise unprocessable("Only cases of the same (confirmed) institution can be linked.")
        if alert_id:
            alert = get_alert(db, alert_id)
            members = alert_members(db, alert_id)
            if not {a, b} <= {m["id"] for m in members}:
                raise unprocessable(f"Both cases must belong to overlap alert {alert_id}.")
            _check_act(user, alert, members, db)
        else:
            pseudo = {"id": f"{a}/{b}", "institution_id": ca["institution_id"], "tier": link_type}
            _check_act(user, pseudo, [ca, cb], db)
        if db.one("SELECT 1 FROM case_links WHERE case_a = ? AND case_b = ? AND link_type = ? AND active = 1", (a, b, link_type)):
            raise conflict(f"{a} and {b} are already linked as {link_type}.")
        link_id = next_id(db, "link", "LNK-", 5)
        db.insert("case_links", {
            "id": link_id, "case_a": a, "case_b": b, "link_type": link_type, "overlap_alert_id": alert_id, "active": 1,
            "remarks": remarks, "created_by": user.id, "created_role": user.role, "created_at": clock.now_iso(),
            "removed_by": None, "removed_at": None, "removed_remarks": None,
        })
        for me, other in ((ca, b), (cb, a)):
            append_action(db, me, "LINKED", user, remarks=f"Linked to {other} as {link_type.lower()}"
                          + (f": {remarks}" if remarks else ""), to_value=other)
        chain.record(db, user, "CASES_LINKED", "case_link", link_id,
                     after={"case_a": a, "case_b": b, "link_type": link_type, "overlap_alert_id": alert_id}, remarks=remarks)
    return {"link_id": link_id, "case_a": a, "case_b": b, "link_type": link_type}


def unlink(db, user: User, link_id: str, remarks: str | None) -> dict[str, Any]:
    if not remarks or len(remarks.strip()) < 5:
        raise unprocessable("Remarks are mandatory to remove a link.")
    with db.tx():
        link = db.one("SELECT * FROM case_links WHERE id = ?", (link_id,))
        if link is None:
            raise not_found("Link", link_id)
        if not link["active"]:
            raise conflict("Link already removed.")
        ca, cb = get_case(db, link["case_a"]), get_case(db, link["case_b"])
        pseudo = {"id": link_id, "institution_id": ca["institution_id"], "tier": link["link_type"]}
        _check_act(user, pseudo, [ca, cb], db)
        db.update("case_links", "id", link_id, {"active": 0, "removed_by": user.id, "removed_at": clock.now_iso(),
                                                "removed_remarks": remarks})
        for me, other in ((ca, cb["id"]), (cb, ca["id"])):
            append_action(db, me, "UNLINKED", user, remarks=f"Link to {other} removed: {remarks}", from_value=other)
        chain.record(db, user, "CASES_UNLINKED", "case_link", link_id, before={"active": 1}, after={"active": 0}, remarks=remarks)
    return {"link_id": link_id, "active": False}


# ----------------------------------------------------------------------------- master cases
def _duplicate_evidence(db, case_ids: list[str]) -> bool:
    """True if every case shares a DUPLICATE alert or an active DUPLICATE link with another member."""
    marks = ",".join("?" for _ in case_ids)
    linked: dict[str, set[str]] = {c: set() for c in case_ids}
    for r in db.all(f"SELECT oc.alert_id, oc.case_id FROM overlap_alert_cases oc JOIN overlap_alerts o ON o.id = oc.alert_id "
                    f"WHERE o.tier = 'DUPLICATE' AND oc.case_id IN ({marks})", case_ids):
        linked[r["case_id"]].add(r["alert_id"])
    groups: dict[str, set[str]] = {}
    for c, alerts in linked.items():
        for a in alerts:
            groups.setdefault(a, set()).add(c)
    ok = {c: False for c in case_ids}
    for members in groups.values():
        if len(members) >= 2:
            for c in members:
                ok[c] = True
    for r in db.all(f"SELECT case_a, case_b FROM case_links WHERE active = 1 AND link_type = 'DUPLICATE' AND "
                    f"case_a IN ({marks}) AND case_b IN ({marks})", (*case_ids, *case_ids)):
        ok[r["case_a"]] = ok[r["case_b"]] = True
    return all(ok.values())


def merge(db, user: User, case_ids: list[str], *, kind: str = "DUPLICATE_MERGE", master_case_id: str | None = None,
          title: str | None = None, lead_bureau: str | None = None, remarks: str | None = None,
          alert_id: str | None = None) -> dict[str, Any]:
    """Create (or extend) a Master Case. Originals are preserved and stay individually searchable."""
    if not remarks or len(remarks.strip()) < 5:
        raise unprocessable("Remarks are mandatory when creating or extending a Master Case.")
    if kind not in ("DUPLICATE_MERGE", "COORDINATION"):
        raise unprocessable("kind must be DUPLICATE_MERGE or COORDINATION.")
    case_ids = sorted(set(case_ids))
    with db.tx():
        cases = [get_case(db, c) for c in case_ids]
        master = None
        if master_case_id:
            master = db.one("SELECT * FROM master_cases WHERE id = ?", (master_case_id,))
            if master is None:
                raise not_found("Master Case", master_case_id)
            if master["status"] != "ACTIVE":
                raise conflict("That Master Case is dissolved.")
            kind = master["kind"]
        elif len(cases) < 2:
            raise unprocessable("Select at least two cases to create a Master Case.")
        insts = {c["institution_id"] for c in cases} | ({master["institution_id"]} if master else set())
        if None in insts or len(insts) != 1:
            raise unprocessable("All cases must belong to the same confirmed institution.")
        for c in cases:
            if c["master_case_id"] and c["master_case_id"] != (master or {}).get("id"):
                raise conflict(f"{c['id']} already belongs to Master Case {c['master_case_id']}; unmerge it first.")
        bureaus = {c["bureau_code"] for c in cases}
        if not user.has("overlap.merge"):
            raise forbidden(f"{user.role_label} may not merge cases.")
        if not user.is_authority:
            if kind == "COORDINATION":
                raise forbidden("Coordination Master Cases across Bureaus/Cells are created by the Competent Authority.")
            if bureaus != {user.bureau_code}:
                raise forbidden("Cross-bureau merges need the Competent Authority; officers may merge duplicates "
                                "held by their own Bureau/Cell only.")
        if kind == "DUPLICATE_MERGE":
            check_ids = case_ids + ([m["id"] for m in db.all("SELECT id FROM complaints WHERE master_case_id = ?",
                                                              (master["id"],))] if master else [])
            if not _duplicate_evidence(db, sorted(set(check_ids))):
                raise conflict("These cases are not flagged as duplicates of each other (no DUPLICATE alert or link). "
                               "Link them as duplicates first, or create a COORDINATION Master Case (Competent Authority).")
        if lead_bureau and db.one("SELECT 1 FROM bureaus WHERE code = ?", (lead_bureau,)) is None:
            raise not_found("Bureau/Cell", lead_bureau)
        now = clock.now_iso()
        created = False
        if master is None:
            created = True
            mc_id = next_id(db, "master", "MC-", 4)
            inst_name = db.val("SELECT name FROM institutions WHERE id = ?", (cases[0]["institution_id"],))
            db.insert("master_cases", {
                "id": mc_id, "kind": kind, "institution_id": cases[0]["institution_id"],
                "title": (title or f"{'Duplicate group' if kind == 'DUPLICATE_MERGE' else 'Coordinated matter'} — {inst_name}")[:200],
                "lead_bureau_code": lead_bureau, "status": "ACTIVE", "overlap_alert_id": alert_id, "created_by": user.id,
                "created_role": user.role, "created_at": now, "dissolved_by": None, "dissolved_at": None, "remarks": remarks,
            })
            master = db.one("SELECT * FROM master_cases WHERE id = ?", (mc_id,))
        assert master is not None
        added = []
        for c in cases:
            if c["master_case_id"] == master["id"]:
                continue
            db.insert("master_case_members", {"master_case_id": master["id"], "case_id": c["id"], "added_by": user.id,
                                              "added_at": now, "removed_by": None, "removed_at": None, "remarks": remarks})
            db.update("complaints", "id", c["id"], {"master_case_id": master["id"]})
            c["master_case_id"] = master["id"]
            append_action(db, c, "MERGED_INTO_MASTER", user, remarks=f"Added to Master Case {master['id']}: {remarks}",
                          to_value=master["id"])
            added.append(c["id"])
        if lead_bureau and lead_bureau != master["lead_bureau_code"]:
            db.update("master_cases", "id", master["id"], {"lead_bureau_code": lead_bureau})
        chain.record(db, user, "MASTER_CASE_CREATED" if created else "MASTER_CASE_EXTENDED", "master_case", master["id"],
                     after={"kind": kind, "added_cases": added, "lead_bureau": lead_bureau or master["lead_bureau_code"],
                            "overlap_alert_id": alert_id}, remarks=remarks)
    return {"master_case_id": master["id"], "kind": kind, "added_cases": added, "created": created}


def unmerge(db, user: User, master_case_id: str, case_id: str | None, remarks: str | None) -> dict[str, Any]:
    """Remove one case (or all) from a Master Case. History is kept; the master dissolves below 2 members."""
    if not remarks or len(remarks.strip()) < 5:
        raise unprocessable("Remarks are mandatory to unmerge.")
    with db.tx():
        master = db.one("SELECT * FROM master_cases WHERE id = ?", (master_case_id,))
        if master is None:
            raise not_found("Master Case", master_case_id)
        if master["status"] != "ACTIVE":
            raise conflict("Master Case already dissolved.")
        members = db.all("SELECT * FROM complaints WHERE master_case_id = ?", (master_case_id,))
        if not user.is_authority:
            if not (user.has("overlap.merge") and master["kind"] == "DUPLICATE_MERGE"
                    and {m["bureau_code"] for m in members} == {user.bureau_code}):
                raise forbidden("Unmerge is reserved for the Competent Authority (or the Bureau/Cell that holds all members "
                                "of a duplicate group).")
        targets = [m for m in members if case_id is None or m["id"] == case_id]
        if case_id and not targets:
            raise bad_request(f"{case_id} is not a member of {master_case_id}.")
        now = clock.now_iso()
        for m in targets:
            db.run("UPDATE master_case_members SET removed_by = ?, removed_at = ?, remarks = COALESCE(remarks,'') || ? "
                   "WHERE master_case_id = ? AND case_id = ? AND removed_at IS NULL",
                   (user.id, now, f" | removed: {remarks}", master_case_id, m["id"]))
            db.update("complaints", "id", m["id"], {"master_case_id": None})
            m["master_case_id"] = None
            append_action(db, m, "REMOVED_FROM_MASTER", user, remarks=f"Removed from Master Case {master_case_id}: {remarks}",
                          from_value=master_case_id)
        remaining = db.val("SELECT COUNT(*) FROM complaints WHERE master_case_id = ?", (master_case_id,), 0)
        dissolved = False
        if remaining < 2:
            for m in db.all("SELECT * FROM complaints WHERE master_case_id = ?", (master_case_id,)):
                db.run("UPDATE master_case_members SET removed_by = ?, removed_at = ? WHERE master_case_id = ? AND case_id = ? "
                       "AND removed_at IS NULL", (user.id, now, master_case_id, m["id"]))
                db.update("complaints", "id", m["id"], {"master_case_id": None})
                append_action(db, m, "REMOVED_FROM_MASTER", user,
                              remarks=f"Master Case {master_case_id} dissolved (fewer than two members).", from_value=master_case_id)
            db.update("master_cases", "id", master_case_id, {"status": "DISSOLVED", "dissolved_by": user.id, "dissolved_at": now})
            dissolved = True
        chain.record(db, user, "MASTER_CASE_UNMERGED", "master_case", master_case_id,
                     after={"removed_cases": [m["id"] for m in targets], "dissolved": dissolved}, remarks=remarks)
    return {"master_case_id": master_case_id, "removed_cases": [m["id"] for m in targets], "dissolved": dissolved}


def master_case_detail(db, master_case_id: str) -> dict[str, Any]:
    master = db.one("SELECT * FROM master_cases WHERE id = ?", (master_case_id,))
    if master is None:
        raise not_found("Master Case", master_case_id)
    history = db.all("SELECT * FROM master_case_members WHERE master_case_id = ? ORDER BY added_at, id", (master_case_id,))
    member_ids = sorted({h["case_id"] for h in history})
    cases = db.all(f"SELECT id, status, bureau_code, category_code, received_date, master_case_id, institution_id, subject "
                   f"FROM complaints WHERE id IN ({','.join('?' for _ in member_ids)})", member_ids) if member_ids else []
    return {"master": master, "membership_history": history, "cases": cases}


# ----------------------------------------------------------------------------- decisions
def decide_lead(db, user: User, alert_id: str, decision: str, bureau: str | None, remarks: str | None) -> dict[str, Any]:
    if decision not in ("ACCEPT", "OVERRIDE"):
        raise unprocessable("decision must be ACCEPT or OVERRIDE.")
    if decision == "OVERRIDE" and (not remarks or len(remarks.strip()) < 5):
        raise unprocessable("Remarks are mandatory when overriding the recommended lead Bureau/Cell.")
    with db.tx():
        alert = get_alert(db, alert_id)
        members = alert_members(db, alert_id)
        _check_decide(user, alert, members)
        if alert["status"] in ("RESOLVED", "DISMISSED"):
            raise conflict("Alert is closed.")
        lead = alert["recommended_lead"] if decision == "ACCEPT" else bureau
        if not lead or db.one("SELECT 1 FROM bureaus WHERE code = ?", (lead,)) is None:
            raise unprocessable("A valid lead Bureau/Cell is required.")
        before = {"lead_decision": alert["lead_decision"], "decided_lead": alert["decided_lead"]}
        now = clock.now_iso()
        db.update("overlap_alerts", "id", alert_id, {
            "lead_decision": "ACCEPTED" if decision == "ACCEPT" else "OVERRIDDEN", "decided_lead": lead,
            "decision_remarks": remarks, "decided_by": user.id, "decided_role": user.role, "decided_at": now,
            "status": "UNDER_REVIEW" if alert["status"] == "OPEN" else alert["status"], "updated_at": now,
        })
        text = (f"Lead Bureau/Cell for {alert_id}: {lead} ("
                f"{'recommendation accepted' if decision == 'ACCEPT' else 'recommendation ' + str(alert['recommended_lead']) + ' overridden'})"
                + (f" — {remarks}" if remarks else ""))
        _note_on_members(db, members, user, text)
        db.run("UPDATE master_cases SET lead_bureau_code = ? WHERE overlap_alert_id = ? AND status = 'ACTIVE'", (lead, alert_id))
        chain.record(db, user, "LEAD_BUREAU_" + ("ACCEPTED" if decision == "ACCEPT" else "OVERRIDDEN"), "overlap_alert", alert_id,
                     before=before, after={"decided_lead": lead, "recommended": alert["recommended_lead"]}, remarks=remarks)
    return {"alert_id": alert_id, "decided_lead": lead, "lead_decision": "ACCEPTED" if decision == "ACCEPT" else "OVERRIDDEN"}


def set_status(db, user: User, alert_id: str, status: str, remarks: str | None) -> dict[str, Any]:
    if status not in ("UNDER_REVIEW", "RESOLVED", "DISMISSED", "OPEN"):
        raise unprocessable("status must be UNDER_REVIEW, RESOLVED, DISMISSED or OPEN.")
    if not remarks or len(remarks.strip()) < 5:
        raise unprocessable("Remarks are mandatory for overlap alert decisions.")
    with db.tx():
        alert = get_alert(db, alert_id)
        members = alert_members(db, alert_id)
        if status == "UNDER_REVIEW":
            _check_act(user, alert, members, db)
        else:
            _check_decide(user, alert, members)
        if alert["status"] == status:
            raise conflict(f"Alert is already {status}.")
        now = clock.now_iso()
        db.update("overlap_alerts", "id", alert_id, {"status": status, "status_remarks": remarks, "status_by": user.id,
                                                    "status_at": now, "updated_at": now})
        if status in ("RESOLVED", "DISMISSED"):
            close_alerts(db, where="overlap_alert_id = ?", params=(alert_id,), state="RESOLVED", actor_id=user.id,
                         remarks=f"Overlap alert {status.lower()}: {remarks}")
            _note_on_members(db, members, user, f"Overlap alert {alert_id} {status.lower()}: {remarks}")
        chain.record(db, user, f"OVERLAP_{status}", "overlap_alert", alert_id, before={"status": alert["status"]},
                     after={"status": status}, remarks=remarks)
    return {"alert_id": alert_id, "status": status}


def signals_of(alert: dict[str, Any]) -> dict[str, Any]:
    return loads(alert["signals_json"], {})


def recommendation_of(alert: dict[str, Any]) -> dict[str, Any]:
    return loads(alert["recommendation_json"], {})

