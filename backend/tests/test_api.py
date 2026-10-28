"""Phase 3: API integration — OpenAPI coverage, role restrictions (server-side), search filters, dashboard,
reports + CSV export, dossier, imports (mapping, dry run, commit), alerts, rules, persistence."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from starlette.testclient import TestClient

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
CA = {"X-Demo-User": "competent.authority"}
RB = {"X-Demo-User": "rb.officer"}
PGRC = {"X-Demo-User": "pgrc.officer"}
RO = {"X-Demo-User": "ro.central"}
SM = {"X-Demo-User": "senior.mgmt"}


@pytest.fixture
def client(db_path):
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def test_openapi_documents_every_route(client):
    spec = client.get("/api/openapi.json").json()
    from app.main import ROUTERS

    for r in ROUTERS:
        for ep in r.endpoints:
            path = ep.path.replace(":path", "")
            assert path in spec["paths"], path
            assert ep.method.lower() in spec["paths"][path], (ep.method, path)
    public = {"/api/health", "/api/system/me", "/api/system/users", "/api/system/permissions", "/api/system/reference"}
    for path, ops in spec["paths"].items():
        for op in ops.values():
            assert op["x-permission"] or path in public, path
    assert spec["components"]["securitySchemes"]["DemoUser"]["name"] == "X-Demo-User"
    assert client.get("/api/docs").status_code == 200


def test_role_restrictions_are_enforced_server_side(client, db_path):
    from app.db.database import connect

    r = client.post("/api/cases/PGRC-5530/actions", json={"action_type": "REMARK", "remarks": "sm tries"}, headers=SM)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    r = client.post("/api/cases/PGRC-5530/status", json={"status": "PENDING", "remarks": "rb tries"}, headers=RB)
    assert r.status_code == 403
    r = client.put("/api/rules/settings/matching", json={"value": {"auto_link_threshold": 0.95}}, headers=PGRC)
    assert r.status_code == 403
    r = client.get("/api/cases/PGRC-5544", headers=RO)  # Western region case, Central regional office
    assert r.status_code == 403
    rows = client.get("/api/cases?page_size=200", headers=RO).json()["items"]
    assert rows and {x["region_code"] for x in rows} == {"CENTRAL"}
    assert client.get("/api/cases?page_size=1", headers={"X-Demo-User": "nobody"}).status_code == 401
    with connect(db_path) as db:
        denied = db.all("SELECT * FROM audit_events WHERE action = 'ACCESS_DENIED'")
    assert len(denied) >= 3 and {d["actor_role"] for d in denied} >= {"SENIOR_MANAGEMENT", "RB_OFFICER", "PGRC_OFFICER"}
    me = client.get("/api/system/me", headers=SM).json()
    assert "case.update" not in me["permissions"] and "Prototype role simulation" in me["notice"]


def test_validation_errors_are_consistent(client):
    r = client.post("/api/cases/PGRC-5530/transfer", json={"to_bureau": "RB"}, headers=PGRC)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error" and r.json()["error"]["details"]
    r = client.post("/api/cases/PGRC-5530/transfer", content=b"{not json", headers={**PGRC, "content-type": "application/json"})
    assert r.status_code == 400
    assert client.get("/api/cases/NOPE-1", headers=CA).status_code == 404
    assert client.get("/api/nope", headers=CA).status_code == 404


def test_search_by_every_required_field(client):
    def ids(q):
        return {x["id"] for x in client.get(f"/api/cases?page_size=200&{q}", headers=CA).json()["items"]}

    by_name = ids("institution=Sankalp Institute of Engineering")
    assert {"PGRC-5530", "RB-2291", "PGRC-4127"} <= by_name
    assert "PGRC-5530" in ids("institution=Institution A")  # alias
    assert "PGRC-5530" in ids("permanent_id=SYN-1-41730052")
    assert ids("case_id=PGRC-5530") == {"PGRC-5530"}
    assert all(x.startswith(("RB-", "PGRC-", "AB-", "SDC-", "LC-", "RO-")) for x in ids("bureau=RB"))
    rb = client.get("/api/cases?bureau=RB&page_size=50", headers=CA).json()["items"]
    assert rb and {x["bureau_code"] for x in rb} == {"RB"}
    cen = client.get("/api/cases?region=CENTRAL&category=RAGGING&page_size=50", headers=CA).json()["items"]
    assert cen and all(x["region_code"] == "CENTRAL" and x["category_code"] == "RAGGING" for x in cen)
    st = client.get("/api/cases?status=ESCALATED&page_size=50", headers=CA).json()["items"]
    assert st and {x["status"] for x in st} == {"ESCALATED"}
    dr = client.get("/api/cases?date_from=2026-10-01&date_to=2026-10-20&page_size=200", headers=CA).json()["items"]
    assert dr and all("2026-10-01" <= x["received_date"] <= "2026-10-20" for x in dr)
    combo = client.get("/api/cases?institution_id=INS-0001&status=UNDER_PROCESS&bureau=PGRC", headers=CA).json()
    assert {x["id"] for x in combo["items"]} == {"PGRC-5530"} and combo["total"] == 1
    g = client.get("/api/search?q=SIET Bhopal", headers=CA).json()
    assert g["institutions"][0]["id"] == "INS-0001"
    assert client.get("/api/search?q=PGRC-5530", headers=CA).json()["cases"][0]["id"] == "PGRC-5530"


def test_dashboard_is_computed_and_filters_change_results(client, db_path):
    from app.db.database import connect

    all_ = client.get("/api/dashboard", headers=CA).json()
    with connect(db_path) as db:
        assert all_["kpis"]["received"] == db.val("SELECT COUNT(*) FROM complaints")
        assert all_["kpis"]["overdue"] == db.val("SELECT COUNT(*) FROM complaints WHERE status != 'DISPOSED' AND "
                                                 "expected_disposal_date < '2026-10-27'")
    k = all_["kpis"]
    assert k["pending"] + k["under_process"] + k["transferred"] + k["escalated"] == k["open_total"]
    recent = client.get("/api/dashboard?date_from=2026-01-01", headers=CA).json()
    assert 0 < recent["kpis"]["received"] < k["received"]
    pgrc = client.get("/api/dashboard?bureau=PGRC", headers=CA).json()
    assert pgrc["kpis"]["received"] == next(b for b in all_["by_bureau"] if b["code"] == "PGRC")["received"]
    assert all_["demo"]["institution_a"]["id"] == "INS-0001" and all_["demo"]["institution_a_conflict"]
    assert all_["overlaps"]["open_by_tier"]["CONFLICT"] >= 1 and all_["multi_bureau_count"] >= 5


def test_reports_and_csv_export_match(client, db_path):
    from app.db.database import connect

    table = client.get("/api/reports/summary?group_by=region&date_from=2025-01-01", headers=CA).json()
    resp = client.get("/api/reports/export?report=summary&group_by=region&date_from=2025-01-01&fmt=csv", headers=CA)
    assert resp.status_code == 200 and "attachment" in resp.headers["content-disposition"]
    text = resp.content.decode("utf-8-sig")
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    rows = list(csv.DictReader(io.StringIO("\n".join(lines))))
    assert len(rows) == len(table["rows"])
    assert sum(int(r["Received"]) for r in rows) == sum(r["received"] for r in table["rows"])
    assert "SYNTHETIC" in text and "date_from" in text
    with connect(db_path) as db:
        assert sum(int(r["Received"]) for r in rows) == db.val("SELECT COUNT(*) FROM complaints WHERE received_date >= '2025-01-01'")
        assert db.one("SELECT 1 FROM audit_events WHERE action = 'REPORT_EXPORTED'")
    x = client.get("/api/reports/export?report=ageing&fmt=xlsx", headers=SM)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    for rep in ("ageing", "performance?period=quarter", "sla", "overlaps"):
        assert client.get(f"/api/reports/{rep}", headers=SM).json()["rows"]


def test_dossier_json_and_pdf(client):
    d = client.get("/api/institutions/INS-0001/dossier", headers=SM).json()
    for key in ("institution", "case_history", "open_cases", "overlaps", "risk", "pending_sla", "recommendations", "provenance",
                "disclaimer", "narrative"):
        assert key in d
    assert d["narrative"]["source"] == "TEMPLATE" and "OVL-" in d["narrative"]["text"]
    assert d["overlaps"][0]["headline"] == "Potential Overlapping Cases – Coordination Required"
    assert any(c["id"] == "PGRC-5530" and c["officer"] for c in d["open_cases"])
    ai = client.get("/api/institutions/INS-0001/dossier?narrative=ai", headers=SM).json()
    assert ai["narrative"]["source"] == "TEMPLATE" and "not configured" in ai["narrative"]["validation"]["note"]
    pdf = client.get("/api/institutions/INS-0001/dossier.pdf", headers=SM)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_ai_narrative_validation_rejects_invented_facts(db):
    from app.core.security import resolve_user
    from app.dossier.service import build, template_narrative, validate_ai_text

    facts = {"ids": ["PGRC-5530", "RB-2291"], "score": 69.0, "count": 23, "probability": 0.43}
    assert validate_ai_text("PGRC-5530 and RB-2291 overlap; 23 cases; risk 69; 43% forecast.", facts)["ok"]
    bad = validate_ai_text("PGRC-9999 was substantiated in 2017 with 450 complainants.", facts)
    assert not bad["ok"] and "PGRC-9999" in bad["unknown_ids"] and "450" in bad["unknown_numbers"]
    d = build(db, resolve_user(db, "senior.mgmt"), "INS-0001")
    facts = {k: v for k, v in d.items() if k != "narrative"}
    assert validate_ai_text(template_narrative(facts), facts)["ok"]  # the deterministic text is fully grounded


def test_ai_narrative_paths_with_stubbed_model(db, client, monkeypatch):
    """The optional AI wording path, with the model call stubbed (no key or network needed):
    no key -> template; call fails -> template; invented ID -> rejected; faithful wording -> labelled AI-assisted."""
    from app.core.security import resolve_user
    from app.dossier import service as dossier

    user = resolve_user(db, "senior.mgmt")
    off = dossier.build(db, user, "INS-0001", narrative_mode="ai")
    assert off["narrative"]["source"] == "TEMPLATE" and "not configured" in off["narrative"]["validation"]["note"]
    template = off["narrative"]["text"]

    monkeypatch.setattr(dossier.llm, "available", lambda: True)
    replies: list[str | None] = [None, "Synthetic data. PGRC-9999 is also pending against the institution.",
                                 "Synthetic demo data. " + template]
    monkeypatch.setattr(dossier.llm, "complete", lambda *a, **k: replies.pop(0))
    failed = dossier.build(db, user, "INS-0001", narrative_mode="ai")["narrative"]
    assert failed["source"] == "TEMPLATE" and "unavailable" in failed["validation"]["note"]
    rejected = dossier.build(db, user, "INS-0001", narrative_mode="ai")["narrative"]
    assert rejected["source"] == "TEMPLATE" and rejected["validation"]["unknown_ids"] == ["PGRC-9999"]
    accepted = dossier.build(db, user, "INS-0001", narrative_mode="ai")["narrative"]
    assert accepted["source"] == "AI_ASSISTED" and accepted["text"].startswith("Synthetic demo data.")

    # The optional AI category suggestion degrades cleanly when no key is configured.
    monkeypatch.undo()
    r = client.post("/api/classify", json={"text": "The college collected excess fees and refused receipts.", "use_llm": True},
                    headers=SM)
    assert r.status_code == 200 and r.json()["llm"]["available"] is False and r.json()["local"]


def _upload(client, name, kind, headers=CA):
    with (SAMPLES / name).open("rb") as f:
        return client.post(f"/api/imports/upload?kind={kind}", files={"file": (name, f.read())}, headers=headers)


def test_institution_import_mapping_dry_run_and_commit(client, db_path):
    from app.db.database import connect

    r = _upload(client, "sample_institutions.csv", "INSTITUTIONS")
    assert r.status_code == 201, r.text
    up = r.json()
    m = up["suggested_mapping"]
    assert m["name"] == "College Name" and m["permanent_id"] == "AICTE ID" and m["state"] == "State"
    assert m["intake_total"] == "Total Intake" and m["trust_name"] == "Trust/Society"
    job = up["job"]["id"]
    v = client.post(f"/api/imports/{job}/validate", json={"mapping": m}, headers=CA).json()
    c = v["counts"]
    assert c["total"] == 8 and c["invalid"] == 3 and c["insert"] >= 2 and c["matched"] >= 1 and c["review"] >= 1
    codes = {i["code"] for i in v["issues"]}
    assert {"INVALID_VALUE", "REQUIRED", "DUPLICATE_IN_FILE"} <= codes
    with connect(db_path) as db:
        before = db.val("SELECT COUNT(*) FROM institutions")
    no_ack = client.post(f"/api/imports/{job}/commit", json={"mapping_hash": v["mapping_hash"]}, headers=CA)
    assert no_ack.status_code == 409
    bad_hash = client.post(f"/api/imports/{job}/commit", json={"mapping_hash": "x", "acknowledge_skipped": True}, headers=CA)
    assert bad_hash.status_code == 409
    ok = client.post(f"/api/imports/{job}/commit", json={"mapping_hash": v["mapping_hash"], "acknowledge_skipped": True}, headers=CA)
    assert ok.status_code == 200, ok.text
    s = ok.json()["summary"]["counts"]
    assert s["INSERTED"] >= 2 and s["SKIPPED"] == 3 and s["MATCHED"] >= 1
    with connect(db_path) as db:
        assert db.val("SELECT COUNT(*) FROM institutions") == before + s["INSERTED"]
        kesari = db.one("SELECT * FROM institutions WHERE permanent_id = 'SYN-1-49990001'")
        assert kesari["intake_source"] == "IMPORTED" and kesari["is_synthetic"] == 0 and kesari["trust_id"]
        assert db.one("SELECT 1 FROM audit_events WHERE action = 'IMPORT_COMMITTED' AND entity_id = ?", (job,))
    assert client.post(f"/api/imports/{job}/commit", json={"mapping_hash": v["mapping_hash"], "acknowledge_skipped": True},
                       headers=CA).status_code == 409


def test_complaint_xlsx_import_with_sheet_selection(client, db_path):
    from app.db.database import connect

    up = _upload(client, "sample_complaints.xlsx", "COMPLAINTS", headers=PGRC).json()
    assert up["sheets"] == ["Read me", "Complaints Register"]
    up = client.post(f"/api/imports/{up['job']['id']}/sheet", json={"sheet": "Complaints Register"}, headers=PGRC).json()
    m = up["suggested_mapping"]
    assert m["source_case_id"] == "Complaint No" and m["received_date"] == "Date of Receipt" and m["category"] == "Nature of Complaint"
    assert m["bureau"] == "Bureau/Cell" and m["institution_name"] == "Name of Institution"
    job = up["job"]["id"]
    v = client.post(f"/api/imports/{job}/validate", json={"mapping": m}, headers=PGRC).json()
    assert v["counts"]["total"] == 12 and v["counts"]["invalid"] == 5
    commit = client.post(f"/api/imports/{job}/commit", json={"mapping_hash": v["mapping_hash"], "acknowledge_skipped": True},
                         headers=PGRC)
    assert commit.status_code == 200, commit.text
    counts = commit.json()["summary"]["counts"]
    assert counts["SKIPPED"] == 5 and counts["INSERTED"] + counts["INSERTED_NEEDS_REVIEW"] == 7
    with connect(db_path) as db:
        rows = db.all("SELECT * FROM complaints WHERE source_system = 'IMPORT' ORDER BY source_ref")
        assert len(rows) == 7 and all(r["source_ref"].startswith("IMP/") and r["id"] != r["source_ref"] for r in rows)
        rb = next(r for r in rows if r["source_ref"] == "IMP/RB/2026/003")
        assert rb["institution_id"] == "INS-0001" and rb["bureau_code"] == "RB"
        udaan = next(r for r in rows if r["source_ref"] == "IMP/SDC/2026/004")
        assert udaan["institution_id"] is None and udaan["match_status"] == "PENDING_REVIEW"
        assert db.one("SELECT 1 FROM match_reviews WHERE source_ref = ? AND source_type = 'IMPORT'", (udaan["id"],))
        disposed = next(r for r in rows if r["source_ref"] == "IMP/RO/2026/009")
        assert disposed["status"] == "DISPOSED" and disposed["outcome"] == "UNSUBSTANTIATED"
    sig = _upload(client, "sample_complaints.xlsx", "PUBLIC_SIGNALS", headers=PGRC)
    assert sig.status_code == 403


def test_alerts_rules_and_overlap_endpoints(client):
    alerts = client.get("/api/alerts?state=NEW&page_size=5", headers=PGRC).json()
    assert alerts["items"] and "In-app" in alerts["delivery_note"]
    aid = alerts["items"][0]["id"]
    assert client.post(f"/api/alerts/{aid}/act", json={"action": "ACKNOWLEDGE"}, headers=SM).status_code == 403
    assert client.post(f"/api/alerts/{aid}/act", json={"action": "ACKNOWLEDGE"}, headers=PGRC).json()["state"] == "ACKNOWLEDGED"
    assert client.post(f"/api/alerts/{aid}/act", json={"action": "RESOLVE"}, headers=PGRC).status_code == 422
    prev = client.post("/api/rules/preview", json={"categories": {"FEE_FRAUD": {"severity_weight": 4.5, "severity_level": 4}}},
                       headers=SM).json()
    assert prev["valid"] and prev["band_changes"] > 0
    bad = client.post("/api/rules/preview", json={"settings": {"matching": {"review_threshold": 0.95}}}, headers=SM).json()
    assert not bad["valid"]
    upd = client.put("/api/rules/categories/FEE_FRAUD", json={"severity_weight": 4.5, "severity_level": 4}, headers=CA)
    assert upd.status_code == 200 and upd.json()["recomputed"] > 1000
    assert client.post("/api/rules/reset", json={"confirm": "NO"}, headers=CA).status_code == 422
    assert client.post("/api/rules/reset", json={"confirm": "RESET"}, headers=CA).status_code == 200
    conflict = client.get("/api/overlaps?tier=CONFLICT", headers=CA).json()["items"][0]
    assert conflict["institution_id"] == "INS-0001"
    detail = client.get(f"/api/overlaps/{conflict['id']}", headers=PGRC).json()
    assert detail["permissions"]["can_act"] and not detail["permissions"]["can_decide"]
    assert detail["members"][0]["role"] == "TRIGGER" and detail["recommendation"]["recommended"] == "PGRC"
    lk = client.post(f"/api/overlaps/{conflict['id']}/link", headers=PGRC,
                     json={"case_a": "PGRC-5530", "case_b": "RB-2291", "link_type": "CONFLICT", "remarks": "Coordinate"})
    assert lk.status_code == 201
    lead = client.post(f"/api/overlaps/{conflict['id']}/lead", json={"decision": "ACCEPT", "remarks": "Agreed"}, headers=CA)
    assert lead.json()["decided_lead"] == "PGRC"
    mc = client.post(f"/api/overlaps/{conflict['id']}/merge", headers=CA, json={
        "case_ids": ["PGRC-5530", "RB-2291"], "kind": "COORDINATION", "lead_bureau": "PGRC", "remarks": "One coordinated record"})
    assert mc.status_code == 201
    master = client.get(f"/api/master-cases/{mc.json()['master_case_id']}", headers=SM).json()
    assert len(master["cases"]) == 2
    assert client.post(f"/api/master-cases/{mc.json()['master_case_id']}/unmerge", json={"remarks": "test unmerge"},
                       headers=PGRC).status_code == 403
    verify = client.post("/api/audit/verify", headers=SM).json()
    assert verify["ok"] and verify["checked"] > 10


def test_intake_api_and_persistence_across_restart(db_path):
    from app.main import create_app

    payload = {"institution_name": "Navankur Inst. of Technology, Nashik", "category_code": "EXAMINATION",
               "subject": "Revaluation results pending", "description": "Revaluation results of the supplementary examination "
               "have not been declared for sixty days.", "received_date": "2026-10-26", "bureau_code": "PGRC",
               "complainant_count": 12}
    with TestClient(create_app()) as c:
        assert c.get("/api/dashboard", headers=SM).json()["data_mode"] == "SYNTHETIC"
        prev = c.post("/api/cases/preview", json=payload, headers=PGRC).json()
        assert prev["institution_match"]["candidates"][0]["institution_id"] == "INS-0007"
        assert prev["priority"]["chips"] and prev["ml_suggestion"]["top"][0]["category"] == "EXAMINATION"
        out = c.post("/api/cases", json={**payload, "institution_id": "INS-0007", "match_decision": "CONFIRM"}, headers=PGRC)
        assert out.status_code == 201, out.text
        case_id = out.json()["case_id"]
        assert c.post(f"/api/cases/{case_id}/actions", json={"action_type": "NOTICE_ISSUED", "remarks": "Notice sent"},
                      headers=PGRC).status_code == 200
    with TestClient(create_app()) as c2:  # "restart"
        d = c2.get(f"/api/cases/{case_id}", headers=SM).json()
        assert d["case"]["institution_id"] == "INS-0007" and d["case"]["is_synthetic"] is False
        assert [t["action_type"] for t in d["timeline"]][:2] == ["CREATED", "NOTICE_ISSUED"]
        assert c2.get("/api/system/status", headers=SM).json()["data"]["non_synthetic_cases"] >= 1
        # Once a real (entered) record exists, every disclaimer says the data is mixed, not purely synthetic.
        assert c2.get("/api/dashboard", headers=SM).json()["data_mode"] == "MIXED"
        csv_text = c2.get("/api/reports/export?report=summary&group_by=bureau&fmt=csv", headers=SM).text
        assert "MIXED DATA" in csv_text and "SYNTHETIC demo records" in csv_text
        assert c2.get("/api/institutions/INS-0007/dossier", headers=SM).json()["disclaimer"].startswith("MIXED DATA")


def test_public_signals_are_separate_and_imported_with_provenance(client, db_path):
    from app.db.database import connect

    listing = client.get("/api/signals", headers=SM).json()
    verified = [s for s in listing["items"] if s["verification"] == "VERIFIED_SOURCE"]
    assert len(verified) == 5 and all(s["source_url"].startswith("https://") and s["retrieved_at"] and s["summary"] for s in verified)
    assert all(s["source_url"] is None for s in listing["items"] if s["verification"] == "SYNTHETIC")
    assert "NOT a verified complaint" in listing["disclaimer"]
    # .test is a reserved TLD (RFC 2606): clearly a test fixture, never presented as a real source.
    body = (b"Headline,Agency,Link,Published,Summary,College\n"
            b"Circular on fee refunds,Test Agency,https://notices.test/circular-1,2026-10-01,Reminder about refund timelines.,"
            b"Sankalp Institute of Engineering and Technology Bhopal\n"
            b"Template row,Test Agency,https://www.example.org/x,2026-10-02,Placeholder text,\n")
    with connect(db_path) as db:
        n_cases = db.val("SELECT COUNT(*) FROM complaints")
    files = {"file": ("signals.csv", body)}
    assert client.post("/api/imports/upload?kind=PUBLIC_SIGNALS", files=files, headers=PGRC).status_code == 403
    up = client.post("/api/imports/upload?kind=PUBLIC_SIGNALS", files=files, headers=CA).json()
    m = up["suggested_mapping"]
    assert m["source_url"] == "Link" and m["publisher"] == "Agency" and m["institution_text"] == "College"
    job = up["job"]["id"]
    v = client.post(f"/api/imports/{job}/validate", json={"mapping": m}, headers=CA).json()
    assert v["counts"]["invalid"] == 1 and any(i["code"] == "EXAMPLE_URL" for i in v["issues"])
    r = client.post(f"/api/imports/{job}/commit", json={"mapping_hash": v["mapping_hash"], "acknowledge_skipped": True}, headers=CA)
    assert r.status_code == 200, r.text
    new = [s for s in client.get("/api/signals?verification=UNVERIFIED", headers=SM).json()["items"]
           if s["source_url"] == "https://notices.test/circular-1"]
    assert len(new) == 1 and new[0]["institution_id"] == "INS-0001" and new[0]["match_status"] == "MATCHED"
    assert new[0]["import_job_id"] == job and "not verified" in new[0]["notes"]
    with connect(db_path) as db:
        assert db.val("SELECT COUNT(*) FROM complaints") == n_cases  # a signal never becomes a complaint
    again = client.post("/api/imports/upload?kind=PUBLIC_SIGNALS", files=files, headers=CA).json()
    v2 = client.post(f"/api/imports/{again['job']['id']}/validate", json={"mapping": m}, headers=CA).json()
    assert any(i["code"] == "ALREADY_IMPORTED" for i in v2["issues"])


def test_overlap_status_and_non_destructive_unmerge_via_api(client):
    dup = client.get("/api/overlaps?tier=DUPLICATE&status=OPEN&page_size=50", headers=CA).json()["items"]
    target = next(a for a in dup if a["bureaus"] == ["PGRC"])  # case IDs keep their original prefix after transfers
    assert client.post(f"/api/overlaps/{target['id']}/status", json={"status": "UNDER_REVIEW", "remarks": "Looking"},
                       headers=SM).status_code == 403
    assert client.post(f"/api/overlaps/{target['id']}/status", json={"status": "UNDER_REVIEW", "remarks": "x"},
                       headers=PGRC).status_code == 422  # remarks are mandatory (min length)
    r = client.post(f"/api/overlaps/{target['id']}/status", json={"status": "UNDER_REVIEW", "remarks": "Checking registers"},
                    headers=PGRC)
    assert r.status_code == 200 and r.json()["status"] == "UNDER_REVIEW"
    before = {cid: client.get(f"/api/cases/{cid}", headers=CA).json()["case"] for cid in target["cases"][:2]}
    mc = client.post(f"/api/overlaps/{target['id']}/merge", headers=PGRC, json={
        "case_ids": target["cases"][:2], "kind": "DUPLICATE_MERGE", "remarks": "Same complainant, same issue"})
    assert mc.status_code == 201, mc.text
    mid = mc.json()["master_case_id"]
    for cid, old in before.items():
        now = client.get(f"/api/cases/{cid}", headers=CA).json()
        assert now["case"]["id"] == cid and now["case"]["status"] == old["status"] and now["case"]["master_case_id"] == mid
        assert "MERGED_INTO_MASTER" in [t["action_type"] for t in now["timeline"]]
    out = client.post(f"/api/master-cases/{mid}/unmerge", json={"remarks": "Different complainants after all"}, headers=CA)
    assert out.status_code == 200
    master = client.get(f"/api/master-cases/{mid}", headers=SM).json()
    assert master["master"]["status"] == "DISSOLVED" and len(master["membership_history"]) == 2
    assert all(h["removed_at"] for h in master["membership_history"])
    for cid in before:
        tl = [t["action_type"] for t in client.get(f"/api/cases/{cid}", headers=CA).json()["timeline"]]
        assert "MERGED_INTO_MASTER" in tl and "REMOVED_FROM_MASTER" in tl  # history kept, nothing deleted
