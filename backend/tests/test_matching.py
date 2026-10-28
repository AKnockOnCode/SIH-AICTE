"""Phase 2: canonicalisation, fuzzy similarity, calibrated matching and human feedback."""

from __future__ import annotations

from app.audit import chain
from app.core.security import resolve_user
from app.institutions import matcher
from app.institutions import service as inst_service
from app.institutions.fuzzy import partial_ratio, ratio, token_set_ratio, token_sort_ratio
from app.institutions.normalize import acronym, normalize_name


def test_canonicalisation_and_fuzzy_functions():
    a = normalize_name("Sankalp Inst. of Engg. & Tech., Bhopal")
    b = normalize_name("SANKALP INSTITUTE OF ENGINEERING AND TECHNOLOGY (Main Campus)")
    assert a == b == "sankalp institute engineering technology"
    assert acronym("Sankalp Institute of Engineering & Technology") == "siet"
    assert ratio("prerna", "prerana") > 90
    assert ratio("abc", "xyz") == 0
    assert token_sort_ratio("college engineering navankur", "navankur college engineering") == 100
    assert token_set_ratio("navankur", "navankur college engineering") == 100
    assert partial_ratio("sankalp", "the sankalp institute") == 100


def test_variants_resolve_to_the_right_institution(ro_db):
    cases = [
        ("Sankalp Inst. of Engg. & Tech., Bhopal", None, "INS-0001", {"AUTO_LINK"}),
        ("Sankalap Institute of Enginering & Technology", None, "INS-0001", {"AUTO_LINK", "REVIEW"}),
        ("Prerna Inst. of Tech & Sci", "Telangana", "INS-0005", {"REVIEW", "AUTO_LINK"}),
        ("Abhyudaya College Pune", None, "INS-0004", {"AUTO_LINK"}),
        ("Institution A", None, "INS-0001", {"AUTO_LINK"}),
    ]
    for raw, addr, expected, decisions in cases:
        res = matcher.match(ro_db, matcher.Query(raw, raw_address=addr))
        top = res["candidates"][0]
        assert top["institution_id"] == expected, raw
        assert res["decision"] in decisions, (raw, res["decision"])
        assert 0 <= top["confidence"] <= 1 and top["factors"], raw
        assert any(f["factor"] == "name" for f in top["factors"])


def test_identifier_acronym_ambiguity_and_no_match(ro_db):
    res = matcher.match(ro_db, matcher.Query("some name", raw_permanent_id="SYN-1-41730052"))
    assert res["candidates"][0]["institution_id"] == "INS-0001" and res["candidates"][0]["confidence"] >= 0.99
    assert any(f["factor"] == "permanent_id" for f in res["candidates"][0]["factors"])
    acr = matcher.match(ro_db, matcher.Query("S.I.E.T Bhopal", raw_address="Bhopal"))
    assert acr["decision"] == "REVIEW" and acr["candidates"][0]["institution_id"] == "INS-0001"
    amb = matcher.match(ro_db, matcher.Query("Sankalp College Bhopal", raw_address="Bhopal, Madhya Pradesh"))
    assert amb["decision"] == "REVIEW" and "Ambiguous" in amb["reason"]
    none = matcher.match(ro_db, matcher.Query("Udaan Institute of Technology, Warangal"))
    assert none["decision"] == "NO_MATCH"
    # low confidence never auto-links
    for raw in ("Navankur Inst.", "Engineering College", "Institute of Technology"):
        r = matcher.match(ro_db, matcher.Query(raw))
        if r["decision"] == "AUTO_LINK":
            assert r["candidates"][0]["confidence"] >= r["thresholds"]["auto_link"]


def test_model_is_calibrated_on_synthetic_validation(ro_db):
    model = matcher.load_model()
    assert model is not None and model["metrics"]["brier_score"] < 0.05
    assert model["features"] == matcher.FEATURES


def test_confirm_and_reject_feed_back_into_matching(db):
    ca = resolve_user(db, "competent.authority")
    review = db.one("SELECT * FROM match_reviews WHERE source_ref = 'PGRC-5564'")
    assert review["status"] == "PENDING"
    before_events = db.val("SELECT COUNT(*) FROM audit_events")
    out = inst_service.confirm(db, ca, review["id"], "INS-0005", "Verified with complainant: Prerana, Warangal")
    assert out["status"] == "CONFIRMED"
    case = db.one("SELECT * FROM complaints WHERE id = 'PGRC-5564'")
    assert case["institution_id"] == "INS-0005" and case["match_status"] == "CONFIRMED" and case["region_code"] == "SOUTH_CENTRAL"
    assert db.one("SELECT 1 FROM institution_aliases WHERE institution_id='INS-0005' AND alias_type='CONFIRMED_MATCH'")
    assert db.val("SELECT COUNT(*) FROM audit_events") > before_events
    assert db.one("SELECT 1 FROM audit_events WHERE action = 'MATCH_CONFIRMED' AND entity_id = ?", (review["id"],))
    again = matcher.match(db, matcher.Query("Prerna Inst. of Tech & Sci"))
    assert again["candidates"][0]["institution_id"] == "INS-0005" and again["candidates"][0]["confidence"] >= 0.97
    # Reject: the rejected pairing is down-weighted next time
    review2 = db.one("SELECT * FROM match_reviews WHERE source_ref = 'PGRC-5561'")
    first = review2["best_institution_id"]
    before = matcher.match(db, matcher.Query("Sankalp College Bhopal"))
    conf_before = next(c["confidence"] for c in before["candidates"] if c["institution_id"] == first)
    res = inst_service.reject(db, ca, review2["id"], first, "Complainant confirmed it is the polytechnic, not SIET")
    assert res["status"] in ("PENDING", "REJECTED")
    after = matcher.match(db, matcher.Query("Sankalp College Bhopal"))
    conf_after = next(c["confidence"] for c in after["candidates"] if c["institution_id"] == first)
    assert conf_after < conf_before * 0.5
    assert chain.verify(db)["ok"]


def test_new_institution_from_review(db):
    pgrc = resolve_user(db, "competent.authority")
    review = db.one("SELECT * FROM match_reviews WHERE source_ref = 'SDC-7805'")
    out = inst_service.resolve_with_new_institution(db, pgrc, review["id"], {"state": "Telangana", "district": "Warangal"},
                                                    "Not in master; created after verification")
    inst = db.one("SELECT * FROM institutions WHERE id = ?", (out["institution_id"],))
    assert inst["name"].startswith("Udaan") and inst["region_code"] == "SOUTH_CENTRAL"
    assert db.one("SELECT institution_id FROM complaints WHERE id='SDC-7805'")["institution_id"] == inst["id"]
