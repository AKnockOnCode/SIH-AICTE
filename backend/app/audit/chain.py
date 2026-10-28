"""Tamper-evident, hash-chained audit log.

Each event stores `payload_hash = sha256(canonical(before, after, remarks))` and
`hash = sha256(canonical(event fields + payload_hash + prev_hash))`, where `prev_hash`
is the previous event's hash (genesis = 64 zeros). Verification recomputes every link in
`seq` order. Any edit, deletion or re-ordering of a stored row breaks the chain from that
point. Limitation: whoever controls the database file can rewrite the *whole* chain;
production use needs an external anchor (e.g. periodic head-hash publication or WORM
storage). The chain is extended inside the caller's write transaction (SQLite
`BEGIN IMMEDIATE` serialises writers), so two requests cannot fork it.
"""

from __future__ import annotations

import uuid
from typing import Any

from ..core.clock import now_iso
from ..core.security import SYSTEM_USER, User
from ..core.util import canonical_json, sha256_hex

GENESIS_HASH = "0" * 64


def _payload_hash(before_json: str | None, after_json: str | None, remarks: str | None) -> str:
    return sha256_hex(canonical_json({"before": before_json, "after": after_json, "remarks": remarks}))


def _event_hash(fields: dict[str, Any]) -> str:
    keys = (
        "event_id", "ts", "actor_id", "actor_label", "actor_role", "actor_bureau",
        "action", "entity_type", "entity_id", "payload_hash", "prev_hash",
    )
    return sha256_hex(canonical_json({k: fields.get(k) for k in keys}))


def record(
    db,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    before: Any = None,
    after: Any = None,
    remarks: str | None = None,
) -> dict[str, Any]:
    """Append one audit event. Must run inside the caller's transaction."""
    if not db.in_tx:
        with db.tx():
            return record(db, actor, action, entity_type, entity_id, before, after, remarks)
    actor = actor or SYSTEM_USER
    prev = db.val("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1", default=GENESIS_HASH)
    before_json = canonical_json(before) if before is not None else None
    after_json = canonical_json(after) if after is not None else None
    fields: dict[str, Any] = {
        "event_id": uuid.uuid4().hex,
        "ts": now_iso(micro=True),
        "actor_id": actor.id,
        "actor_label": actor.display_name,
        "actor_role": actor.role,
        "actor_bureau": actor.bureau_code,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before_json": before_json,
        "after_json": after_json,
        "remarks": remarks,
        "payload_hash": _payload_hash(before_json, after_json, remarks),
        "prev_hash": prev,
    }
    fields["hash"] = _event_hash(fields)
    seq = db.insert("audit_events", fields)
    fields["seq"] = seq
    return fields


def verify(db) -> dict[str, Any]:
    """Recompute the whole chain. Returns ok flag, count and the first broken link (if any)."""
    prev = GENESIS_HASH
    checked = 0
    last_seq = 0
    for row in db.raw.execute("SELECT * FROM audit_events ORDER BY seq"):
        row = dict(row)
        checked += 1
        expected_payload = _payload_hash(row["before_json"], row["after_json"], row["remarks"])
        problem = None
        if row["prev_hash"] != prev:
            problem = "prev_hash does not match the previous event's hash (row deleted, inserted or re-ordered)"
        elif row["payload_hash"] != expected_payload:
            problem = "payload_hash mismatch (before/after/remarks were modified)"
        elif row["hash"] != _event_hash(row):
            problem = "event hash mismatch (event metadata was modified)"
        if problem:
            return {
                "ok": False, "checked": checked, "first_bad_seq": row["seq"],
                "reason": problem, "head_hash": None, "last_good_seq": last_seq,
            }
        prev = row["hash"]
        last_seq = row["seq"]
    return {"ok": True, "checked": checked, "first_bad_seq": None, "reason": None,
            "head_hash": prev if checked else GENESIS_HASH, "last_good_seq": last_seq}
