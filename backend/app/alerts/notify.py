"""In-app notifications (the Alerts Centre). Delivery is IN_APP only: no email/SMS is sent."""

from __future__ import annotations

from typing import Any

from ..core.clock import now_iso
from ..core.util import next_id


def raise_alert(db, *, alert_type: str, severity: str, title: str, message: str, dedupe_key: str,
                institution_id: str | None = None, case_id: str | None = None, overlap_alert_id: str | None = None,
                target_bureau: str | None = None, target_region: str | None = None, refresh: bool = True) -> tuple[str, bool]:
    """Create an alert once per dedupe key. Returns (alert_id, created).

    If the alert already exists and is still NEW/ACKNOWLEDGED its text is refreshed; resolved
    or dismissed alerts are left alone (they are not re-raised for the same key).
    """
    now = now_iso()
    existing = db.one("SELECT id, state FROM alerts WHERE dedupe_key = ?", (dedupe_key,))
    if existing:
        if refresh and existing["state"] in ("NEW", "ACKNOWLEDGED"):
            db.run("UPDATE alerts SET title = ?, message = ?, severity = ?, updated_at = ? WHERE id = ?",
                   (title, message, severity, now, existing["id"]))
        return existing["id"], False
    alert_id = next_id(db, "alert", "ALR-", 6)
    db.insert("alerts", {
        "id": alert_id, "alert_type": alert_type, "severity": severity, "title": title, "message": message,
        "institution_id": institution_id, "case_id": case_id, "overlap_alert_id": overlap_alert_id,
        "target_bureau": target_bureau, "target_region": target_region, "state": "NEW", "dedupe_key": dedupe_key,
        "channel": "IN_APP", "created_at": now, "updated_at": now, "acted_by": None, "acted_role": None,
        "acted_at": None, "action_remarks": None,
    })
    return alert_id, True


def close_alerts(db, *, where: str, params: tuple[Any, ...], state: str, actor_id: str, remarks: str) -> int:
    now = now_iso()
    cur = db.run(f"UPDATE alerts SET state = ?, acted_by = ?, acted_at = ?, action_remarks = ?, updated_at = ? "
                 f"WHERE state IN ('NEW','ACKNOWLEDGED') AND {where}", (state, actor_id, now, remarks, now, *params))
    return cur.rowcount
