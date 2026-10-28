"""SLA facts: due date, age, time remaining and overdue state (deterministic).

The due date (expected disposal date) is fixed when a case is registered as
received_date + SLA days of its category (an editable rule). No pauses or exemptions are
modelled; if AICTE policy needs them they must be added explicitly. These are *facts*;
breach *predictions* live in `sla.breach` and are labelled as probabilistic.
"""

from __future__ import annotations

from datetime import date
from typing import Any

OVERDUE_SQL = "(c.status != 'DISPOSED' AND c.expected_disposal_date < ?)"


def sla_state(case: dict[str, Any], today: date, warn_days: int = 3) -> dict[str, Any]:
    received = date.fromisoformat(case["received_date"])
    due = date.fromisoformat(case["expected_disposal_date"])
    sla = max(1, int(case["sla_days"]))
    if case.get("status") == "DISPOSED" and case.get("disposed_date"):
        end = date.fromisoformat(case["disposed_date"])
        age = (end - received).days
        late_by = (end - due).days
        state = "DISPOSED_LATE" if late_by > 0 else "DISPOSED_IN_TIME"
        label = f"Disposed {late_by} day(s) after due date" if late_by > 0 else "Disposed within SLA"
        return {"due_date": due.isoformat(), "sla_days": sla, "age_days": age, "days_remaining": None,
                "overdue": False, "overdue_by_days": max(0, late_by), "pct_used": round(100 * age / sla),
                "state": state, "is_open": False, "label": label}
    age = max(0, (today - received).days)
    remaining = (due - today).days
    if remaining < 0:
        state, label = "OVERDUE", f"Overdue by {-remaining} day(s)"
    elif remaining <= warn_days:
        state, label = "DUE_SOON", f"Due in {remaining} day(s)" if remaining else "Due today"
    else:
        state, label = "ON_TRACK", f"{remaining} day(s) remaining"
    return {"due_date": due.isoformat(), "sla_days": sla, "age_days": age, "days_remaining": remaining,
            "overdue": remaining < 0, "overdue_by_days": max(0, -remaining), "pct_used": round(100 * age / sla),
            "state": state, "is_open": True, "label": label}


AGEING_BUCKETS = [(0, 15, "0–15 days"), (16, 30, "16–30 days"), (31, 60, "31–60 days"), (61, 90, "61–90 days"),
                  (91, 180, "91–180 days"), (181, 100000, "Over 180 days")]


def ageing_bucket(age_days: int) -> str:
    for lo, hi, label in AGEING_BUCKETS:
        if lo <= age_days <= hi:
            return label
    return AGEING_BUCKETS[-1][2]
