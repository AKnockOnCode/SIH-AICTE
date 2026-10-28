"""Phase 5 critical paths (a–r) exercised through the real UI in headless Chromium against a freshly
seeded server. Tests run in file order and share one server (later steps build on earlier ones)."""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from pathlib import Path

from playwright.sync_api import expect

from conftest import ROOT, shot

HEADLINE = "Potential Overlapping Cases – Coordination Required"
SAMPLES = ROOT / "backend" / "data" / "samples"
STATE: dict[str, str] = {}


def _db(server) -> sqlite3.Connection:
    con = sqlite3.connect(server.db_path, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _audit_actions(server, entity_id: str) -> set[str]:
    with _db(server) as con:
        return {r["action"] for r in con.execute("SELECT action FROM audit_events WHERE entity_id = ?", (entity_id,))}


def field(scope, label: str):
    """Form control by its label text, ignoring the decorative required-field asterisk."""
    return scope.get_by_label(re.compile(rf"^{re.escape(label)}( \*)?$"))


def _kpi(page, label: str):
    return page.locator("section[aria-label='Key figures'] a").filter(has=page.get_by_text(label, exact=True))


# a. Dashboard KPIs derived from seeded records -------------------------------------------------------------
def test_a_dashboard_kpis_from_database(server, open_page):
    page = open_page("competent.authority", "/")
    with _db(server) as con:
        received = con.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
        overdue = con.execute("SELECT COUNT(*) FROM complaints WHERE status != 'DISPOSED' AND expected_disposal_date < '2026-10-27'").fetchone()[0]
        rb = con.execute("SELECT COUNT(*) FROM complaints WHERE bureau_code = 'RB'").fetchone()[0]
    expect(_kpi(page, "Received")).to_contain_text(f"{received:,}")
    expect(_kpi(page, "Overdue (beyond SLA)")).to_contain_text(str(overdue))
    expect(page.get_by_text("Guided demo scenario")).to_be_visible()
    shot(page, "01-dashboard.png")
    page.goto(server.url + "/?bureau=RB")
    expect(_kpi(page, "Received")).to_contain_text(str(rb))
    assert rb < received and not page.errors


# b. Search by name, alias, Permanent ID, case ID, bureau, region, category, status, date range ----------------
def test_b_search_filters(server, open_page):
    page = open_page("competent.authority", "/")
    box = page.get_by_label("Search institutions, aliases, Permanent IDs or case IDs")
    box.fill("Institution A")
    box.press("Enter")
    expect(page).to_have_url(re.compile(r"/search\?q=Institution"))
    expect(page.get_by_role("heading", name="Institution matches")).to_be_visible()
    expect(page.get_by_role("link", name="PGRC-5530").first).to_be_visible()
    shot(page, "02-search.png")
    checks = [
        ("institution=SIET%20Bhopal", "PGRC-5530"),
        ("permanent_id=SYN-1-41730052", "RB-2291"),
        ("case_id=PGRC-5530", "PGRC-5530"),
        ("bureau=RB&region=CENTRAL&category=APPROVAL_RENEWAL&status=UNDER_PROCESS&date_from=2026-10-01&date_to=2026-10-27", "RB-2291"),
    ]
    for query, expected in checks:
        page.goto(f"{server.url}/search?{query}")
        expect(page.get_by_role("link", name=expected, exact=True).first).to_be_visible()
        status, data = server.api("GET", f"/api/cases?{query}&page_size=1")
        assert status == 200
        expect(page.get_by_role("heading", name=re.compile(rf"^{data['total']} cases? found"))).to_be_visible()


# c. Institution profile consolidated history and dossier export/print ---------------------------------------
def test_c_institution_profile_and_dossier(server, open_page):
    page = open_page("senior.mgmt", "/institutions/INS-0001")
    expect(page.get_by_role("heading", name="Sankalp Institute of Engineering & Technology", exact=True)).to_be_visible()
    expect(page.get_by_text(HEADLINE).first).to_be_visible()
    expect(page.get_by_text("Institution Risk Index")).to_be_visible()
    page.get_by_role("tab", name=re.compile("All cases")).click()
    with _db(server) as con:
        n = con.execute("SELECT COUNT(*) FROM complaints WHERE institution_id = 'INS-0001'").fetchone()[0]
    expect(page.get_by_role("tab", name=re.compile("All cases"))).to_contain_text(str(n))
    shot(page, "03-institution-profile.png")
    page.goto(server.url + "/institutions/INS-0001/dossier")
    for title in ("Summary", "Canonical profile and identifiers", "Institution Risk Index and forecast", "Duplicate, related and conflict alerts",
                  "Open cases and current responsibility", "Data provenance"):
        expect(page.get_by_role("heading", name=re.compile(re.escape(title)))).to_be_visible()
    with page.expect_download() as dl:
        page.get_by_role("button", name="Server PDF").click()
    assert Path(dl.value.path()).read_bytes()[:4] == b"%PDF"
    page.emulate_media(media="print")
    expect(page.get_by_role("button", name="Print / save as PDF")).to_be_hidden()  # toolbar not printed
    shot(page, "04-dossier-print.png")
    assert "DOSSIER_GENERATED" in _audit_actions(server, "INS-0001")


# d. Create a complaint with live institution matching and duplicate/overlap checking ------------------------
def test_d_intake_matching_and_overlap_check(server, open_page):
    page = open_page("pgrc.officer", "/cases/new")
    field(page, "Institution name").fill("Sankalp Inst of Engg, Bhopal")
    expect(page.get_by_text("High-confidence match")).to_be_visible(timeout=15000)
    expect(page.get_by_text("Sankalp Institute of Engineering & Technology").first).to_be_visible()
    field(page, "Category").select_option("FEE_FRAUD")
    field(page, "Subject").fill("Caution deposit not refunded to passed-out students")
    field(page, "Description").fill("Passed-out students report that the institute has not refunded the caution deposit and collected "
                                          "excess fee without receipts despite repeated written requests to the accounts office.")
    field(page, "Number of complainants").fill("6")
    expect(page.get_by_text("Duplicates and conflicts across Bureaus/Cells")).to_be_visible(timeout=15000)
    expect(page.get_by_text(re.compile("Priority estimate"))).to_be_visible()
    ack = page.get_by_label(re.compile("I have checked the possible duplicate"))
    if ack.count():
        ack.check()
    shot(page, "05-intake-preview.png")
    page.get_by_role("button", name="Register complaint").click()
    expect(page.get_by_text("Complaint registered")).to_be_visible(timeout=15000)
    case_id = page.get_by_role("link", name=re.compile(r"^PGRC-\d{4,5}$")).first.inner_text()
    STATE["new_case"] = case_id
    with _db(server) as con:
        row = con.execute("SELECT * FROM complaints WHERE id = ?", (case_id,)).fetchone()
        alerts = con.execute("SELECT COUNT(*) FROM overlap_alert_cases WHERE case_id = ?", (case_id,)).fetchone()[0]
    assert row["institution_id"] == "INS-0001" and row["is_synthetic"] == 0 and row["match_status"] == "CONFIRMED"
    assert alerts >= 1  # overlap detection ran on submit
    assert "CASE_CREATED" in _audit_actions(server, case_id)


# e. Confirm / reject an institution match and verify the audit entries -------------------------------------
def test_e_match_review_confirm_and_reject(server, open_page):
    page = open_page("pgrc.officer", "/match-reviews")
    card = page.locator("section#MR-00001")
    expect(card).to_contain_text("Sankalp College Bhopal")
    card.get_by_role("button", name="Confirm").first.click()
    page.get_by_role("dialog").get_by_role("button", name="Confirm match").click()
    expect(page.get_by_text(re.compile("saved"))).to_be_visible()
    card2 = page.locator("section#MR-00002")
    card2.get_by_role("button", name="Not this one").first.click()
    field(page.get_by_role("dialog"), "Remarks").fill("Different institution: SIET Bhopal is not this campus")
    page.get_by_role("dialog").get_by_role("button", name="Reject candidate").click()
    expect(page.get_by_role("dialog")).to_be_hidden()
    assert "MATCH_CONFIRMED" in _audit_actions(server, "MR-00001")
    assert "MATCH_REJECTED" in _audit_actions(server, "MR-00002")
    with _db(server) as con:
        assert con.execute("SELECT institution_id FROM complaints WHERE id = 'PGRC-5561'").fetchone()[0] == "INS-0001"
        assert con.execute("SELECT 1 FROM institution_aliases WHERE alias = 'Sankalp College Bhopal'").fetchone()


# f. Institution A RB/PGRC conflict with the exact warning, plus a live trigger --------------------------------
def test_f_institution_a_conflict_and_live_trigger(server, open_page):
    page = open_page("competent.authority", "/overlaps/OVL-0001")
    expect(page.get_by_text(HEADLINE, exact=True).first).to_be_visible()
    expect(page.get_by_role("link", name="RB-2291").first).to_be_visible()
    expect(page.get_by_role("link", name="PGRC-5530").first).to_be_visible()
    expect(page.get_by_text("same institution")).to_be_visible()
    # Test (d) added a newer fee-fraud complaint to this alert; compare the original pair, as in the demo story.
    page.get_by_role("button", name="Show PGRC-5530 on the left").click()
    expect(page.get_by_role("button", name="Show PGRC-5530 on the left")).to_have_attribute("aria-pressed", "true")
    shot(page, "06-overlap-conflict.png")
    rb = open_page("rb.officer", "/cases/RB-2310")
    rb.get_by_role("button", name="Add action or remark").click()
    field(rb, "Action").select_option("RENEWAL_INITIATED")
    field(rb, "Remarks / details").fill("Extension of Approval 2027-28 initiated after scrutiny")
    rb.get_by_role("dialog").get_by_role("button", name="Add action").click()
    banner = rb.get_by_role("alert").filter(has_text=HEADLINE)
    expect(banner).to_be_visible(timeout=15000)
    shot(rb, "07-live-conflict-trigger.png")
    assert "CASE_ACTION_RENEWAL_INITIATED" in _audit_actions(server, "RB-2310")


# g. Link related cases and merge duplicates into a Master Case without losing originals --------------------------
def test_g_link_and_merge_duplicates(server, open_page):
    _, data = server.api("GET", "/api/overlaps?tier=DUPLICATE&status=OPEN&page_size=100")
    alert = next(a for a in data["items"] if a["bureaus"] == ["PGRC"])
    a, b = alert["cases"][:2]
    page = open_page("pgrc.officer", f"/overlaps/{alert['id']}")
    page.get_by_role("button", name="Link cases").click()
    dlg = page.get_by_role("dialog")
    field(dlg, "Case A").select_option(a)
    field(dlg, "Case B").select_option(b)
    dlg.get_by_role("button", name="Link cases").click()
    expect(dlg).to_be_hidden()
    page.get_by_role("button", name="Merge into Master Case").click()
    dlg = page.get_by_role("dialog")
    for cid in (a, b):
        box = dlg.get_by_role("checkbox", name=re.compile(re.escape(cid)))
        if not box.is_checked():
            box.check()
    field(dlg, "Remarks").fill("Same grievance registered twice; one coordinated record")
    dlg.get_by_role("button", name="Merge").click()
    expect(dlg).to_be_hidden()
    _, detail = server.api("GET", f"/api/overlaps/{alert['id']}")
    mc = detail["master_cases"][0]["id"]
    STATE["master"] = mc
    page.goto(f"{server.url}/master-cases/{mc}")
    expect(page.get_by_role("heading", name=re.compile(mc))).to_be_visible()
    shot(page, "08-master-case.png")
    page.goto(f"{server.url}/cases/{a}")
    expect(page.get_by_text("Merged into Master Case").first).to_be_visible()  # original keeps its own history
    ca = open_page("competent.authority", f"/master-cases/{mc}")
    ca.get_by_role("button", name="Dissolve Master Case").click()
    field(ca.get_by_role("dialog"), "Remarks").fill("Different complainants after verification")
    ca.get_by_role("dialog").get_by_role("button", name="Dissolve").click()
    expect(ca.get_by_text("Dissolved", exact=True).first).to_be_visible()
    with _db(server) as con:
        hist = con.execute("SELECT COUNT(*) FROM master_case_members WHERE master_case_id = ? AND removed_at IS NOT NULL", (mc,)).fetchone()[0]
        assert hist == 2 and con.execute("SELECT COUNT(*) FROM complaints WHERE id IN (?, ?)", (a, b)).fetchone()[0] == 2
    assert {"MASTER_CASE_CREATED", "MASTER_CASE_UNMERGED"} <= _audit_actions(server, mc)


# h. Lead-Bureau recommendation justified by category and workload ----------------------------------------------
def test_h_lead_recommendation(server, open_page):
    page = open_page("competent.authority", "/overlaps/OVL-0001")
    expect(page.get_by_text("Suggested lead: PGRC")).to_be_visible()
    expect(page.get_by_role("columnheader", name="Workload")).to_be_visible()
    expect(page.get_by_text(re.compile(r"workload factor"))).to_be_visible()
    page.get_by_role("button", name="Accept", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="Accept lead").click()
    expect(page.get_by_text("Agreed lead: PGRC")).to_be_visible()
    assert any(a.startswith("LEAD_BUREAU_") for a in _audit_actions(server, "OVL-0001"))


# i. Status, assignment, remarks, transfer and escalation with timeline/audit history -----------------------------
def test_i_workflow_actions(server, open_page):
    page = open_page("pgrc.officer", "/cases/PGRC-4466")

    def op(button: str, fill: dict | None = None, select: dict | None = None, confirm: str | None = None):
        page.get_by_role("button", name=button, exact=True).click()
        dlg = page.get_by_role("dialog")
        for label, value in (select or {}).items():
            field(dlg, label).select_option(value)
        for label, value in (fill or {}).items():
            field(dlg, label).fill(value)
        dlg.get_by_role("button", name=confirm or button, exact=True).click()
        expect(dlg).to_be_hidden()

    op("Change status", select={"New status": "UNDER_PROCESS"})
    op("Assign officer", select={"Officer (PGRC)": "OFF-PGRC-01"}, confirm="Assign")
    op("Add action or remark", select={"Action": "REMARK"}, fill={"Remarks / details": "Institution asked to release certificates within 7 days"},
       confirm="Add action")
    op("Transfer", select={"Transfer to": "SDC"}, fill={"Remarks": "Scholarship component handled by SDC"})
    expect(page.get_by_text(re.compile("Your role cannot change this case"))).to_be_visible()
    ca = open_page("competent.authority", "/cases/PGRC-4466")
    ca.get_by_role("button", name="Escalate", exact=True).click()
    field(ca.get_by_role("dialog"), "Remarks").fill("Certificates withheld for over a month; needs Competent Authority review")
    ca.get_by_role("dialog").get_by_role("button", name="Escalate").click()
    expect(ca.get_by_role("heading", level=1)).to_contain_text("Escalated")
    for label in ("Status changed", "Assigned to officer", "Remark added", "Transferred to another Bureau/Cell", "Escalated"):
        expect(ca.locator("ol > li > p").filter(has_text=re.compile(rf"^{re.escape(label)}")).first).to_be_visible()
    shot(ca, "09-case-workflow.png")
    acts = _audit_actions(server, "PGRC-4466")
    assert {"CASE_STATUS_CHANGED", "CASE_ASSIGNED", "CASE_ACTION_REMARK", "CASE_TRANSFERRED", "CASE_ESCALATED"} <= acts


# j. SLA due date, overdue state, reminders/escalation alerts and breach-risk explanation ----------------------------
def test_j_sla_breach_and_alerts(server, open_page):
    page = open_page("competent.authority", "/cases/PGRC-5530")
    expect(page.get_by_text(re.compile(r"% of time used"))).to_be_visible()
    expect(page.get_by_role("heading", name="Forecast: may breach SLA")).to_be_visible()
    expect(page.get_by_text("What drives this estimate")).to_be_visible()
    shot(page, "10-case-sla-forecast.png")
    page.goto(server.url + "/cases/SDC-7801")
    expect(page.get_by_text(re.compile(r"Overdue by \d+ day\(s\)\. This is a fact"))).to_be_visible()
    page.goto(server.url + "/alerts?type=ESCALATION")
    expect(page.get_by_text("Escalation (level 1): case PGRC-4466").first).to_be_visible()
    page.goto(server.url + "/alerts?type=SLA_OVERDUE")
    first = page.locator("ul > li").filter(has=page.get_by_role("button", name="Acknowledge")).first
    title = first.locator("span.font-semibold").first.inner_text()
    first.get_by_role("button", name="Acknowledge").click()
    expect(page.get_by_text(re.compile(r"acknowledged\.$")).first).to_be_visible()
    page.goto(server.url + "/alerts?type=SLA_OVERDUE&state=ACKNOWLEDGED")
    expect(page.get_by_text(title).first).to_be_visible()
    shot(page, "11-alerts.png")


# k. Edit a priority rule, recalculate/explain, override, and verify the audit entries ---------------------------
def test_k_rules_priority_and_override(server, open_page):
    page = open_page("competent.authority", "/rules")
    page.get_by_label("FEE_FRAUD severity").select_option("4")
    page.get_by_label("FEE_FRAUD weight").fill("4")
    page.get_by_role("button", name="Preview impact").click()
    expect(page.get_by_text(re.compile(r"open cases would change priority band"))).to_be_visible()
    shot(page, "12-rules-preview.png")
    page.get_by_role("button", name=re.compile(r"^Save \d+ change")).click()
    expect(page.get_by_text(re.compile("Rules saved and audited"))).to_be_visible()
    page.goto(server.url + "/cases/PGRC-5530")
    expect(page.get_by_text(re.compile(r"severity 4/5")).first).to_be_visible()
    page.get_by_role("button", name="Override priority").click()
    dlg = page.get_by_role("dialog")
    field(dlg, "New band").select_option("CRITICAL")
    field(dlg, "Reason").fill("Parliament question received on this matter")
    dlg.get_by_role("button", name="Save override").click()
    expect(page.get_by_text(re.compile(r"\(override\)")).first).to_be_visible()
    assert "RULE_CATEGORY_UPDATED" in _audit_actions(server, "FEE_FRAUD")
    assert "PRIORITY_OVERRIDE" in _audit_actions(server, "PGRC-5530")


# l. Risk / watch-list and trust graph, including a rising-risk institution and a trust cluster ------------------------
def test_l_watchlist_and_graph(server, open_page):
    page = open_page("senior.mgmt", "/watchlist")
    entry = page.locator("li").filter(has=page.get_by_role("link", name="Prerana Institute of Technology & Science", exact=True)).first
    expect(entry).to_contain_text("Risk rising")
    shot(page, "13-watchlist.png")
    page.goto(server.url + "/graph?trust=TRS-02")
    expect(page.get_by_role("heading", name="Navankur Education Society")).to_be_visible()
    expect(page.get_by_text(re.compile(r"institutions flagged")).first).to_be_visible()
    page.wait_for_timeout(2500)
    shot(page, "14-trust-graph.png")
    page.get_by_role("button", name=re.compile("Navankur College of Engineering")).first.click()
    expect(page.get_by_role("link", name="Open profile")).to_be_visible()


# m. Report with filters, CSV export and its contents ------------------------------------------------------------
def test_m_report_csv_export(server, open_page):
    page = open_page("senior.mgmt", "/reports?region=CENTRAL&date_from=2025-01-01")
    expect(page.get_by_role("heading", name="Case summary by bureau/cell")).to_be_visible()
    with page.expect_download() as dl:
        page.get_by_role("button", name="Export CSV").click()
    text = Path(dl.value.path()).read_bytes().decode("utf-8-sig")
    meta = [ln for ln in text.splitlines() if ln.startswith("#")]
    rows = list(csv.DictReader(io.StringIO("\n".join(ln for ln in text.splitlines() if not ln.startswith("#")))))
    assert any("SYNTHETIC" in m for m in meta) and any("CENTRAL" in m for m in meta)
    with _db(server) as con:
        n = con.execute("SELECT COUNT(*) FROM complaints WHERE region_code = 'CENTRAL' AND received_date >= '2025-01-01'").fetchone()[0]
    assert sum(int(r["Received"]) for r in rows) == n
    shot(page, "15-reports.png")


# n. Import an institution CSV and a complaint XLSX with mapping, invalid rows and a dry run ----------------------------
def test_n_imports(server, open_page):
    page = open_page("competent.authority", "/imports")
    page.get_by_label("Data type").select_option("INSTITUTIONS")
    page.locator("input[type=file]").set_input_files(str(SAMPLES / "sample_institutions.csv"))
    expect(page.get_by_text("Map your columns")).to_be_visible()
    page.get_by_role("button", name=re.compile("Run dry run")).click()
    expect(page.get_by_text("Dry-run result")).to_be_visible()
    expect(page.get_by_text("Invalid (will be skipped)").locator("..")).to_contain_text("3")
    shot(page, "16-import-dry-run.png")
    page.get_by_role("checkbox", name=re.compile("skip the 3 invalid")).check()
    page.get_by_role("button", name="Commit import").click()
    expect(page.get_by_text(re.compile(r"Import IMP-\d+: Committed"))).to_be_visible()
    page.get_by_role("button", name="Start over").click()
    page.get_by_label("Data type").select_option("COMPLAINTS")
    page.locator("input[type=file]").set_input_files(str(SAMPLES / "sample_complaints.xlsx"))
    page.get_by_role("button", name="Complaints Register").click()
    expect(page.get_by_text(re.compile(r"12 data rows found"))).to_be_visible()
    page.get_by_role("button", name=re.compile("Run dry run")).click()
    expect(page.get_by_text("Invalid (will be skipped)").locator("..")).to_contain_text("5")
    page.get_by_role("checkbox", name=re.compile("skip the 5 invalid")).check()
    page.get_by_role("button", name="Commit import").click()
    expect(page.get_by_text(re.compile(r"Import IMP-\d+: Committed"))).to_be_visible()
    with _db(server) as con:
        assert con.execute("SELECT COUNT(*) FROM complaints WHERE source_system = 'IMPORT'").fetchone()[0] == 7
        assert con.execute("SELECT 1 FROM institutions WHERE name = 'Kesari Institute of Technology'").fetchone()


# o. Public signals with source links / provenance -------------------------------------------------------------------
def test_o_public_signals(server, open_page):
    page = open_page("senior.mgmt", "/signals")
    links = page.get_by_role("link", name="Open source")
    expect(links.first).to_be_visible()
    hrefs = [links.nth(i).get_attribute("href") for i in range(links.count())]
    assert len(hrefs) >= 5 and all(h and h.startswith("https://") for h in hrefs)
    expect(page.get_by_text("No link: this is a synthetic layout example, not a real public signal.").first).to_be_visible()
    expect(page.get_by_text(re.compile("NOT a verified complaint")).first).to_be_visible()
    shot(page, "17-public-signals.png")


# p. Role switching: restricted actions are denied by the server, not just hidden ------------------------------------
def test_p_roles_enforced_server_side(server, open_page):
    page = open_page("competent.authority", "/cases/PGRC-5530")
    expect(page.get_by_role("button", name="Add action or remark")).to_be_visible()
    page.get_by_label(re.compile("Demo role")).select_option("senior.mgmt")
    expect(page.get_by_text(re.compile("Your role cannot change this case"))).to_be_visible()
    with _db(server) as con:
        before = con.execute("SELECT COUNT(*) FROM audit_events WHERE action = 'ACCESS_DENIED'").fetchone()[0]
    r = page.request.post(server.url + "/api/cases/PGRC-5530/actions", headers={"X-Demo-User": "senior.mgmt"},
                          data={"action_type": "REMARK", "remarks": "trying anyway"})
    assert r.status == 403
    r2 = page.request.post(server.url + "/api/cases/PGRC-5530/status", headers={"X-Demo-User": "rb.officer"},
                           data={"status": "PENDING", "remarks": "not my case"})
    assert r2.status == 403
    with _db(server) as con:
        assert con.execute("SELECT COUNT(*) FROM audit_events WHERE action = 'ACCESS_DENIED'").fetchone()[0] >= before + 2


# q. Hash-chain verification, including a deliberately tampered event ------------------------------------------------
def test_q_audit_chain_verification_and_tamper(server, open_page):
    page = open_page("competent.authority", "/audit")
    page.get_by_role("button", name="Verify now").click()
    expect(page.get_by_text(re.compile(r"Chain intact: [\d,]+ events verified"))).to_be_visible()
    shot(page, "18-audit-verify.png")
    with _db(server) as con:
        seq, remarks = con.execute("SELECT seq, remarks FROM audit_events ORDER BY seq LIMIT 1 OFFSET 10").fetchone()
        con.execute("UPDATE audit_events SET remarks = 'tampered' WHERE seq = ?", (seq,))
    try:
        page.get_by_role("button", name="Verify now").click()
        expect(page.get_by_text(re.compile(rf"Chain broken at event #{seq}"))).to_be_visible()
    finally:
        with _db(server) as con:
            con.execute("UPDATE audit_events SET remarks = ? WHERE seq = ?", (remarks, seq))
    page.get_by_role("button", name="Verify now").click()
    expect(page.get_by_text(re.compile(r"Chain intact"))).to_be_visible()


# r. Restart the server: data and user changes persist -----------------------------------------------------------
def test_r_restart_persistence(server, open_page):
    server.stop()
    server.start()
    page = open_page("competent.authority", f"/cases/{STATE['new_case']}")
    expect(page.get_by_role("heading", level=1)).to_contain_text(STATE["new_case"])
    expect(page.get_by_text("Case registered").first).to_be_visible()
    page.goto(server.url + "/rules")
    expect(page.get_by_label("FEE_FRAUD severity")).to_have_value("4")
    page.goto(server.url + f"/master-cases/{STATE['master']}")
    expect(page.get_by_text("Dissolved", exact=True).first).to_be_visible()
    page.goto(server.url + "/institutions?q=Kesari")
    expect(page.get_by_role("link", name="Kesari Institute of Technology").first).to_be_visible(timeout=10000)
    _, inst = server.api("GET", "/api/institutions?q=Kesari")
    assert inst["total"] >= 1
    _, status = server.api("GET", "/api/system/status")
    assert status["data"]["non_synthetic_cases"] >= 8  # 1 intake + 7 imported
