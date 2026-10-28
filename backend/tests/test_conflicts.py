"""Phase 2: conflict tiers, live detection, lead-Bureau recommendation, link/merge/unmerge safety."""

from __future__ import annotations

from datetime import date

import pytest

from app.audit import chain
from app.complaints import service as complaints
from app.conflicts import lead as lead_mod
from app.conflicts import service as overlap
from app.conflicts.detector import evaluate_pairs
from app.core.constants import COORDINATION_HEADLINE
from app.core.errors import ApiError
from app.core.security import resolve_user
from app.core.util import loads
from app.scoring.rules import category_rules, get_settings_block
from app.workflow import service as wf

TODAY = date(2026, 10, 27)


def _alert_for(db, case_id, tier):
    return db.one("SELECT o.* FROM overlap_alerts o JOIN overlap_alert_cases c ON c.alert_id = o.id "
                  "WHERE c.case_id = ? AND o.tier = ?", (case_id, tier))


def test_institution_a_conflict_alert(ro_db):
    al = _alert_for(ro_db, "RB-2291", "CONFLICT")
    assert al is not None and al["headline"] == COORDINATION_HEADLINE == "Potential Overlapping Cases – Coordination Required"
    members = {r["case_id"] for r in ro_db.all("SELECT case_id FROM overlap_alert_cases WHERE alert_id = ?", (al["id"],))}
    assert {"RB-2291", "PGRC-5530", "PGRC-4127"} <= members
    rules = set(loads(al["rules_json"]))
    assert {"C1", "C2"} <= rules
    assert al["trigger_type"] == "ACTION_ADDED" and al["trigger_case_id"] == "RB-2291"
    assert al["recommended_lead"] == "PGRC" and al["cross_bureau"] == 1
    rec = loads(al["recommendation_json"])
    assert rec["advisory"] is True and any("workload" in r for r in rec["rationale"])
    sig = loads(al["signals_json"])
    pair = next(p for p in sig["pairs"] if p["b"] == "PGRC-5530")
    assert pair["favourable_action"]["action_type"] == "RENEWAL_INITIATED"
    assert ro_db.one("SELECT 1 FROM alerts WHERE overlap_alert_id = ? AND severity = 'CRITICAL'", (al["id"],))


def test_live_trigger_on_regulatory_action(db):
    assert _alert_for(db, "RB-2310", "CONFLICT") is None
    rb = resolve_user(db, "rb.officer")
    out = wf.add_action(db, rb, "RB-2310", "INTAKE_INCREASE_APPROVED", remarks="Committee recommends approval")
    assert out["overlap_alerts"] and out["overlap_alerts"][0]["tier"] == "CONFLICT"
    al = _alert_for(db, "RB-2310", "CONFLICT")
    assert "PGRC-5544" in {r["case_id"] for r in db.all("SELECT case_id FROM overlap_alert_cases WHERE alert_id=?", (al["id"],))}
    assert al["trigger_type"] == "ACTION_ADDED" and al["headline"] == COORDINATION_HEADLINE
    assert db.one("SELECT 1 FROM audit_events WHERE action='OVERLAP_DETECTED' AND entity_id=?", (al["id"],))
    # PGRC officer cannot add regulatory actions; RO cannot change status
    pgrc = resolve_user(db, "pgrc.officer")
    with pytest.raises(ApiError) as e:
        wf.add_action(db, pgrc, "PGRC-5544", "RENEWAL_INITIATED", remarks="x")
    assert e.value.status == 403


def test_same_institution_alone_is_not_an_overlap(ro_db):
    trigger = ro_db.one("SELECT * FROM complaints WHERE id = 'PGRC-3402'")  # 2021 general enquiry, disposed
    other = ro_db.one("SELECT * FROM complaints WHERE id = 'SDC-7790'")     # 2022 scholarship, disposed
    assert evaluate_pairs(ro_db, trigger, [other], TODAY) == []
    # favourable action vs a case in the SAME bureau is not a cross-bureau conflict
    rb_file = ro_db.one("SELECT * FROM complaints WHERE id = 'RB-2291'")
    same_bureau = ro_db.one("SELECT * FROM complaints WHERE id = 'RB-2260'")
    assert all(p["tier"] != "CONFLICT" for p in evaluate_pairs(ro_db, rb_file, [same_bureau], TODAY))


def test_tiers_are_distinct(ro_db):
    tiers = {r["tier"] for r in ro_db.all("SELECT DISTINCT tier FROM overlap_alerts")}
    assert tiers == {"DUPLICATE", "RELATED", "CONFLICT"}
    for al in ro_db.all("SELECT * FROM overlap_alerts"):
        codes = set(loads(al["rules_json"]))
        prefix = {"DUPLICATE": "D", "RELATED": "R", "CONFLICT": "C"}[al["tier"]]
        assert codes and all(c.startswith(prefix) for c in codes), (al["id"], codes)


def _payload(**kw):
    p = {"institution_name": "Sankalp Institute of Engineering & Technology, Bhopal", "category_code": "FEE_FRAUD",
         "subject": "Excess fee collected without receipts; caution deposit not refunded",
         "description": "Students of B.Tech (CSE) and B.Tech (Mechanical) report that the institute collected Rs 65,000 "
                        "each over and above the approved fee as a development charge without issuing receipts.",
         "received_date": date(2026, 10, 25), "bureau_code": "PGRC", "complainant_count": 3, "evidence_count": 1,
         "reference_flag": "NONE", "match_decision": "CONFIRM", "institution_id": "INS-0001"}
    p.update(kw)
    return p


def test_intake_duplicate_guard_and_detection(db):
    pgrc = resolve_user(db, "pgrc.officer")
    prev = complaints.preview(db, pgrc, _payload())
    assert prev["selected_institution"]["id"] == "INS-0001" and prev["duplicate_warning"] is True
    assert prev["priority"]["chips"]
    with pytest.raises(ApiError) as e:
        complaints.create(db, pgrc, _payload())
    assert e.value.status == 409 and e.value.details["duplicates"]
    out = complaints.create(db, pgrc, _payload(acknowledge_duplicates=True))
    assert out["case_id"].startswith("PGRC-") and any(o["tier"] == "DUPLICATE" for o in out["overlap_alerts"])
    created = db.one("SELECT * FROM complaints WHERE id = ?", (out["case_id"],))
    assert created["is_synthetic"] == 0 and created["created_by"] == "pgrc.officer"
    assert db.one("SELECT 1 FROM audit_events WHERE action='CASE_CREATED' AND entity_id=?", (out["case_id"],))
    # RB officer cannot register a PGRC case
    with pytest.raises(ApiError) as e2:
        complaints.create(db, resolve_user(db, "rb.officer"), _payload(acknowledge_duplicates=True))
    assert e2.value.status == 403


def test_lead_recommendation_responds_to_workload(db):
    al = _alert_for(db, "RB-2291", "CONFLICT")
    members = db.all("SELECT c.* FROM overlap_alert_cases oc JOIN complaints c ON c.id = oc.case_id WHERE oc.alert_id=?", (al["id"],))
    rules = category_rules(db)
    cfg = get_settings_block(db, "lead")
    reg = {"RB-2291": [{"action_type": "RENEWAL_INITIATED", "bureau_code": "RB"}]}
    base = lead_mod.recommend(db, members, rules, cfg, reg)
    assert base["recommended"] == "PGRC"  # justified by subject matter (fee fraud, ragging) - see rationale
    assert "subject-matter" in base["rationale"][0] and "workload factor" in base["rationale"][0]
    # A closer call: an RB regulatory complaint and a PGRC fee complaint at the same institution.
    pair = [
        {"id": "X-1", "category_code": "REGULATORY_NONCOMPLIANCE", "status": "UNDER_PROCESS", "bureau_code": "RB"},
        {"id": "X-2", "category_code": "FEE_FRAUD", "status": "UNDER_PROCESS", "bureau_code": "PGRC"},
    ]
    load = lead_mod.workload(db)
    load["RB"]["load_ratio"], load["PGRC"]["load_ratio"] = 1.0, 1.0
    assert lead_mod.recommend(db, pair, rules, cfg, {}, load=load)["recommended"] == "RB"
    load["RB"]["load_ratio"], load["PGRC"]["load_ratio"] = 2.0, 0.6  # RB overloaded, PGRC has capacity
    shifted = lead_mod.recommend(db, pair, rules, cfg, {}, load=load)
    assert shifted["recommended"] == "PGRC"
    rb_row = next(r for r in shifted["scores"] if r["bureau"] == "RB")
    assert rb_row["workload_factor"] < 1.0


def test_merge_preserves_originals_and_unmerge(db):
    dup = db.one("SELECT * FROM overlap_alerts WHERE tier = 'DUPLICATE' AND cross_bureau = 0 ORDER BY score DESC LIMIT 1")
    ids = [r["case_id"] for r in db.all("SELECT case_id FROM overlap_alert_cases WHERE alert_id = ?", (dup["id"],))]
    hist_before = {i: db.val("SELECT COUNT(*) FROM case_actions WHERE case_id = ?", (i,)) for i in ids}
    ca = resolve_user(db, "competent.authority")
    out = overlap.merge(db, ca, ids, kind="DUPLICATE_MERGE", remarks="Same grievance filed twice", alert_id=dup["id"])
    mc = out["master_case_id"]
    for i in ids:
        row = db.one("SELECT * FROM complaints WHERE id = ?", (i,))
        assert row is not None and row["master_case_id"] == mc
        assert db.val("SELECT COUNT(*) FROM case_actions WHERE case_id = ?", (i,)) == hist_before[i] + 1
    assert db.one("SELECT 1 FROM audit_events WHERE action = 'MASTER_CASE_CREATED' AND entity_id = ?", (mc,))
    res = overlap.unmerge(db, ca, mc, None, "Separate grievances after verification")
    assert res["dissolved"] is True
    assert db.one("SELECT status FROM master_cases WHERE id = ?", (mc,))["status"] == "DISSOLVED"
    assert db.val("SELECT COUNT(*) FROM master_case_members WHERE master_case_id = ? AND removed_at IS NOT NULL", (mc,)) == len(ids)
    for i in ids:
        assert db.one("SELECT master_case_id FROM complaints WHERE id = ?", (i,))["master_case_id"] is None
    assert chain.verify(db)["ok"]


def test_merge_permissions_and_eligibility(db):
    pgrc = resolve_user(db, "pgrc.officer")
    with pytest.raises(ApiError) as e:  # not duplicates of each other
        overlap.merge(db, pgrc, ["PGRC-5530", "PGRC-4466"], remarks="trying to merge unrelated cases")
    assert e.value.status == 409
    with pytest.raises(ApiError) as e2:  # cross-bureau needs the Competent Authority
        overlap.merge(db, pgrc, ["PGRC-5530", "RB-2291"], kind="COORDINATION", remarks="coordination master case")
    assert e2.value.status == 403
    ca = resolve_user(db, "competent.authority")
    al = _alert_for(db, "RB-2291", "CONFLICT")
    out = overlap.merge(db, ca, ["PGRC-5530", "RB-2291", "PGRC-4127"], kind="COORDINATION", lead_bureau="PGRC",
                        remarks="One coordinated record; PGRC leads, RB holds renewal", alert_id=al["id"])
    assert out["created"] and db.one("SELECT kind FROM master_cases WHERE id=?", (out["master_case_id"],))["kind"] == "COORDINATION"


def test_conflict_decisions_reserved_for_authority(db):
    al = _alert_for(db, "RB-2291", "CONFLICT")
    rb = resolve_user(db, "rb.officer")
    with pytest.raises(ApiError) as e:
        overlap.set_status(db, rb, al["id"], "RESOLVED", "RB thinks it is fine")
    assert e.value.status == 403
    overlap.set_status(db, rb, al["id"], "UNDER_REVIEW", "RB placing renewal on hold for review")
    ca = resolve_user(db, "competent.authority")
    dec = overlap.decide_lead(db, ca, al["id"], "ACCEPT", None, "PGRC to complete fee-fraud inquiry first")
    assert dec["decided_lead"] == "PGRC"
    notes = db.val("SELECT COUNT(*) FROM case_actions WHERE case_id='PGRC-5530' AND action_type='COORDINATION_NOTE'")
    assert notes >= 1
    with pytest.raises(ApiError):
        overlap.decide_lead(db, ca, al["id"], "OVERRIDE", "RB", "")  # override needs remarks
    overlap.set_status(db, ca, al["id"], "RESOLVED", "Joint decision recorded; renewal held pending PGRC report")
    assert db.one("SELECT status FROM overlap_alerts WHERE id=?", (al["id"],))["status"] == "RESOLVED"
    assert db.val("SELECT COUNT(*) FROM alerts WHERE overlap_alert_id=? AND state IN ('NEW','ACKNOWLEDGED')", (al["id"],)) == 0
