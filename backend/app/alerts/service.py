"""Alert sweep (SLA, reminders, predicted breaches, escalations, match reviews, audit
integrity) and Alerts-Centre operations. Alerts are in-app records only (channel IN_APP);
the prototype does not send email or SMS.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..audit import chain
from ..core import clock
from ..core.errors import conflict, forbidden, not_found, unprocessable
from ..core.security import User, region_scope
from ..scoring.rules import get_settings_block
from ..sla import breach
from .notify import raise_alert

ACTIVE = ("NEW", "ACKNOWLEDGED")


def _auto_resolve(db, alert_type: str, keep: set[str], prefix: str) -> int:
    now = clock.now_iso()
    rows = db.all("SELECT id, dedupe_key FROM alerts WHERE alert_type = ? AND state IN ('NEW','ACKNOWLEDGED')", (alert_type,))
    n = 0
    for r in rows:
        if r["dedupe_key"].startswith(prefix) and r["dedupe_key"] not in keep:
            db.run("UPDATE alerts SET state = 'RESOLVED', acted_by = 'system', acted_at = ?, updated_at = ?, "
                   "action_remarks = 'Auto-resolved: condition no longer applies' WHERE id = ?", (now, now, r["id"]))
            n += 1
    return n


def sweep(db, today: date | None = None) -> dict[str, int]:
    """Idempotent: re-running creates nothing new for unchanged conditions."""
    today = today or clock.today()
    cfg = get_settings_block(db, "sla")
    warn_days = int(cfg["warning_days_before_due"])
    idle_days = int(cfg["pending_reminder_idle_days"])
    threshold = float(cfg["predicted_breach_threshold"])
    stats = {"overdue": 0, "due_soon": 0, "predicted": 0, "reminders": 0, "escalations": 0, "match_reviews": 0,
             "auto_resolved": 0, "audit_warning": 0}
    with db.tx():
        open_cases = db.all("SELECT c.*, i.name AS institution_name FROM complaints c LEFT JOIN institutions i "
                            "ON i.id = c.institution_id WHERE c.status != 'DISPOSED'")
        keep = {"SLA_OVERDUE": set(), "SLA_WARNING": set(), "PREDICTED_BREACH": set(), "PENDING_REMINDER": set()}
        model = None
        for c in open_cases:
            due = date.fromisoformat(c["expected_disposal_date"])
            remaining = (due - today).days
            who = c["institution_name"] or c["institution_name_raw"]
            if remaining < 0:
                key = f"SLA_OVERDUE:{c['id']}"
                keep["SLA_OVERDUE"].add(key)
                sev = "CRITICAL" if (c["priority_override_band"] or c["priority_band"]) in ("CRITICAL", "HIGH") else "WARNING"
                _, new = raise_alert(db, alert_type="SLA_OVERDUE", severity=sev, title=f"Overdue: {c['id']} ({-remaining} days)",
                                     message=f"{who}: due {due.isoformat()}, now {-remaining} day(s) beyond the "
                                             f"{c['sla_days']}-day timeline. Status {c['status']}.",
                                     dedupe_key=key, institution_id=c["institution_id"], case_id=c["id"],
                                     target_bureau=c["bureau_code"], target_region=c["region_code"])
                stats["overdue"] += int(new)
            else:
                if remaining <= warn_days:
                    key = f"SLA_WARNING:{c['id']}:{due.isoformat()}"
                    keep["SLA_WARNING"].add(key)
                    _, new = raise_alert(db, alert_type="SLA_WARNING", severity="WARNING",
                                         title=f"Due {'today' if remaining == 0 else f'in {remaining} day(s)'}: {c['id']}",
                                         message=f"{who}: disposal due {due.isoformat()}.", dedupe_key=key,
                                         institution_id=c["institution_id"], case_id=c["id"],
                                         target_bureau=c["bureau_code"], target_region=c["region_code"])
                    stats["due_soon"] += int(new)
                if model is None:
                    model = breach.get_model(db, today)
                pred = breach.predict(db, c, today, model)
                if pred.get("applicable") and pred["probability"] >= threshold:
                    key = f"PREDICTED_BREACH:{c['id']}"
                    keep["PREDICTED_BREACH"].add(key)
                    reasons = "; ".join(f["label"] for f in pred["factors"][:2] if f["direction"] == "+") or "historical pattern"
                    _, new = raise_alert(db, alert_type="PREDICTED_BREACH", severity="WARNING",
                                         title=f"Forecast: may breach SLA — {c['id']} ({round(pred['probability'] * 100)}%)",
                                         message=f"{who}: model-estimated breach probability {pred['probability']:.0%} with "
                                                 f"{remaining} day(s) left ({reasons}). Prediction, not a fact.",
                                         dedupe_key=key, institution_id=c["institution_id"], case_id=c["id"],
                                         target_bureau=c["bureau_code"], target_region=c["region_code"])
                    stats["predicted"] += int(new)
            last = c["last_action_at"] or c["created_at"]
            idle = (today - datetime.fromisoformat(last.replace("Z", "+00:00")).date()).days
            if c["status"] == "RECEIVED" and (today - date.fromisoformat(c["received_date"])).days > 3:
                key = f"PENDING_REMINDER:{c['id']}:unacknowledged"
                keep["PENDING_REMINDER"].add(key)
                _, new = raise_alert(db, alert_type="PENDING_REMINDER", severity="WARNING",
                                     title=f"Not yet acknowledged: {c['id']}",
                                     message=f"{who}: received {c['received_date']} and still not acknowledged/assigned.",
                                     dedupe_key=key, institution_id=c["institution_id"], case_id=c["id"],
                                     target_bureau=c["bureau_code"], target_region=c["region_code"])
                stats["reminders"] += int(new)
            elif idle >= idle_days:
                key = f"PENDING_REMINDER:{c['id']}:{last[:10]}"
                keep["PENDING_REMINDER"].add(key)
                _, new = raise_alert(db, alert_type="PENDING_REMINDER", severity="INFO",
                                     title=f"No action for {idle} days: {c['id']}",
                                     message=f"{who}: last action on {last[:10]} ({c['last_action_type']}). Next: "
                                             f"{c['next_action'] or 'not recorded'}.",
                                     dedupe_key=key, institution_id=c["institution_id"], case_id=c["id"],
                                     target_bureau=c["bureau_code"], target_region=c["region_code"])
                stats["reminders"] += int(new)
            if c["status"] == "ESCALATED":
                key = f"ESCALATION:{c['id']}:{c['escalation_level']}:None"
                _, new = raise_alert(db, alert_type="ESCALATION", severity="CRITICAL",
                                     title=f"Escalated case awaiting review: {c['id']}",
                                     message=f"{who}: escalation level {c['escalation_level']}; review by the Competent Authority.",
                                     dedupe_key=key, institution_id=c["institution_id"], case_id=c["id"],
                                     target_bureau=None, target_region=c["region_code"], refresh=False)
                stats["escalations"] += int(new)
        for t, k in keep.items():
            stats["auto_resolved"] += _auto_resolve(db, t, k, f"{t}:")
        for r in db.all("SELECT * FROM match_reviews WHERE status = 'PENDING'"):
            region = db.val("SELECT region_code FROM complaints WHERE id = ?", (r["source_ref"],)) if r["source_ref"] else None
            _, new = raise_alert(db, alert_type="MATCH_REVIEW", severity="INFO",
                                 title=f"Institution match needs review: '{r['raw_name'][:60]}'",
                                 message=f"Best candidate confidence {r['best_confidence'] or 0:.0%}; officer confirmation needed.",
                                 dedupe_key=f"MATCH_REVIEW:{r['id']}", case_id=r["source_ref"] if r["source_type"] != "IMPORT" else None,
                                 target_region=region, refresh=False)
            stats["match_reviews"] += int(new)
        result = chain.verify(db)
        if not result["ok"]:
            _, new = raise_alert(db, alert_type="AUDIT_WARNING", severity="CRITICAL",
                                 title="Audit hash chain verification FAILED",
                                 message=f"First broken event seq {result['first_bad_seq']}: {result['reason']}.",
                                 dedupe_key=f"AUDIT_WARNING:{result['first_bad_seq']}")
            stats["audit_warning"] += int(new)
    return stats


def visible_clause(user: User) -> tuple[str, list[Any]]:
    """Officers see their Bureau's alerts plus Bureau-less ones; Regional Offices their region."""
    if user.role in ("RB_OFFICER", "PGRC_OFFICER"):
        return "(a.target_bureau = ? OR a.target_bureau IS NULL)", [user.bureau_code]
    scope = region_scope(user)
    if scope:
        return "(a.target_region = ?)", [scope]
    return "1=1", []


def act(db, user: User, alert_id: str, action: str, remarks: str | None) -> dict[str, Any]:
    states = {"ACKNOWLEDGE": "ACKNOWLEDGED", "RESOLVE": "RESOLVED", "DISMISS": "DISMISSED", "REOPEN": "NEW"}
    if action not in states:
        raise unprocessable(f"action must be one of {sorted(states)}.")
    if action in ("RESOLVE", "DISMISS") and (not remarks or len(remarks.strip()) < 3):
        raise unprocessable("Remarks are mandatory to resolve or dismiss an alert.")
    with db.tx():
        alert = db.one("SELECT * FROM alerts a WHERE id = ?", (alert_id,))
        if alert is None:
            raise not_found("Alert", alert_id)
        clause, params = visible_clause(user)
        if db.one(f"SELECT 1 FROM alerts a WHERE a.id = ? AND {clause}", (alert_id, *params)) is None:
            raise forbidden("This alert is not addressed to your role/Bureau/region.")
        if alert["alert_type"] == "AUDIT_WARNING" and not user.is_authority:
            raise forbidden("Only the Competent Authority can act on audit-integrity alerts.")
        new_state = states[action]
        if alert["state"] == new_state:
            raise conflict(f"Alert already {new_state}.")
        now = clock.now_iso()
        db.update("alerts", "id", alert_id, {"state": new_state, "acted_by": user.id, "acted_role": user.role,
                                             "acted_at": now, "action_remarks": remarks, "updated_at": now})
        chain.record(db, user, f"ALERT_{new_state}", "alert", alert_id, before={"state": alert["state"]},
                     after={"state": new_state, "alert_type": alert["alert_type"], "case_id": alert["case_id"]}, remarks=remarks)
    return {"alert_id": alert_id, "state": new_state}

