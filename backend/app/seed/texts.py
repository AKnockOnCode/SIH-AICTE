"""Synthetic complaint wording.

Templates are used three ways: (1) seeded complaint descriptions, (2) labelled training
examples for the local TF-IDF + Logistic Regression classifier (generated with a separate
random seed), and (3) near-duplicate paraphrases for the duplicate detector. No names or
contact details are ever generated.
"""

from __future__ import annotations

import random
import re

COURSES = ["B.Tech (CSE)", "B.Tech (Mechanical)", "B.Tech (Civil)", "B.Tech (ECE)", "Diploma (Electrical)",
           "MBA", "MCA", "B.Pharm", "D.Pharm", "B.Arch", "M.Tech (Structures)", "PGDM", "B.Tech (AI & DS)"]
HOSTELS = ["A", "B", "C", "boys' hostel 2", "girls' hostel 1", "new hostel"]
DEPTS = ["Computer Engineering", "Mechanical Engineering", "Civil Engineering", "Pharmacy",
         "Management Studies", "Electronics", "Architecture", "Applied Sciences"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
DOCS = ["original 10th and 12th mark sheets", "transfer certificate", "degree certificate",
        "migration certificate", "provisional certificate", "original caste and income certificates"]
EXAMS = ["end-semester examination", "internal assessment", "practical examination", "supplementary examination"]

CLOSERS = [
    "Kindly take necessary action at the earliest.",
    "We request AICTE to intervene.",
    "The management has not responded to repeated requests.",
    "Several students are affected and are afraid to complain openly.",
    "Please treat this complaint as urgent.",
    "The institute grievance committee did not act on our representation.",
    "Supporting documents are attached.",
    "We are ready to provide further details if required.",
    "",
    "",
]

TEMPLATES: dict[str, dict[str, list[str]]] = {
    "RAGGING": {
        "subject": ["Ragging of first-year students in hostel {hostel}", "Ragging incident in {course} first year",
                    "Seniors harassing juniors (ragging) at hostel", "Complaint of ragging and physical intimidation"],
        "desc": [
            "First-year students of {course} were ragged by senior students in hostel {hostel} during the night. Juniors were forced to perform humiliating acts.",
            "My ward is being ragged by seniors since joining in {month}. The anti-ragging squad did not respond when we called.",
            "Senior students forced freshers to stand for hours and shouted abuses at them in the hostel mess. This is clear ragging.",
            "A first-semester student was slapped and threatened by a group of seniors for refusing their orders. Ragging continues despite the anti-ragging affidavit.",
            "Freshers are being made to do assignments of seniors and are bullied by seniors late at night in hostel {hostel}.",
            "Ragging in the name of introduction sessions: juniors are made to shave heads and are verbally abused by senior students.",
            "Two students left the hostel after being ragged repeatedly. The warden ignored the complaint and the anti-ragging committee has not met.",
            "Senior students extorted money and forced juniors to drink alcohol in hostel {hostel}. We fear for the students' safety.",
        ],
    },
    "SEXUAL_HARASSMENT": {
        "subject": ["Sexual harassment complaint against staff member", "Harassment of girl students in {dept}",
                    "Inappropriate behaviour by faculty towards students", "Complaint of sexual harassment and stalking"],
        "desc": [
            "Girl students of {dept} allege sexual harassment by a faculty member who sends inappropriate messages and makes lewd remarks.",
            "A staff member has been stalking a student and making indecent comments. The internal complaints committee did not act.",
            "Students report inappropriate touching by a lab assistant during practical sessions in {dept}.",
            "A faculty member threatened to reduce internal marks if the student did not meet him privately. This amounts to sexual harassment.",
            "The internal complaints committee has not been constituted as required and complaints of harassment by staff are being suppressed.",
            "Women students of {course} complain of repeated lewd remarks and harassment on the campus bus by staff.",
            "A student was molested near the college parking area; the management advised her not to report it.",
        ],
    },
    "CAMPUS_CRIME": {
        "subject": ["Assault on student inside campus", "Theft and violence in hostel", "Drugs being sold near campus",
                    "Student attacked by outsiders on campus"],
        "desc": [
            "A student of {course} was assaulted inside the campus by a group of outsiders; security staff did not intervene.",
            "There have been repeated thefts in hostel {hostel} and one student was beaten when he tried to stop the theft.",
            "Narcotics are being sold to students near the campus gate and security is aware of it.",
            "A student was attacked with a knife after an argument in the canteen. The institute did not inform police promptly.",
            "Outsiders enter the campus at night and threaten students; a robbery took place in the hostel last week.",
            "Students were beaten by private security guards employed by the institute during a protest.",
        ],
    },
    "VIOLENT_STRIKE": {
        "subject": ["Violent strike disrupts classes", "Vandalism during staff strike", "Unrest on campus turned violent",
                    "Students injured during agitation"],
        "desc": [
            "A strike by staff over unpaid salaries turned violent; classrooms were vandalised and students were locked out.",
            "Agitation on campus led to stone pelting and arson near the administrative block. Classes have been suspended for {days} days.",
            "A violent strike by a group of students and outsiders damaged laboratory equipment in {dept}.",
            "Unpaid faculty went on strike and a mob blocked the gate; students could not attend the {exam}.",
            "Vandalism and violence during the strike injured two students. The management has not restored normal functioning.",
        ],
    },
    "FAKE_UNAPPROVED": {
        "subject": ["Course running without AICTE approval", "Admissions to unapproved programme", "Fake course advertised",
                    "Institution operating unapproved campus"],
        "desc": [
            "The institute is admitting students to {course} although the course is not approved by AICTE for this academic year.",
            "Students were promised an AICTE-approved {course} degree but the programme is unapproved and the degree may be invalid.",
            "The institute runs an off-campus centre without AICTE approval and collects fees for an unapproved programme.",
            "Advertisements claim AICTE approval for {course} but the approval list does not show this course. This appears to be a fake course.",
            "Seats beyond the approved intake were filled in {course}; students fear their degrees will not be recognised.",
            "The college changed its name and started a bogus diploma course without approval from AICTE.",
        ],
    },
    "REGULATORY_NONCOMPLIANCE": {
        "subject": ["Severe faculty shortage", "Infrastructure not as per norms", "Mandatory disclosure not updated",
                    "Laboratories without equipment"],
        "desc": [
            "There is a severe faculty shortage in {dept}; many subjects are taught by visiting staff with no qualifications.",
            "Laboratories in {dept} have no working equipment and practical classes are not conducted as per norms.",
            "The institute has not updated its mandatory disclosure and the library has very few books and no journals.",
            "Classrooms and hostels are not as per AICTE norms; the building approved in the application does not exist.",
            "Faculty listed in the approval documents do not actually teach at the institute.",
            "Approval conditions on infrastructure and faculty ratio are being violated in {course}.",
        ],
    },
    "FEE_FRAUD": {
        "subject": ["Excess fee collected without receipt", "Refund of fees denied after cancellation", "Capitation fee demanded for admission",
                    "Illegal fee hike for {course}"],
        "desc": [
            "The institute collected Rs {amount} over and above the approved fee for {course} without issuing receipts.",
            "After cancellation of admission in {month}, the institute refused to refund fees of Rs {amount} including the caution deposit.",
            "Parents were asked to pay a capitation donation of Rs {amount} for admission to {course}.",
            "An extra development charge of Rs {amount} was demanded from all students of {course}; no receipt was given.",
            "The institute increased the hostel and tuition fee mid-year by Rs {amount} without approval of the fee regulatory authority.",
            "Students who left after the first semester were asked to pay the fee for the entire course before getting a refund.",
            "Caution deposit of Rs {amount} has not been refunded to passed-out students even after one year.",
        ],
    },
    "WITHHELD_CERTIFICATES": {
        "subject": ["Original certificates withheld", "Transfer certificate not issued", "Documents not returned after cancellation",
                    "Institute holding mark sheets for fee dues"],
        "desc": [
            "The institute is withholding my {doc} and demanding fees for the remaining years of the course.",
            "Even after cancellation of admission, the college is not returning the {doc}.",
            "Passed-out students of {course} have not received their {doc} for {days} days.",
            "The {doc} of several students are withheld to force payment of disputed dues.",
            "The institute refuses to issue the transfer certificate unless an additional Rs {amount} is paid.",
        ],
    },
    "SCHOLARSHIP": {
        "subject": ["Scholarship amount not credited", "Fee reimbursement pending", "Stipend not paid",
                    "Scholarship application not forwarded"],
        "desc": [
            "My scholarship for {month} has not been credited although the institute verified the application.",
            "The institute did not forward the scholarship applications of eligible students of {course} before the deadline.",
            "Fee reimbursement for SC/ST students has been pending for {days} days and the institute is demanding full fees.",
            "The monthly stipend for {course} scholars has not been paid for three months.",
            "The institute deducted a processing charge from the scholarship amount of Rs {amount}.",
        ],
    },
    "EXAMINATION": {
        "subject": ["Results not declared", "Revaluation request ignored", "Hall ticket withheld", "Irregularities in examination"],
        "desc": [
            "Results of the {exam} for {course} have not been declared for {days} days.",
            "The revaluation request submitted in {month} has not been processed and marks are not updated.",
            "Hall tickets were withheld for students who had not paid an extra examination fee of Rs {amount}.",
            "There were irregularities in the {exam}; question papers were leaked before the examination.",
            "Internal marks were reduced without explanation for students of {course}.",
        ],
    },
    "APPROVAL_RENEWAL": {
        "subject": ["Extension of Approval file", "Intake increase proposal", "Approval renewal processing", "Change of name / approval file"],
        "desc": [
            "Extension of Approval application for the coming academic year received for scrutiny of compliance documents.",
            "Proposal for intake increase in {course} received; expert committee scrutiny pending.",
            "Approval renewal file opened after receipt of the institute's application and affidavit.",
            "Scrutiny of compliance documents for continuation of approval of {course}.",
        ],
    },
    "GENERAL_ENQUIRY": {
        "subject": ["General enquiry about approval status", "Request for information", "Query on admission process",
                    "Enquiry regarding course recognition"],
        "desc": [
            "Request for information about the approval status of the institute and its courses.",
            "Query regarding the admission process and the documents required for lateral entry.",
            "Enquiry about whether the {course} programme is recognised for government jobs.",
            "A parent requests details of the grievance redressal mechanism of the institute.",
            "Request for a copy of the institute's mandatory disclosure and fee structure.",
        ],
    },
}

_SYNONYMS = {
    "institute": "college", "college": "institute", "students": "learners", "complaint": "grievance",
    "refuse": "decline", "refused": "declined", "fees": "charges", "fee": "charge", "demanded": "asked for",
    "collected": "took", "approval": "permission", "seniors": "senior students", "repeated": "multiple",
    "action": "steps", "immediately": "at once", "management": "administration",
}


def fill(template: str, rng: random.Random, slots: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    slots = dict(slots or {})
    defaults = {
        "course": lambda: rng.choice(COURSES), "hostel": lambda: rng.choice(HOSTELS),
        "dept": lambda: rng.choice(DEPTS), "month": lambda: rng.choice(MONTHS),
        "doc": lambda: rng.choice(DOCS), "exam": lambda: rng.choice(EXAMS),
        "amount": lambda: f"{rng.choice([12, 18, 25, 35, 40, 55, 65, 80, 95, 120, 150]) * 1000:,}",
        "days": lambda: str(rng.choice([20, 30, 45, 60, 75, 90])),
    }
    for key in re.findall(r"{(\w+)}", template):
        if key not in slots and key in defaults:
            slots[key] = defaults[key]()
    return template.format(**slots), slots


def make_complaint_text(category: str, rng: random.Random, closer: bool = True) -> tuple[str, str, dict[str, str]]:
    t = TEMPLATES[category]
    desc_t = rng.choice(t["desc"])
    desc, slots = fill(desc_t, rng)
    subject, slots = fill(rng.choice(t["subject"]), rng, slots)
    if closer:
        extra = rng.choice(CLOSERS)
        if extra:
            desc = f"{desc} {extra}"
    return subject, desc, slots


def paraphrase(text: str, rng: random.Random) -> str:
    """Light rewording used for near-duplicate complaints (same grievance filed again)."""
    words = text.split(" ")
    out = []
    for w in words:
        core = w.strip(".,;:").lower()
        if core in _SYNONYMS and rng.random() < 0.45:
            rep = _SYNONYMS[core]
            if w[:1].isupper():
                rep = rep[:1].upper() + rep[1:]
            out.append(w.replace(w.strip(".,;:"), rep))
        else:
            out.append(w)
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(out))
    if len(sentences) > 1 and rng.random() < 0.5:
        sentences = sentences[1:] + sentences[:1]
    lead = rng.choice(["Reminder: ", "Repeat complaint: ", "Again requesting action: ", ""])
    return lead + " ".join(sentences)


def training_examples(n_per_category: int, seed: int) -> list[tuple[str, str]]:
    """Labelled synthetic texts for the local category classifier."""
    rng = random.Random(seed)
    data = []
    for cat in TEMPLATES:
        for _ in range(n_per_category):
            subject, desc, _ = make_complaint_text(cat, rng, closer=rng.random() < 0.7)
            text = f"{subject}. {desc}" if rng.random() < 0.6 else desc
            if rng.random() < 0.25:
                text = paraphrase(text, rng)
            data.append((text, cat))
    rng.shuffle(data)
    return data
