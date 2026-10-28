"""Phase 2: priority formula + chips, rules, overrides, classifier, SLA facts and breach model."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.errors import ApiError
from app.core.security import resolve_user
from app.scoring import classifier, priority
from app.scoring.rules import DEFAULT_SETTINGS, category_rules, get_settings_block, save_settings_block
from app.sla import breach
from app.sla.engine import sla_state
from app.workflow import service as wf

TODAY = date(2026, 10, 27)


def test_priority_formula_and_chips(ro_db):
    case = ro_db.one("SELECT * FROM complaints WHERE id = 'PGRC-5530'")
    res = priority.compute(case, category_rules(ro_db), get_settings_block(ro_db, "priority"), TODAY)
    assert res["band"] == "HIGH" and res["score"] == pytest.approx(45.6, abs=0.1)
    pts = sum(c["points"] for c in res["chips"] if c["kind"] in ("severity", "modifier"))
    assert pts == pytest.approx(res["score"], abs=0.3)
    keys = {c["key"] for c in res["chips"]}
    assert {"severity", "complainants", "evidence", "reference", "age"} <= keys


def test_keyword_escalation_cap_and_ml_chip(ro_db):
    rules = category_rules(ro_db)
    cfg = get_settings_block(ro_db, "priority")
    case = {"category_code": "GENERAL_ENQUIRY", "subject": "Query", "description": "Seniors were ragging juniors in the hostel",
            "received_date": "2026-10-20", "complainant_count": 1, "evidence_count": 0, "reference_flag": "NONE",
            "sla_days": 30, "disposed_date": None}
    res = priority.compute(case, rules, cfg, TODAY, {"category": "RAGGING", "probability": 0.81})
    assert res["inputs"]["severity_level"] == 5 and res["band"] == "CRITICAL"
    assert any(c["kind"] == "keyword" for c in res["chips"])
    ml = next(c for c in res["chips"] if c["kind"] == "ml")
    assert ml["points"] == 0 and "Recommendation only" in ml["detail"]
    heavy = dict(case, category_code="CAMPUS_CRIME", complainant_count=150, evidence_count=3, reference_flag="COURT",
                 received_date="2026-01-01")
    res2 = priority.compute(heavy, rules, cfg, TODAY)
    assert any(c["kind"] == "cap" for c in res2["chips"]) and res2["score"] <= 100


def test_rule_change_changes_score_and_validation(db):
    case = db.one("SELECT * FROM complaints WHERE id = 'PGRC-5530'")
    before = priority.compute_for_case(db, case, TODAY)["score"]
    with db.tx():
        db.run("UPDATE category_rules SET severity_weight = 4.0, severity_level = 4, updated_at = '2099-01-01' WHERE code = 'FEE_FRAUD'")
    after = priority.compute_for_case(db, case, TODAY)["score"]
    assert after > before
    bad = dict(DEFAULT_SETTINGS["priority"], bands={"CRITICAL": 20, "HIGH": 35, "MEDIUM": 10})
    with pytest.raises(ApiError), db.tx():
        save_settings_block(db, "priority", bad, "test")


def test_rule_cache_sees_edits_whatever_their_timestamp(db):
    """Regression: with a frozen date, an edit made early in the (real) day carries an *older* timestamp
    than the seeded rules; the rule cache must still pick it up."""
    assert category_rules(db)["FEE_FRAUD"]["severity_level"] == 3
    with db.tx():
        db.run("UPDATE category_rules SET severity_level = 4, updated_at = '2000-01-01T00:00:00Z' WHERE code = 'FEE_FRAUD'")
    assert category_rules(db)["FEE_FRAUD"]["severity_level"] == 4


def test_frozen_clock_never_goes_backwards(ro_db):  # the fixture freezes the date at 2026-10-27
    from app.core import clock

    saved = dict(clock._floor)
    try:
        later = "2026-10-27T17:00:00Z"  # 22:30 IST on the frozen date, later than most real times of day
        clock.observe(later)
        a, b = clock.now_iso(), clock.now_iso()  # second precision, as most stored timestamps
        assert later < a < b and a.startswith("2026-10-27")  # stays on the frozen date, after the stored event
        assert clock.today() == TODAY
    finally:
        clock._floor.clear()
        clock._floor.update(saved)


def test_priority_override_is_logged(db):
    pgrc = resolve_user(db, "pgrc.officer")
    out = wf.override_priority(db, pgrc, "PGRC-5530", "CRITICAL", "Mass complaint with media attention")
    assert out["new_band"] == "CRITICAL"
    row = db.one("SELECT * FROM priority_overrides WHERE case_id = 'PGRC-5530'")
    assert row["previous_band"] == "HIGH" and row["reason"] and row["actor_role"] == "PGRC_OFFICER" and row["bureau_code"] == "PGRC"
    assert db.one("SELECT 1 FROM audit_events WHERE action = 'PRIORITY_OVERRIDE' AND entity_id = 'PGRC-5530'")
    case = db.one("SELECT * FROM complaints WHERE id = 'PGRC-5530'")
    assert priority.compute_for_case(db, case, TODAY)["effective_band"] == "CRITICAL"
    rb = resolve_user(db, "rb.officer")
    with pytest.raises(ApiError) as e:
        wf.override_priority(db, rb, "PGRC-5530", "LOW", "Not my bureau but trying anyway")
    assert e.value.status == 403


def test_classifier_recommendation(ro_db):
    top = classifier.predict("Senior students forced first years to do humiliating acts in the hostel at night")
    assert top[0]["category"] == "RAGGING"
    st = classifier.status()
    assert st["available"] and "synthetic" in st["caveat"]


def test_sla_state_facts():
    base = {"received_date": "2026-10-01", "expected_disposal_date": "2026-10-16", "sla_days": 15}
    assert sla_state({**base, "status": "UNDER_PROCESS"}, TODAY)["state"] == "OVERDUE"
    assert sla_state({**base, "status": "UNDER_PROCESS"}, date(2026, 10, 14))["state"] == "DUE_SOON"
    assert sla_state({**base, "status": "UNDER_PROCESS"}, date(2026, 10, 5))["state"] == "ON_TRACK"
    late = sla_state({**base, "status": "DISPOSED", "disposed_date": "2026-10-20"}, TODAY)
    assert late["state"] == "DISPOSED_LATE" and late["overdue_by_days"] == 4


def test_breach_prediction_is_explained_and_distinguished_from_facts(ro_db):
    model = breach.get_model(ro_db, TODAY)
    assert model["status"] == "FITTED" and model["c_index"] > 0.6
    fee = breach.predict(ro_db, ro_db.one("SELECT * FROM complaints WHERE id='PGRC-5530'"), TODAY, model)
    assert fee["applicable"] and 0 < fee["probability"] < 1 and fee["band"] == "HIGH" and fee["factors"]
    assert fee["historical_reference"]["comparable_cases"] >= 8
    overdue = ro_db.one("SELECT * FROM complaints WHERE status != 'DISPOSED' AND expected_disposal_date < '2026-10-20' LIMIT 1")
    res = breach.predict(ro_db, overdue, TODAY, model)
    assert res["applicable"] is False and res["is_fact"] is True
