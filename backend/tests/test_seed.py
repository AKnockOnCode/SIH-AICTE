"""Phase 1: seed reproducibility, relationships and the hand-seeded demo story."""

from __future__ import annotations

from datetime import date, timedelta

from app.audit import chain
from app.db.database import connect
from app.seed.demo_story import PENDING_REVIEW_TRUTH
from app.seed.generator import fingerprint, generate

ANCHOR = date(2026, 10, 27)


def test_counts_and_synthetic_labels(ro_db):
    assert ro_db.val("SELECT COUNT(*) FROM institutions") == 60
    assert ro_db.val("SELECT COUNT(*) FROM complaints") == 1200
    assert ro_db.val("SELECT COUNT(*) FROM trusts") >= 6
    assert ro_db.val("SELECT COUNT(*) FROM complaints WHERE is_synthetic = 0") == 0
    assert ro_db.val("SELECT COUNT(*) FROM institutions WHERE permanent_id NOT LIKE 'SYN-%'") == 0
    assert ro_db.val("SELECT COUNT(*) FROM trusts WHERE provenance NOT LIKE 'SYNTHETIC%'") == 0
    # several trusts operate multiple institutions
    multi = ro_db.val("SELECT COUNT(*) FROM (SELECT trust_id FROM institutions WHERE trust_id IS NOT NULL "
                      "GROUP BY trust_id HAVING COUNT(*) >= 2)")
    assert multi >= 6
    years = {r["y"] for r in ro_db.all("SELECT DISTINCT substr(received_date,1,4) AS y FROM complaints")}
    assert {"2019", "2026"} <= years
    statuses = {r["status"] for r in ro_db.all("SELECT DISTINCT status FROM complaints")}
    assert statuses == {"RECEIVED", "PENDING", "UNDER_PROCESS", "TRANSFERRED", "ESCALATED", "DISPOSED"}
    overdue = ro_db.val("SELECT COUNT(*) FROM complaints WHERE status != 'DISPOSED' AND expected_disposal_date < ?",
                        (ANCHOR.isoformat(),))
    assert overdue > 50


def test_reproducible_and_idempotent(tmp_path, session_dirs):
    fps = []
    for name in ("a.db", "b.db"):
        with connect(tmp_path / name) as db:
            summary = generate(db, seed=26264, anchor=ANCHOR)
            assert summary["counts"]["complaints"] == 1200
            fps.append(fingerprint(db))
    assert fps[0] == fps[1]
    with connect(tmp_path / "a.db") as db:
        again = generate(db, seed=26264, anchor=ANCHOR)
        assert again["skipped"] is True
        assert db.val("SELECT COUNT(*) FROM complaints") == 1200
    with connect(tmp_path / "c.db") as db:
        generate(db, seed=1, anchor=ANCHOR)
        assert fingerprint(db) != fps[0]
        # demo IDs are stable regardless of the random seed
        assert db.one("SELECT id FROM complaints WHERE id = 'PGRC-5530'") is not None


def test_referential_integrity_and_histories(ro_db):
    assert ro_db.all("PRAGMA foreign_key_check") == []
    bad_officer = ro_db.val(
        "SELECT COUNT(*) FROM complaints c JOIN officers o ON o.id = c.assigned_officer_id "
        "WHERE o.bureau_code != c.bureau_code")
    assert bad_officer == 0
    assert ro_db.val("SELECT COUNT(*) FROM complaints WHERE status = 'DISPOSED' AND "
                     "(outcome IS NULL OR disposed_date IS NULL OR disposed_date < received_date)") == 0
    assert ro_db.val("SELECT COUNT(*) FROM complaints WHERE status != 'DISPOSED' AND outcome IS NOT NULL") == 0
    # due date = receipt + SLA days
    for r in ro_db.all("SELECT received_date, sla_days, expected_disposal_date FROM complaints LIMIT 200"):
        assert date.fromisoformat(r["expected_disposal_date"]) == date.fromisoformat(r["received_date"]) + timedelta(days=r["sla_days"])
    # every case starts with CREATED and its actions are chronological
    rows = ro_db.all("SELECT case_id, action_type, action_at FROM case_actions ORDER BY case_id, action_at, id")
    first: dict[str, str] = {}
    for r in rows:
        first.setdefault(r["case_id"], r["action_type"])
    assert set(first.values()) == {"CREATED"}
    assert len(first) == 1200


def test_demo_story_institution_a(ro_db):
    a = ro_db.one("SELECT * FROM institutions WHERE id = 'INS-0001'")
    assert a["demo_tag"] == "INSTITUTION_A" and a["region_code"] == "CENTRAL"
    rag = ro_db.one("SELECT * FROM complaints WHERE id = 'PGRC-4127'")
    fee = ro_db.one("SELECT * FROM complaints WHERE id = 'PGRC-5530'")
    rb = ro_db.one("SELECT * FROM complaints WHERE id = 'RB-2291'")
    assert rag["category_code"] == "RAGGING" and rag["institution_id"] == "INS-0001"
    assert rag["received_date"] < fee["received_date"]  # older ragging case
    assert fee["category_code"] == "FEE_FRAUD" and fee["status"] == "UNDER_PROCESS" and fee["bureau_code"] == "PGRC"
    assert rb["bureau_code"] == "RB" and rb["status"] != "DISPOSED" and rb["institution_id"] == "INS-0001"
    kinds = [r["action_type"] for r in ro_db.all("SELECT action_type FROM case_actions WHERE case_id = 'RB-2291' ORDER BY action_at")]
    assert kinds[-1] == "RENEWAL_INITIATED"
    open_cases = ro_db.val("SELECT COUNT(*) FROM complaints WHERE institution_id = 'INS-0001' AND status != 'DISPOSED'")
    assert open_cases == 4
    # alias "Institution A" makes the scenario searchable
    assert ro_db.one("SELECT 1 FROM institution_aliases WHERE institution_id='INS-0001' AND alias='Institution A'")


def test_demo_story_live_trigger_and_pending_reviews(ro_db):
    kinds = {r["action_type"] for r in ro_db.all("SELECT action_type FROM case_actions WHERE case_id = 'RB-2310'")}
    assert "RENEWAL_INITIATED" not in kinds and "INTAKE_INCREASE_APPROVED" not in kinds
    sh = ro_db.one("SELECT * FROM complaints WHERE id = 'PGRC-5544'")
    assert sh["status"] == "UNDER_PROCESS" and sh["category_code"] == "SEXUAL_HARASSMENT"
    for case_id in PENDING_REVIEW_TRUTH:
        row = ro_db.one("SELECT * FROM complaints WHERE id = ?", (case_id,))
        assert row["institution_id"] is None and row["match_status"] == "PENDING_REVIEW"
        assert row["institution_name_raw"]


def test_public_signals_provenance(ro_db):
    real = ro_db.all("SELECT * FROM public_signals WHERE verification = 'VERIFIED_SOURCE'")
    synth = ro_db.all("SELECT * FROM public_signals WHERE verification = 'SYNTHETIC'")
    assert len(real) >= 4 and len(synth) >= 2
    assert all(r["source_url"].startswith("https://") and r["retrieved_at"] for r in real)
    assert all(r["source_url"] is None and r["signal_type"] == "SYNTHETIC_DEMO" for r in synth)
    # signals never become complaints
    assert ro_db.val("SELECT COUNT(*) FROM complaints WHERE source_system LIKE '%SIGNAL%'") == 0


def test_seed_is_audited_and_chain_verifies(ro_db):
    ev = ro_db.one("SELECT * FROM audit_events WHERE action IN ('SEED_DATASET','SEED_RESET') ORDER BY seq LIMIT 1")
    assert ev is not None
    result = chain.verify(ro_db)
    assert result["ok"], result
