"""Seed post-processing: run the real engines over the generated data.

Order: train local models -> institution matching for seeded raw names (match reviews,
confidences) -> local category suggestions -> priority scores -> conflict detection
(the Institution A renewal action first, then a full scan) -> alert sweep.
Nothing here is hard-coded: alerts and scores are produced by the same code paths the API uses.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..alerts.service import sweep
from ..conflicts import detector
from ..core.security import SYSTEM_USER
from ..institutions import matcher
from ..institutions.service import record_review
from ..scoring import classifier, priority
from ..scoring.rules import get_settings_block


def post_process(db, anchor: date) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    stats["matcher_model"] = matcher.train_model(db)["metrics"]
    stats["classifier"] = {k: v for k, v in classifier.train().items() if k in ("macro_f1", "accuracy", "n_examples")}
    auto_t = float(get_settings_block(db, "matching")["auto_link_threshold"])
    with db.tx():
        pending = db.all("SELECT * FROM complaints WHERE match_status = 'PENDING_REVIEW' ORDER BY id")
        for c in pending:
            q = matcher.Query(c["institution_name_raw"], raw_address=c["institution_address_raw"],
                              raw_pincode=c["institution_pincode_raw"], raw_permanent_id=c["permanent_id_raw"])
            res = matcher.match(db, q)
            record_review(db, q, res, "SEED", c["id"], status="PENDING")
            best = res["candidates"][0]["confidence"] if res["candidates"] else None
            db.run("UPDATE complaints SET match_confidence = ? WHERE id = ?", (best, c["id"]))
        names = {r["id"]: r["name"] for r in db.all("SELECT id, name FROM institutions")}
        updates = []
        for c in db.all("SELECT id, institution_id, institution_name_raw, institution_address_raw, institution_pincode_raw, "
                        "permanent_id_raw, match_status FROM complaints WHERE institution_id IS NOT NULL"):
            if c["institution_name_raw"] == names[c["institution_id"]] and not c["permanent_id_raw"]:
                updates.append(("CONFIRMED", 1.0, c["id"]))
                continue
            res = matcher.match(db, matcher.Query(c["institution_name_raw"], raw_address=c["institution_address_raw"],
                                                  raw_pincode=c["institution_pincode_raw"], raw_permanent_id=c["permanent_id_raw"]))
            conf = next((x["confidence"] for x in res["candidates"] if x["institution_id"] == c["institution_id"]), None)
            top_is_true = bool(res["candidates"]) and res["candidates"][0]["institution_id"] == c["institution_id"]
            status = "AUTO_LINKED" if (res["decision"] == "AUTO_LINK" and top_is_true and (conf or 0) >= auto_t) else "CONFIRMED"
            updates.append((status, conf, c["id"]))
        db.many("UPDATE complaints SET match_status = ?, match_confidence = ? WHERE id = ?", updates)
        rows = db.all("SELECT id, subject, description FROM complaints ORDER BY id")
        preds = classifier.predict_many([f"{r['subject']}. {r['description']}" for r in rows])
        db.many("UPDATE complaints SET ml_category = ?, ml_confidence = ? WHERE id = ?",
                [(cat, p, r["id"]) for r, (cat, p) in zip(rows, preds, strict=True)])
        stats["priorities"] = priority.recompute_all(db, anchor)
        act = db.one("SELECT * FROM case_actions WHERE case_id = 'RB-2291' AND action_type = 'RENEWAL_INITIATED'")
        if act:
            detector.detect_for_case(db, "RB-2291", trigger_type="ACTION_ADDED", actor=SYSTEM_USER, today=anchor,
                                     trigger_action={"id": act["id"], "action_type": act["action_type"],
                                                     "action_at": act["action_at"], "bureau_code": act["bureau_code"]})
        stats["scan"] = detector.scan_all(db, actor=SYSTEM_USER, today=anchor)
    stats["alerts"] = sweep(db, anchor)
    stats["match_reviews"] = len(pending)
    return stats
