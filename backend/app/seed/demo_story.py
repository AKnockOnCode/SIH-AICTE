"""Hand-seeded demo scenarios with stable IDs (repeatable on every fresh seed).

* Institution A — Sankalp Institute of Engineering & Technology (INS-0001), Central region:
  an older ragging case (PGRC-4127, substantiated), a fee-fraud case under process at PGRC
  (PGRC-5530) and an RB approval-renewal file where the renewal is being initiated
  (RB-2291). The conflict detector must raise "Potential Overlapping Cases – Coordination
  Required" for this combination (wired in by the seeding post-process).
* Institution B — Abhyudaya College of Engineering & Research (INS-0004): an open sexual-
  harassment case at PGRC and an RB intake-increase file *without* a favourable action
  yet, so the detector can be triggered live in the demo by adding that action.
* Raw-name cases needing institution-match review (institution not yet linked).
Synthetic public signals are clearly labelled and carry no URL.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..core.constants import ACTION_TYPES
from .generator import Builder, Event, Inst

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "public"

# case id -> true institution for pending-review demo cases (used by tests only)
PENDING_REVIEW_TRUTH = {
    "PGRC-5561": "INS-0002",
    "PGRC-5562": "INS-0001",
    "PGRC-5564": "INS-0005",
    "RB-2318": "INS-0004",
    "RO-9801": "INS-0007",
    "SDC-7805": None,  # 'Udaan Institute of Technology' is not in the master (new institution)
}


def _replace_timeline(builder: Builder, case: dict[str, Any], received: date,
                      steps: list[tuple[str, int, int, str, str | None, str | None, str | None, str | None, str | None]]) -> None:
    """Swap the generic action history for an exact scripted one.

    step = (action_type, day_offset, hour, actor_label, role, bureau, officer, remarks, to_value)
    """
    builder.actions = [a for a in builder.actions if a["case_id"] != case["id"]]
    for kind, day, hour, actor, role, bureau, officer, remarks, to in steps:
        d = received + timedelta(days=day)
        docs: list[str] = []
        if kind == "NOTICE_ISSUED":
            ref = builder.notice_ref(bureau or "PGRC", d)
            docs.append(builder.add_doc(case["id"], "NOTICE", "Notice to institution seeking response", ref, d))
            remarks = (remarks or "") + f" (Notice {ref})"
        if kind == "INSTITUTION_REPLY_RECEIVED":
            docs.append(builder.add_doc(case["id"], "REPLY", "Institution's reply", None, d))
        builder.act(case, kind, d, hour, actor=actor, role=role, bureau=bureau, officer=officer,
                    remarks=remarks, to=to, docs=docs)
    mine = sorted([a for a in builder.actions if a["case_id"] == case["id"]], key=lambda a: a["action_at"])
    last = mine[-1]
    case["last_action_type"] = last["action_type"]
    case["last_action_at"] = last["action_at"]
    case["last_action_summary"] = ACTION_TYPES[last["action_type"]] + (f": {last['remarks']}" if last["remarks"] else "")
    case["updated_at"] = last["action_at"]


def build(builder: Builder, insts: dict[str, Inst], anchor: date) -> dict[str, Any]:
    ids: list[str] = []

    def add(case_id: str, inst_id: str, category: str, days_ago: int, **o: Any) -> dict[str, Any]:
        o.setdefault("transfers", 0)  # scripted cases stay with the Bureau/Cell named in the story
        ev = Event(inst=insts[inst_id], category=category, received=anchor - timedelta(days=days_ago), protected=True)
        case = builder.realise(ev, case_id, overrides=o)
        ids.append(case_id)
        return case

    a = "INS-0001"
    # 1. Older ragging case, substantiated.
    add("PGRC-4127", a, "RAGGING", 290, bureau="PGRC", complainant_count=3, evidence_count=2, disposed_after=28,
        outcome="SUBSTANTIATED", officer="OFF-PGRC-05", demo_tag="INSTITUTION_A",
        subject="Ragging of first-year students in boys' hostel 2",
        description="First-year B.Tech students were ragged by senior students in boys' hostel 2 over two weeks; "
                    "juniors were forced to perform humiliating acts and one student needed medical attention. "
                    "The anti-ragging squad did not respond to the first call.")
    # 2. Newer fee-fraud case under process at PGRC (PPT: PGRC-5530).
    c = add("PGRC-5530", a, "FEE_FRAUD", 11, bureau="PGRC", complainant_count=14, evidence_count=3, open=True,
            status="UNDER_PROCESS", officer="OFF-PGRC-03", demo_tag="INSTITUTION_A", channel="CPGRAMS",
            raw_name="Sankalp Inst. of Engg. & Tech., Bhopal", raw_pincode=insts[a].pincode,
            raw_address="Bhopal, Madhya Pradesh", match_status="AUTO_LINKED",
            subject="Excess fee collected without receipts; caution deposit not refunded",
            description="Students of B.Tech (CSE) and B.Tech (Mechanical) report that the institute collected "
                        "Rs 65,000 each over and above the approved fee as a 'development charge' without issuing "
                        "receipts, and has refused to refund the caution deposit of passed-out students. Fourteen "
                        "students have jointly signed the complaint and attached fee receipts and bank statements.")
    _replace_timeline(builder, c, anchor - timedelta(days=11), [
        ("CREATED", 0, 11, "Intake – CPGRAMS feed", "SYSTEM", "PGRC", None, "Registered via CPGRAMS feed.", None),
        ("ACKNOWLEDGED", 1, 11, "PGRC desk", "OFFICER", "PGRC", None, None, None),
        ("ASSIGNED", 2, 12, "PGRC section head", "OFFICER", "PGRC", "OFF-PGRC-03", "Assigned to PGRC.", "OFF-PGRC-03"),
        ("NOTICE_ISSUED", 8, 15, "OFF-PGRC-03", "OFFICER", "PGRC", "OFF-PGRC-03",
         "Notice to institution seeking fee records and refund status within 3 days.", None),
        ("INSTITUTION_REPLY_RECEIVED", 10, 16, "PGRC desk", "OFFICER", "PGRC", "OFF-PGRC-03",
         "Reply received; under review.", None),
    ])
    c["next_action"] = "Review institution reply and decide"
    c["next_action_due"] = (anchor - timedelta(days=11) + timedelta(days=15)).isoformat()
    # 3. RB approval-renewal file; renewal being initiated now (PPT: RB-2291).
    c = add("RB-2291", a, "APPROVAL_RENEWAL", 20, bureau="RB", open=True, status="UNDER_PROCESS",
            officer="OFF-RB-02", demo_tag="INSTITUTION_A", channel="RB_PORTAL", raw_name=insts[a].name,
            permanent_id_raw=insts[a].permanent_id,
            subject="Extension of Approval 2027-28 — renewal file",
            description="Application for Extension of Approval (EoA) for academic year 2027-28 received with "
                        "compliance affidavit; scrutiny of faculty, infrastructure and fee documents.")
    _replace_timeline(builder, c, anchor - timedelta(days=20), [
        ("CREATED", 0, 10, "Intake – RB portal", "SYSTEM", "RB", None, "EoA application received via RB portal.", None),
        ("ACKNOWLEDGED", 1, 11, "RB desk", "OFFICER", "RB", None, None, None),
        ("ASSIGNED", 2, 12, "RB section head", "OFFICER", "RB", "OFF-RB-02", "Assigned to RB desk.", "OFF-RB-02"),
        ("SCRUTINY_COMPLETED", 10, 15, "OFF-RB-02", "OFFICER", "RB", "OFF-RB-02",
         "Scrutiny committee: compliance documents in order.", None),
        ("RENEWAL_INITIATED", 18, 16, "OFF-RB-02", "OFFICER", "RB", "OFF-RB-02",
         "Approval renewal (EoA 2027-28) initiated; draft approval letter prepared.", None),
    ])
    c["next_action"] = "Approval decision (issue EoA letter)"
    c["next_action_due"] = (anchor - timedelta(days=20) + timedelta(days=30)).isoformat()
    # 4-13. Remaining Institution A history (four open in total, like the PPT profile).
    add("PGRC-4466", a, "WITHHELD_CERTIFICATES", 48, bureau="PGRC", open=True, status="PENDING", acknowledged=True,
        complainant_count=2, evidence_count=1, officer="OFF-PGRC-02", demo_tag="INSTITUTION_A")
    add("SDC-7801", a, "SCHOLARSHIP", 36, bureau="SDC", open=True, status="UNDER_PROCESS", acknowledged=True,
        complainant_count=6, evidence_count=0, officer="OFF-SDC-02", demo_tag="INSTITUTION_A")
    add("RB-2238", a, "REGULATORY_NONCOMPLIANCE", 410, bureau="RB", disposed_after=75,
        outcome="PARTIALLY_SUBSTANTIATED", officer="OFF-RB-03", demo_tag="INSTITUTION_A")
    add("PGRC-4002", a, "SEXUAL_HARASSMENT", 560, bureau="PGRC", disposed_after=9, outcome="UNSUBSTANTIATED",
        officer="OFF-PGRC-01", demo_tag="INSTITUTION_A")
    add("RB-2105", a, "CAMPUS_CRIME", 700, bureau="RB", disposed_after=12, outcome="SUBSTANTIATED",
        officer="OFF-RB-01", demo_tag="INSTITUTION_A")
    add("PGRC-3920", a, "EXAMINATION", 980, bureau="PGRC", disposed_after=20, outcome="UNSUBSTANTIATED",
        demo_tag="INSTITUTION_A")
    add("PGRC-3655", a, "FEE_FRAUD", 1300, bureau="PGRC", disposed_after=16, outcome="SUBSTANTIATED",
        demo_tag="INSTITUTION_A")
    add("RB-1990", a, "FAKE_UNAPPROVED", 1850, bureau="RB", disposed_after=60, outcome="UNSUBSTANTIATED",
        demo_tag="INSTITUTION_A")
    add("SDC-7790", a, "SCHOLARSHIP", 1650, bureau="SDC", disposed_after=25, outcome="SUBSTANTIATED",
        demo_tag="INSTITUTION_A")
    add("PGRC-3402", a, "GENERAL_ENQUIRY", 2100, bureau="PGRC", disposed_after=10, outcome="NOT_MAINTAINABLE",
        demo_tag="INSTITUTION_A")
    # Recent serious history that drives Institution A's high, rising risk index (all disposed).
    add("RB-2260", a, "CAMPUS_CRIME", 95, bureau="RB", disposed_after=14, outcome="SUBSTANTIATED",
        officer="OFF-RB-05", demo_tag="INSTITUTION_A")
    add("RB-2177", a, "VIOLENT_STRIKE", 150, bureau="RB", disposed_after=21, outcome="SUBSTANTIATED",
        officer="OFF-RB-02", demo_tag="INSTITUTION_A")
    add("PGRC-4602", a, "FEE_FRAUD", 170, bureau="PGRC", disposed_after=18, outcome="SUBSTANTIATED",
        complainant_count=9, demo_tag="INSTITUTION_A")
    add("PGRC-4710", a, "SEXUAL_HARASSMENT", 120, bureau="PGRC", disposed_after=10, outcome="PARTIALLY_SUBSTANTIATED",
        demo_tag="INSTITUTION_A")
    add("PGRC-4555", a, "WITHHELD_CERTIFICATES", 140, bureau="PGRC", disposed_after=16, outcome="SUBSTANTIATED",
        demo_tag="INSTITUTION_A")
    add("RB-2202", a, "FAKE_UNAPPROVED", 330, bureau="RB", disposed_after=40, outcome="PARTIALLY_SUBSTANTIATED",
        demo_tag="INSTITUTION_A")
    add("PGRC-4321", a, "EXAMINATION", 385, bureau="PGRC", disposed_after=14, outcome="UNSUBSTANTIATED",
        demo_tag="INSTITUTION_A")
    add("SDC-7795", a, "SCHOLARSHIP", 600, bureau="SDC", disposed_after=22, outcome="SUBSTANTIATED",
        demo_tag="INSTITUTION_A")

    b = "INS-0004"
    c = add("RB-2310", b, "APPROVAL_RENEWAL", 15, bureau="RB", open=True, status="UNDER_PROCESS", officer="OFF-RB-04",
            demo_tag="LIVE_TRIGGER", channel="RB_PORTAL", raw_name=insts[b].name,
            subject="Intake increase proposal — B.Tech (AI & DS), AY 2027-28",
            description="Proposal for increase in intake of B.Tech (AI & DS) from 120 to 180 for AY 2027-28; "
                        "expert committee scrutiny of faculty and laboratory compliance.")
    _replace_timeline(builder, c, anchor - timedelta(days=15), [
        ("CREATED", 0, 10, "Intake – RB portal", "SYSTEM", "RB", None, "Intake increase proposal received.", None),
        ("ACKNOWLEDGED", 1, 11, "RB desk", "OFFICER", "RB", None, None, None),
        ("ASSIGNED", 1, 12, "RB section head", "OFFICER", "RB", "OFF-RB-04", "Assigned to RB desk.", "OFF-RB-04"),
        ("SCRUTINY_COMPLETED", 10, 15, "OFF-RB-04", "OFFICER", "RB", "OFF-RB-04",
         "Expert committee scrutiny completed; decision pending.", None),
    ])
    c["next_action"] = "Decide intake increase proposal"
    c["next_action_due"] = (anchor - timedelta(days=15) + timedelta(days=30)).isoformat()
    c = add("PGRC-5544", b, "SEXUAL_HARASSMENT", 9, bureau="PGRC", open=True, status="UNDER_PROCESS",
            complainant_count=4, evidence_count=2, officer="OFF-PGRC-06", demo_tag="LIVE_TRIGGER",
            subject="Harassment of women students by a faculty member",
            description="Women students of B.Tech (ECE) allege repeated lewd remarks and inappropriate messages by a "
                        "faculty member; the internal complaints committee has not met despite two representations.")
    _replace_timeline(builder, c, anchor - timedelta(days=9), [
        ("CREATED", 0, 10, "Intake – PGRC online portal", "SYSTEM", "PGRC", None, "Registered via PGRC online portal.", None),
        ("ACKNOWLEDGED", 0, 15, "PGRC desk", "OFFICER", "PGRC", None, None, None),
        ("ASSIGNED", 1, 11, "PGRC section head", "OFFICER", "PGRC", "OFF-PGRC-06", "Assigned to PGRC.", "OFF-PGRC-06"),
        ("NOTICE_ISSUED", 3, 15, "OFF-PGRC-06", "OFFICER", "PGRC", "OFF-PGRC-06",
         "Institution directed to convene ICC and report within 7 days.", None),
        ("INSPECTION_ORDERED", 7, 12, "OFF-PGRC-06", "OFFICER", "PGRC", "OFF-PGRC-06",
         "Fact-finding visit by regional committee ordered.", None),
    ])
    c["next_action"] = "Fact-finding report awaited"
    c["next_action_due"] = (anchor + timedelta(days=3)).isoformat()

    # Raw-name cases whose institution has not yet been confirmed (match-review queue).
    pending = [
        ("PGRC-5561", "INS-0002", "FEE_FRAUD", 6, "PGRC", "Sankalp College Bhopal", "Bhopal, Madhya Pradesh"),
        ("PGRC-5562", "INS-0001", "EXAMINATION", 5, "PGRC", "S.I.E.T Bhopal", "Bhopal"),
        ("PGRC-5564", "INS-0005", "RAGGING", 4, "PGRC", "Prerna Inst. of Tech & Sci", "Telangana"),
        ("RB-2318", "INS-0004", "REGULATORY_NONCOMPLIANCE", 7, "RB", "Abhyudaya Engg College", "Maharashtra"),
        ("RO-9801", "INS-0007", "GENERAL_ENQUIRY", 3, "RO", "Navankur Institute", "Maharashtra"),
        ("SDC-7805", "INS-0005", "SCHOLARSHIP", 2, "SDC", "Udaan Institute of Technology, Warangal", "Warangal, Telangana"),
    ]
    for cid, truth, cat, days, bureau, raw, addr in pending:
        inst = insts[truth]
        add(cid, truth, cat, days, bureau=bureau, raw_name=raw, raw_address=addr, raw_pincode=None,
            permanent_id_raw=None, institution_id=None, match_status="PENDING_REVIEW", open=True,
            status="PENDING" if days > 3 else "RECEIVED", acknowledged=days > 3, demo_tag="MATCH_REVIEW",
            region_code=inst.region, state=inst.state)
    return {
        "case_ids": ids,
        "institution_a": "INS-0001",
        "institution_b": "INS-0004",
        "rising_risk": "INS-0005",
        "flagged_trust": "TRS-02",
        "conflict_trigger": {"case_id": "RB-2291", "action_type": "RENEWAL_INITIATED"},
    }


def load_public_signals() -> list[dict[str, Any]]:
    path = DATA_DIR / "public_signals.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["signals"]


SYNTHETIC_SIGNALS = [
    {"id": "SIG-S01", "title": "SYNTHETIC DEMO SIGNAL — local report of a student protest over fee demands",
     "raw_institution_text": "Sankalp Institute of Engineering and Technology, Bhopal", "institution_id": "INS-0001",
     "match_confidence": 0.97, "match_status": "MATCHED",
     "summary": "Layout example only: a fictional local news-style item describing students protesting additional fee "
                "demands. Not a real article; no source exists."},
    {"id": "SIG-S02", "title": "SYNTHETIC DEMO SIGNAL — hostel safety concerns raised by parents",
     "raw_institution_text": "Prerana Institute of Tech & Science, Warangal", "institution_id": "INS-0005",
     "match_confidence": 0.93, "match_status": "MATCHED",
     "summary": "Layout example only: a fictional item about parents raising hostel-safety concerns. Not a real "
                "article; no source exists."},
    {"id": "SIG-S03", "title": "SYNTHETIC DEMO SIGNAL — notice-style list mentioning 'Navankur Institute'",
     "raw_institution_text": "Navankur Institute", "institution_id": "INS-0007",
     "match_confidence": 0.58, "match_status": "UNCERTAIN",
     "summary": "Layout example only: a fictional notice naming 'Navankur Institute' without a campus, so the match "
                "to a specific institution is uncertain and needs human review."},
]


def insert_signals(db, anchor: date) -> None:
    now = f"{anchor.isoformat()}T04:30:00Z"
    for i, s in enumerate(load_public_signals(), start=1):
        db.insert("public_signals", {
            "id": f"SIG-{i:04d}", "signal_type": s["signal_type"], "verification": "VERIFIED_SOURCE",
            "scope": s.get("scope", "SECTOR"), "title": s["title"], "publisher": s["publisher"],
            "source_url": s["source_url"], "published_date": s.get("published_date"),
            "retrieved_at": s["retrieved_at"], "summary": s["summary"],
            "raw_institution_text": s.get("raw_institution_text"), "institution_id": None,
            "match_confidence": None, "match_status": "NO_MATCH", "notes": s.get("notes"),
            "import_job_id": None, "created_at": now,
        })
    for s in SYNTHETIC_SIGNALS:
        db.insert("public_signals", {
            "id": s["id"], "signal_type": "SYNTHETIC_DEMO", "verification": "SYNTHETIC", "scope": "INSTITUTION",
            "title": s["title"], "publisher": "None — synthetic example", "source_url": None,
            "published_date": None, "retrieved_at": None, "summary": s["summary"],
            "raw_institution_text": s["raw_institution_text"], "institution_id": s["institution_id"],
            "match_confidence": s["match_confidence"], "match_status": s["match_status"],
            "notes": "Generated for UI layout and entity-match demonstration. Never presented as a real signal.",
            "import_job_id": None, "created_at": now,
        })
    db.run("INSERT OR IGNORE INTO id_counters(name, value) VALUES ('signal', ?)",
           (len(load_public_signals()) + 1,))
