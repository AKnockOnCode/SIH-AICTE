"""Deterministic synthetic data generator (institutions, trusts, ~1,200 cases, histories).

Reproducibility: everything is derived from (seed, anchor_date). The anchor is the
"today" of the dataset (default: the date the seed runs, so a fresh `make reset-db` before a
demo gives a realistic SLA picture). Same seed + same anchor => byte-identical core data,
verified by `fingerprint()` and tests. Seeding is idempotent: if a seed run is recorded the
generator does nothing unless `reset=True`.

Modelling notes (all synthetic, documented in README):
* Institutions are fictional (names + SYN- Permanent IDs) to avoid attaching synthetic
  ragging/harassment complaints to real colleges.
* Complaint arrivals per institution follow a Poisson background rate scaled by size,
  a latent risk factor and a yearly growth factor; serious complaints self-excite
  (cluster representation of a Hawkes process), which gives the forecaster real signal.
* Disposal durations are log-normal by severity and Bureau, slowed by admission-season
  load and transfers and sped up by Court/VIP/Parliament references; a share of recent
  cases are left as backlog so that open/overdue figures are realistic.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ..core.clock import iso_z, ist_datetime
from ..core.constants import ACTION_TYPES, CHANNELS
from ..core.util import bump_counter, canonical_json, dumps, sha256_hex
from ..institutions.normalize import acronym, normalize_name
from ..scoring.rules import DEFAULT_CATEGORY_RULES, seed_rules
from . import texts
from .reference import OFFICER_COUNTS, STATES, seed_reference

GENERATOR_VERSION = "1.0.0"
START_DATE = date(2019, 1, 1)
TARGET_CASES = 1200

CAT = {r["code"]: r for r in DEFAULT_CATEGORY_RULES}
COMPLAINT_CATS = [c for c, r in CAT.items() if r["family"] != "REGULATORY_PROCESS"]
SERIOUS_CATS = [c for c in COMPLAINT_CATS if CAT[c]["severity_level"] >= 4]
SAFETY_CATS = [c for c in COMPLAINT_CATS if CAT[c]["family"] == "SAFETY"]

BASE_CATEGORY_WEIGHTS = {
    "FEE_FRAUD": 18, "WITHHELD_CERTIFICATES": 11, "SCHOLARSHIP": 11, "EXAMINATION": 13,
    "GENERAL_ENQUIRY": 9, "REGULATORY_NONCOMPLIANCE": 8, "FAKE_UNAPPROVED": 3, "RAGGING": 3.5,
    "SEXUAL_HARASSMENT": 2.2, "CAMPUS_CRIME": 2.6, "VIOLENT_STRIKE": 1.3,
}
YEAR_GROWTH = {2019: 0.55, 2020: 0.6, 2021: 0.75, 2022: 0.85, 2023: 1.0, 2024: 1.15, 2025: 1.3, 2026: 1.45, 2027: 1.5}
SEASONALITY = {1: 0.85, 2: 0.85, 3: 0.85, 4: 0.85, 5: 0.85, 6: 0.9, 7: 1.3, 8: 1.5, 9: 1.6, 10: 1.5, 11: 1.1, 12: 0.85}
MEDIAN_DAYS = {5: 4.5, 4: 21.0, 3: 9.5, 2: 9.0, 1: 16.0}
BUREAU_SPEED = {"PGRC": 1.1, "RB": 1.3, "AB": 1.0, "SDC": 1.25, "LC": 1.6, "RO": 1.15}
ALT_BUREAU = {
    "PGRC": ["RO", "RB"], "RB": ["AB", "RO"], "SDC": ["PGRC", "RO"], "AB": ["RB"], "LC": ["PGRC"], "RO": ["PGRC"],
}

PREFIXES = [
    "Utkarsh", "Saarthi", "Medhavi", "Anveshan", "Srijan", "Arohan", "Jigyasa", "Kshitij", "Shikhar",
    "Tejasvi", "Pragyan", "Nirmiti", "Ujjwal", "Samarth", "Aakaar", "Vedika", "Unnati", "Satyam",
    "Sanmati", "Chetana", "Amrut", "Navyug", "Suvidya", "Kalpak", "Dhruvtara", "Yashas", "Varenya",
    "Ankur", "Ishanya", "Matrika", "Nakshatra", "Parivartan", "Rachana", "Sahyog", "Tarang", "Udbhav",
    "Vikalp", "Yogdaan", "Agrima", "Bodhi", "Chaitanya", "Deepshikha", "Gatishil", "Hiranya", "Jyotirmay",
]
TYPES = [
    ("Institute of Engineering & Technology", "Engineering"),
    ("College of Engineering", "Engineering"),
    ("Institute of Technology", "Engineering"),
    ("Polytechnic", "Polytechnic"),
    ("College of Pharmacy", "Pharmacy"),
    ("Institute of Management Studies", "Management"),
    ("School of Architecture", "Architecture"),
    ("Institute of Technology & Science", "Engineering"),
    ("College of Engineering & Research", "Engineering"),
    ("Institute of Computer Applications", "Computer Applications"),
]
INTAKE_RANGE = {"Engineering": (480, 1500), "Polytechnic": (240, 660), "Pharmacy": (100, 300),
                "Management": (120, 480), "Architecture": (40, 160), "Computer Applications": (120, 360)}
COURSES_BY_TYPE = {
    "Engineering": ["B.Tech (CSE)", "B.Tech (Mechanical)", "B.Tech (Civil)", "B.Tech (ECE)", "B.Tech (AI & DS)", "M.Tech"],
    "Polytechnic": ["Diploma (Electrical)", "Diploma (Mechanical)", "Diploma (Civil)", "Diploma (Computer)"],
    "Pharmacy": ["B.Pharm", "D.Pharm", "M.Pharm"],
    "Management": ["MBA", "PGDM"],
    "Architecture": ["B.Arch", "M.Arch"],
    "Computer Applications": ["MCA", "BCA"],
}
LOCALITIES = ["Station Road", "Ring Road", "Industrial Area", "Sector 4", "Bypass Road", "College Road",
              "Highway Junction", "Gandhi Nagar", "Shanti Vihar", "Lake View Road", "Tech Park Road"]

TRUSTS = [
    ("TRS-01", "Sankalp Shiksha Samiti", "Madhya Pradesh"),
    ("TRS-02", "Navankur Education Society", "Maharashtra"),
    ("TRS-03", "Vidyaprabha Charitable Trust", "Karnataka"),
    ("TRS-04", "Gyanodaya Shiksha Sansthan", "Uttar Pradesh"),
    ("TRS-05", "Utkal Prajna Educational Trust", "Odisha"),
    ("TRS-06", "Kaveri Technical Education Society", "Tamil Nadu"),
    ("TRS-07", "Shivalik Foundation for Technical Education", "Punjab"),
    ("TRS-08", "Brahmaputra Knowledge Trust", "Assam"),
]
# trust -> preferred states for generated member institutions
TRUST_STATES = {
    "TRS-03": ["Karnataka", "Tamil Nadu", "Karnataka"],
    "TRS-04": ["Uttar Pradesh", "Uttar Pradesh", "Uttarakhand"],
    "TRS-05": ["Odisha", "Odisha"],
    "TRS-06": ["Tamil Nadu", "Tamil Nadu", "Puducherry"],
    "TRS-07": ["Punjab", "Haryana", "Himachal Pradesh"],
    "TRS-08": ["Assam", "Meghalaya"],
}


@dataclass
class Inst:
    id: str
    name: str
    itype: str
    state: str
    district: str
    pincode: str
    region: str
    intake: int
    established: int
    trust_id: str | None
    risk: float
    alpha: float
    permanent_id: str
    address: str
    courses: list[str]
    rising: bool = False
    demo_tag: str | None = None
    bulk: bool = True
    former_name: str | None = None
    aliases: list[tuple[str, str]] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)


@dataclass
class Event:
    inst: Inst
    category: str
    received: date
    protected: bool = False
    dup_of: Event | None = None
    shared_external: bool = False
    paraphrase_of: str | None = None
    dup_subject: str | None = None
    process: str | None = None  # for APPROVAL_RENEWAL files: 'EOA' | 'INTAKE'


# ----------------------------------------------------------------------------- names
def _misspell(word: str, rng: random.Random) -> str:
    if len(word) < 5:
        return word
    i = rng.randrange(1, len(word) - 2)
    op = rng.choice(["swap", "drop", "double", "vowel"])
    if op == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if op == "drop":
        return word[:i] + word[i + 1:]
    if op == "double":
        return word[:i] + word[i] + word[i:]
    vowels = "aeiou"
    if word[i] in vowels:
        return word[:i] + rng.choice([v for v in vowels if v != word[i]]) + word[i + 1:]
    return word[:i] + word[i] + "a" + word[i + 1:]


def _abbreviate(name: str) -> str:
    out = name
    for full, short in (("Institute", "Inst."), ("Engineering", "Engg."), ("Technology", "Tech."),
                        ("College", "Coll."), ("Management", "Mgmt."), ("Pharmacy", "Pharm."),
                        ("Science", "Sci."), ("Research", "Res.")):
        out = out.replace(full, short)
    return out


def make_variants(inst: Inst, rng: random.Random) -> list[str]:
    acr = acronym(inst.name).upper()
    words = inst.name.split(" ")
    long_idx = [i for i, w in enumerate(words) if len(w) >= 6]
    mis_words = list(words)
    if long_idx:
        j = rng.choice(long_idx)
        mis_words[j] = _misspell(words[j], rng)
    variants = [
        f"{inst.name}, {inst.district}",
        inst.name.upper(),
        _abbreviate(inst.name),
        " ".join(mis_words),
        f"{acr}, {inst.district}",
        f"{inst.name} (Main Campus)",
        inst.name.replace("&", "and").replace(",", ""),
        f"{_abbreviate(inst.name)} {inst.district}",
    ]
    if inst.former_name:
        variants.append(inst.former_name)
    return variants


# ----------------------------------------------------------------------------- institutions
def _pincode(prefix: str, rng: random.Random) -> str:
    return prefix + f"{rng.randrange(1, 999):03d}"


def _new_inst(iid: str, name: str, itype: str, state: str, district: str, rng: random.Random, *,
              trust_id: str | None, risk: float, alpha: float, intake: int | None = None,
              demo_tag: str | None = None, rising: bool = False, bulk: bool = True,
              former_name: str | None = None, permanent_id: str | None = None) -> Inst:
    region, districts = STATES[state]
    prefix = dict(districts)[district]
    lo, hi = INTAKE_RANGE[itype]
    courses = COURSES_BY_TYPE[itype]
    return Inst(
        id=iid, name=name, itype=itype, state=state, district=district,
        pincode=_pincode(prefix, rng), region=region,
        intake=intake or int(round(rng.randint(lo, hi) / 30) * 30),
        established=rng.randint(1998, 2016), trust_id=trust_id, risk=risk, alpha=alpha,
        permanent_id=permanent_id or f"SYN-1-4{rng.randrange(1000000, 9999999)}",
        address=f"{rng.randint(2, 98)}, {rng.choice(LOCALITIES)}, {district}",
        courses=rng.sample(courses, k=min(len(courses), rng.randint(2, len(courses)))),
        rising=rising, demo_tag=demo_tag, bulk=bulk, former_name=former_name,
    )


def build_institutions(rng: random.Random) -> list[Inst]:
    insts: list[Inst] = []
    # Hand-specified demo institutions (stable IDs).
    insts.append(_new_inst("INS-0001", "Sankalp Institute of Engineering & Technology", "Engineering",
                           "Madhya Pradesh", "Bhopal", rng, trust_id="TRS-01", risk=2.2, alpha=0.3,
                           intake=720, demo_tag="INSTITUTION_A", bulk=False,
                           former_name="Sankalp College of Engineering", permanent_id="SYN-1-41730052"))
    insts.append(_new_inst("INS-0002", "Sankalp Polytechnic", "Polytechnic", "Madhya Pradesh", "Bhopal", rng,
                           trust_id="TRS-01", risk=1.1, alpha=0.15, intake=360))
    insts.append(_new_inst("INS-0003", "Sankalp College of Pharmacy", "Pharmacy", "Madhya Pradesh", "Indore", rng,
                           trust_id="TRS-01", risk=0.9, alpha=0.1, intake=120))
    insts.append(_new_inst("INS-0004", "Abhyudaya College of Engineering & Research", "Engineering", "Maharashtra",
                           "Pune", rng, trust_id=None, risk=1.2, alpha=0.2, intake=960, demo_tag="LIVE_TRIGGER"))
    insts.append(_new_inst("INS-0005", "Prerana Institute of Technology & Science", "Engineering", "Telangana",
                           "Warangal", rng, trust_id=None, risk=1.3, alpha=0.35, intake=720,
                           demo_tag="RISING_RISK", rising=True))
    navankur = [
        ("INS-0006", "Navankur College of Engineering", "Engineering", "Maharashtra", "Kolhapur", 2.0),
        ("INS-0007", "Navankur Institute of Technology", "Engineering", "Maharashtra", "Nashik", 1.8),
        ("INS-0008", "Navankur Institute of Management Studies", "Management", "Karnataka", "Belagavi", 1.7),
        ("INS-0009", "Navankur School of Pharmacy", "Pharmacy", "Goa", "North Goa", 1.5),
        ("INS-0010", "Navankur Polytechnic", "Polytechnic", "Maharashtra", "Chhatrapati Sambhajinagar", 1.0),
    ]
    for iid, name, itype, state, district, risk in navankur:
        insts.append(_new_inst(iid, name, itype, state, district, rng, trust_id="TRS-02", risk=risk,
                               alpha=0.35 if risk > 1.4 else 0.15, demo_tag="FLAGGED_TRUST"))

    used_names = {i.name for i in insts}
    prefixes = list(PREFIXES)
    rng.shuffle(prefixes)
    state_list = list(STATES)
    n = len(insts)
    trust_cycle = []
    for tid, members in TRUST_STATES.items():
        for st in members:
            trust_cycle.append((tid, st))
    k = 0
    while len(insts) < 60:
        n += 1
        prefix = prefixes[k % len(prefixes)]
        k += 1
        tname, itype = rng.choice(TYPES)
        if trust_cycle:
            trust_id, state = trust_cycle.pop(0)
        else:
            trust_id, state = None, rng.choice(state_list)
        district = rng.choice(STATES[state][1])[0]
        name = f"{prefix} {tname}"
        if name in used_names:
            continue
        used_names.add(name)
        risk = math.exp(rng.gauss(0, 0.45))
        former = None
        if rng.random() < 0.12:
            former = f"{prefix} {rng.choice(['College of Technology', 'Engineering College', 'Technical Institute'])}"
        insts.append(_new_inst(f"INS-{n:04d}", name, itype, state, district, rng, trust_id=trust_id,
                               risk=round(risk, 3), alpha=0.25 if risk > 1.3 else 0.12, former_name=former))
    for inst in insts:
        inst.variants = make_variants(inst, rng)
        acr = acronym(inst.name).upper()
        inst.aliases = [(f"{acr} {inst.district}", "ABBREVIATION"), (_abbreviate(inst.name), "ABBREVIATION")]
        if inst.former_name:
            inst.aliases.append((inst.former_name, "FORMER_NAME"))
    insts[0].aliases.append(("Institution A", "DEMO_LABEL"))
    insts[3].aliases.append(("Institution B", "DEMO_LABEL"))
    return insts


# ----------------------------------------------------------------------------- events
def _poisson(lam: float, rng: random.Random) -> int:
    if lam <= 0:
        return 0
    if lam > 50:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    l_exp, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l_exp:
            return k
        k += 1


def _category_weights(inst: Inst) -> list[tuple[str, float]]:
    out = []
    for cat, w in BASE_CATEGORY_WEIGHTS.items():
        if CAT[cat]["family"] == "SAFETY":
            w *= inst.risk ** 1.1
        elif CAT[cat]["family"] == "REGULATORY":
            w *= inst.risk ** 0.8
        out.append((cat, w))
    return out


def _pick(weighted: list[tuple[str, float]], rng: random.Random) -> str:
    total = sum(w for _, w in weighted)
    r = rng.random() * total
    acc = 0.0
    for item, w in weighted:
        acc += w
        if r <= acc:
            return item
    return weighted[-1][0]


def generate_events(insts: list[Inst], anchor: date, rng: random.Random, base_rate: float) -> list[Event]:
    events: list[Event] = []
    for inst in insts:
        if not inst.bulk:
            continue
        size = (inst.intake / 700.0) ** 0.5
        weights = _category_weights(inst)
        for year in range(START_DATE.year, anchor.year + 1):
            y0 = max(START_DATE, date(year, 1, 1))
            y1 = min(anchor, date(year, 12, 31))
            span = (y1 - y0).days + 1
            if span <= 0:
                continue
            lam = base_rate * size * inst.risk * YEAR_GROWTH.get(year, 1.5) * span / 365.0
            for _ in range(_poisson(lam, rng)):
                # Admission-season seasonality via rejection sampling (Jul-Oct busier).
                while True:
                    d = y0 + timedelta(days=rng.randrange(span))
                    if rng.random() * 1.6 <= SEASONALITY[d.month]:
                        break
                events.append(Event(inst=inst, category=_pick(weights, rng), received=d))
        if inst.rising:
            # Surge of serious complaints in the last ~8 months (rising-risk demo institution).
            for _ in range(11):
                d = anchor - timedelta(days=rng.randint(3, 150))
                events.append(Event(inst=inst, category=rng.choice(SAFETY_CATS + ["FAKE_UNAPPROVED"]),
                                    received=d, protected=True))
    # Self-excitation: each serious event spawns Poisson(alpha) serious follow-ups (Hawkes cluster form).
    queue = [e for e in events if e.category in SERIOUS_CATS]
    while queue:
        parent = queue.pop(0)
        for _ in range(_poisson(parent.inst.alpha, rng)):
            delay = max(1, int(rng.expovariate(1 / 50.0)))
            d = parent.received + timedelta(days=delay)
            if d > anchor:
                continue
            child = Event(inst=parent.inst, category=rng.choice(SERIOUS_CATS), received=d, protected=parent.protected)
            events.append(child)
            queue.append(child)
    return events


def approval_events(insts: list[Inst], anchor: date, rng: random.Random) -> list[Event]:
    out: list[Event] = []
    for inst in insts:
        if not inst.bulk:
            continue
        for year in range(START_DATE.year, anchor.year + 1):
            if rng.random() < 0.12:
                d = date(year, rng.randint(2, 4), rng.randint(1, 28))
                if d <= anchor:
                    out.append(Event(inst=inst, category="APPROVAL_RENEWAL", received=d, process="EOA"))
            if rng.random() < 0.05:
                d = date(year, rng.randint(1, 12), rng.randint(1, 28))
                if d <= anchor:
                    out.append(Event(inst=inst, category="APPROVAL_RENEWAL", received=d, process="INTAKE"))
    return out


# ----------------------------------------------------------------------------- case realisation
class Builder:
    """Turns events into complaint rows, action histories and document references."""

    def __init__(self, anchor: date, rng: random.Random):
        self.anchor = anchor
        self.rng = rng
        self.cases: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.docs: list[dict[str, Any]] = []
        self.doc_seq = 0
        self.ref_seq: dict[tuple[str, int], int] = {}
        self.cpg_seq: dict[int, int] = {}
        self.notice_seq: dict[tuple[str, int], int] = {}

    # -- helpers ---------------------------------------------------------------
    def officer_for(self, bureau: str, region: str) -> str:
        if bureau == "RO":
            return f"OFF-RO-{region}"
        return f"OFF-{bureau}-{self.rng.randint(1, OFFICER_COUNTS[bureau]):02d}"

    def source_ref(self, bureau: str, d: date, region: str) -> str:
        key = (bureau, d.year)
        self.ref_seq[key] = self.ref_seq.get(key, 0) + 1
        n = self.ref_seq[key]
        if bureau == "RO":
            return f"RO-{region[:3]}/{d.year}/{n:04d}"
        letter = {"PGRC": "G", "RB": "R", "AB": "A", "SDC": "S", "LC": "L"}[bureau]
        return f"{bureau}/{letter}/{d.year}/{n:05d}"

    def cpgrams_ref(self, d: date) -> str:
        self.cpg_seq[d.year] = self.cpg_seq.get(d.year, 0) + 1
        return f"CPG/SYN/{d.year}/{self.cpg_seq[d.year]:06d}"

    def notice_ref(self, bureau: str, d: date) -> str:
        key = (bureau, d.year)
        self.notice_seq[key] = self.notice_seq.get(key, 0) + 1
        return f"{bureau}/N/{d.year}/{self.notice_seq[key]:04d}"

    def add_doc(self, case_id: str, doc_type: str, title: str, ref: str | None, d: date) -> str:
        self.doc_seq += 1
        doc_id = f"DOC-{self.doc_seq:06d}"
        self.docs.append({
            "id": doc_id, "case_id": case_id, "doc_type": doc_type, "title": title, "reference_no": ref,
            "file_name": None, "stored_name": None, "mime_type": None, "size_bytes": None, "sha256": None,
            "added_by": "seed", "added_role": "SYSTEM", "is_synthetic": 1, "created_at": f"{d.isoformat()}T06:00:00Z",
        })
        return doc_id

    def act(self, case: dict[str, Any], kind: str, d: date, hour: int, *, actor: str, role: str | None,
            bureau: str | None, officer: str | None = None, remarks: str | None = None, frm: str | None = None,
            to: str | None = None, docs: list[str] | None = None) -> None:
        self.actions.append({
            "case_id": case["id"], "action_type": kind, "action_at": iso_z(ist_datetime(d, hour, self.rng.choice([0, 15, 30, 45]))),
            "actor_id": None, "actor_label": actor, "actor_role": role, "bureau_code": bureau, "officer_id": officer,
            "remarks": remarks, "from_value": frm, "to_value": to, "next_action": None, "next_action_due": None,
            "doc_ids_json": dumps(docs or []), "is_synthetic": 1, "created_at": f"{d.isoformat()}T06:00:00Z",
        })

    # -- main ------------------------------------------------------------------
    def realise(self, ev: Event, case_id: str, *, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        rng, anchor, inst = self.rng, self.anchor, ev.inst
        rule = CAT[ev.category]
        o = overrides or {}
        bureau = o.get("bureau") or rule["default_bureau"]
        if "bureau" not in o and ev.category != "APPROVAL_RENEWAL" and rng.random() < 0.18:
            bureau = rng.choice(ALT_BUREAU[bureau])
        ref_flag = o.get("reference_flag")
        if ref_flag is None:
            x = rng.random()
            ref_flag = "COURT" if x < 0.03 else "VIP" if x < 0.05 else "PARLIAMENT" if x < 0.06 else "NONE"
            if ev.category == "APPROVAL_RENEWAL":
                ref_flag = "NONE"
        if ref_flag == "COURT" and "bureau" not in o and rng.random() < 0.5:
            bureau = "LC"
        if ev.category == "APPROVAL_RENEWAL":
            channel = "RB_PORTAL"
        elif bureau == "RO":
            channel = "REGIONAL_OFFICE"
        elif bureau in ("PGRC", "SDC"):
            channel = rng.choice(["PGRC_PORTAL", "PGRC_PORTAL", "CPGRAMS", "EMAIL"])
        elif bureau == "LC":
            channel = "POST"
        else:
            channel = rng.choice(["RB_PORTAL", "EMAIL", "POST", "CPGRAMS"])
        channel = o.get("channel", channel)
        received = ev.received
        sla = int(rule["sla_days"])
        due = received + timedelta(days=sla)

        # Texts
        if o.get("subject"):
            subject, desc = o["subject"], o["description"]
        elif ev.paraphrase_of is not None and ev.dup_of is not None:
            subject = ev.dup_subject or ""
            desc = texts.paraphrase(ev.paraphrase_of, rng)
        else:
            subject, desc, _slots = texts.make_complaint_text(ev.category, rng)
        # Complainants / evidence
        if "complainant_count" in o:
            ccount = o["complainant_count"]
        else:
            x = rng.random()
            mass = ev.category in ("FEE_FRAUD", "EXAMINATION", "VIOLENT_STRIKE", "SCHOLARSHIP")
            ccount = 1 if x < 0.68 else rng.randint(2, 5) if x < 0.84 else rng.randint(6, 30) if x < (0.95 if mass else 0.98) else rng.randint(31, 180)
            if ev.category == "APPROVAL_RENEWAL":
                ccount = 1
        evidence = o.get("evidence_count", 0 if (ev.category == "APPROVAL_RENEWAL" or rng.random() < 0.55) else rng.randint(1, 4))
        ctype = o.get("complainant_type") or ("OTHER" if ev.category == "APPROVAL_RENEWAL" else _pick(
            [("STUDENT", 60), ("PARENT", 20), ("FACULTY", 7), ("STAFF", 3), ("OTHER", 5), ("ANONYMOUS", 5)], rng))

        # Raw institution reference (often a variant spelling)
        raw_name = o.get("raw_name") or (inst.name if rng.random() < 0.62 else rng.choice(inst.variants))
        raw_pin = o.get("raw_pincode", inst.pincode if rng.random() < 0.45 else None)
        raw_addr = o.get("raw_address", f"{inst.district}, {inst.state}" if rng.random() < 0.6 else None)

        # Processing timeline
        transfers = o.get("transfers", 1 if rng.random() < 0.12 else 0)
        level = rule["severity_level"]
        median = 28.0 if ev.category == "APPROVAL_RENEWAL" else MEDIAN_DAYS[level]
        m = median * BUREAU_SPEED[bureau] * (1.35 if received.month in (7, 8, 9) else 1.0)
        m += 12 * transfers
        if ref_flag != "NONE":
            m *= 0.75
        if ccount > 20:
            m *= 1.15
        duration = max(1, int(round(m * math.exp(rng.gauss(0, 0.55)))))
        age = (anchor - received).days
        # Backlog: a share of recent cases is still open (realistic pending/overdue mix).
        stuck = rng.random() < (0.55 if age <= 365 else 0.3 if age <= 730 else 0.03)
        if "disposed_after" in o:
            duration, stuck = o["disposed_after"], False
        if o.get("open"):
            stuck = True
        disposed = (not stuck) and received + timedelta(days=duration) <= anchor
        # Where an open case is stuck: never picked up, awaiting the institution, or reply under review.
        stall = "none" if disposed else o.get("stall") or _pick(
            [("unacknowledged", 8), ("awaiting_reply", 45), ("reply_review", 47)], rng)

        officer0 = o.get("officer") or self.officer_for(bureau, inst.region)
        case: dict[str, Any] = {
            "id": case_id, "source_system": channel, "source_ref": o.get("source_ref") or self.source_ref(bureau, received, inst.region),
            "external_ref": o.get("external_ref") or (self.cpgrams_ref(received) if channel == "CPGRAMS" else None),
            "channel": channel, "institution_id": o.get("institution_id", inst.id), "institution_name_raw": raw_name,
            "institution_address_raw": raw_addr, "institution_pincode_raw": raw_pin,
            "permanent_id_raw": o.get("permanent_id_raw", inst.permanent_id if rng.random() < 0.2 else None),
            "match_status": o.get("match_status", "CONFIRMED"), "match_confidence": None,
            "category_code": ev.category, "subject": subject, "description": desc,
            "received_date": received.isoformat(), "bureau_code": bureau, "origin_bureau_code": bureau,
            "assigned_officer_id": None, "status": "RECEIVED", "escalation_level": 0, "transfer_count": 0,
            "complainant_count": ccount, "complainant_type": ctype, "evidence_count": evidence,
            "evidence_note": f"{evidence} item(s): synthetic metadata only (no files)" if evidence else None,
            "reference_flag": ref_flag,
            "reference_note": {"COURT": "Writ petition reference (synthetic)", "VIP": "VIP reference letter (synthetic)",
                               "PARLIAMENT": "Parliament question reference (synthetic)"}.get(ref_flag),
            "sla_days": sla, "expected_disposal_date": due.isoformat(), "disposed_date": None, "outcome": None,
            "outcome_remarks": None, "last_action_type": None, "last_action_at": None, "last_action_summary": None,
            "next_action": None, "next_action_due": None, "priority_score": None, "priority_band": None,
            "priority_computed_at": None, "priority_override_band": None, "priority_override_reason": None,
            "ml_category": None, "ml_confidence": None, "master_case_id": None,
            "region_code": o.get("region_code", inst.region), "state": o.get("state", inst.state),
            "is_synthetic": 1, "demo_tag": o.get("demo_tag"),
            "created_at": f"{received.isoformat()}T05:00:00Z", "updated_at": f"{received.isoformat()}T05:00:00Z",
            "created_by": "seed",
        }
        self.cases.append(case)
        start_actions = len(self.actions)

        intake_label = f"Intake – {CHANNELS[channel]}"
        ev_docs = [self.add_doc(case_id, "EVIDENCE", f"Evidence item {i + 1} (synthetic metadata)", None, received)
                   for i in range(evidence)]
        self.act(case, "CREATED", received, rng.randint(9, 10), actor=intake_label, role="SYSTEM", bureau=bureau,
                 remarks=f"Registered via {CHANNELS[channel]}.", docs=ev_docs)
        timeline_end = received + timedelta(days=duration) if disposed else anchor

        def until(days: int) -> date | None:
            d = received + timedelta(days=days)
            return d if d <= timeline_end and d <= anchor else None

        cur_bureau, cur_officer = bureau, None
        ack = until(rng.randint(0, 2))
        if ack and (disposed or o.get("acknowledged") or (age > 2 and stall != "unacknowledged")):
            self.act(case, "ACKNOWLEDGED", ack, 11, actor=f"{cur_bureau} desk", role="OFFICER", bureau=cur_bureau)
            asg = until((ack - received).days + rng.randint(0, 2))
            if asg:
                cur_officer = officer0
                self.act(case, "ASSIGNED", asg, 12, actor=f"{cur_bureau} section head", role="OFFICER",
                         bureau=cur_bureau, officer=cur_officer, to=cur_officer)
        span = max(duration, 2) if disposed else max(age, 2)
        transfer_day = int(span * rng.uniform(0.15, 0.4)) if transfers else None
        is_process = ev.category == "APPROVAL_RENEWAL"
        if cur_officer:
            if is_process:
                d1 = until(int(span * 0.35))
                if d1:
                    self.act(case, "SCRUTINY_COMPLETED", d1, 15, actor=cur_officer, role="OFFICER", bureau=cur_bureau,
                             officer=cur_officer, remarks="Scrutiny of compliance documents completed.")
                d2 = until(int(span * 0.6))
                if d2 and (disposed or rng.random() < 0.6):
                    kind = "RENEWAL_INITIATED" if ev.process == "EOA" else "INTAKE_INCREASE_PROPOSED"
                    self.act(case, kind, d2, 16, actor=cur_officer, role="OFFICER", bureau=cur_bureau,
                             officer=cur_officer, remarks="Processing initiated after scrutiny.")
            else:
                d1 = until(int(span * 0.25) + 1)
                if d1:
                    nref = self.notice_ref(cur_bureau, d1)
                    doc = self.add_doc(case_id, "NOTICE", "Notice to institution seeking response", nref, d1)
                    self.act(case, "NOTICE_ISSUED", d1, 15, actor=cur_officer, role="OFFICER", bureau=cur_bureau,
                             officer=cur_officer, remarks=f"Notice {nref} issued; response sought within 7 days.", docs=[doc])
                d2 = until(int(span * 0.55) + 2)
                if d2 and stall != "awaiting_reply":
                    doc = self.add_doc(case_id, "REPLY", "Institution's reply", None, d2)
                    self.act(case, "INSTITUTION_REPLY_RECEIVED", d2, 14, actor=f"{cur_bureau} desk", role="OFFICER",
                             bureau=cur_bureau, officer=cur_officer, remarks="Reply received from institution.", docs=[doc])
                if level >= 4:
                    d3 = until(int(span * 0.7) + 2)
                    if d3:
                        kind = "INSPECTION_ORDERED" if rng.random() < 0.5 else "HEARING_HELD"
                        self.act(case, kind, d3, 12, actor=cur_officer, role="OFFICER", bureau=cur_bureau, officer=cur_officer,
                                 remarks="Fact-finding by committee." if kind == "INSPECTION_ORDERED" else "Parties heard.")
            if transfers and transfer_day is not None:
                td = until(transfer_day)
                if td:
                    target = {"PGRC": "RB", "RB": "PGRC", "SDC": "PGRC", "AB": "RB", "LC": "PGRC", "RO": "PGRC"}[cur_bureau]
                    if ref_flag == "COURT" and cur_bureau != "LC":
                        target = "LC"
                    self.act(case, "TRANSFERRED", td, 13, actor=cur_officer, role="OFFICER", bureau=cur_bureau,
                             officer=cur_officer, frm=cur_bureau, to=target,
                             remarks=f"Subject matter falls under {target}; transferred for disposal.")
                    case["transfer_count"] += 1
                    cur_bureau = target
                    cur_officer = None
                    acc = until(transfer_day + rng.randint(1, 4))
                    if acc and (disposed or rng.random() < 0.7):
                        cur_officer = self.officer_for(cur_bureau, inst.region)
                        self.act(case, "ASSIGNED", acc, 11, actor=f"{cur_bureau} section head", role="OFFICER",
                                 bureau=cur_bureau, officer=cur_officer, to=cur_officer)
        # Escalation (historic or current)
        overdue_by = ((received + timedelta(days=duration)) - due).days if disposed else (anchor - due).days
        escalated_now = False
        if overdue_by > max(3 * sla, 45) and ((level >= 4 and rng.random() < 0.55) or rng.random() < 0.15):
            ed = due + timedelta(days=rng.randint(7, max(8, min(overdue_by - 1, 30))))
            if ed <= timeline_end and ed <= anchor:
                self.act(case, "ESCALATED", ed, 17, actor=cur_officer or f"{cur_bureau} desk", role="OFFICER",
                         bureau=cur_bureau, frm=cur_bureau, to="COMPETENT_AUTHORITY",
                         remarks=f"Overdue by {(ed - due).days} days; escalated for review.")
                case["escalation_level"] = 1
                escalated_now = not disposed
                if disposed:
                    dd = ed + timedelta(days=rng.randint(2, 6))
                    if dd <= timeline_end:
                        self.act(case, "DEESCALATED", dd, 11, actor="Competent Authority (synthetic)", role="COMPETENT_AUTHORITY",
                                 bureau=None, remarks="Reviewed; time-bound disposal directed.")
        case["bureau_code"] = cur_bureau
        case["assigned_officer_id"] = cur_officer

        if disposed:
            end = received + timedelta(days=duration)
            outcome = o.get("outcome") or self._outcome(ev, inst)
            remarks = {
                "SUBSTANTIATED": "Complaint substantiated; institution directed to take corrective action and report compliance.",
                "PARTIALLY_SUBSTANTIATED": "Partly substantiated; directions issued on the substantiated points.",
                "UNSUBSTANTIATED": "Allegations not substantiated on the record; case closed.",
                "WITHDRAWN": "Complainant withdrew the complaint.",
                "NOT_MAINTAINABLE": "Not maintainable / outside AICTE purview; complainant informed.",
                "PROCESS_COMPLETED": "Regulatory process completed.",
            }[outcome]
            if is_process:
                kind = "EXTENSION_OF_APPROVAL" if ev.process == "EOA" else "INTAKE_INCREASE_APPROVED"
                self.act(case, kind, end, 16, actor=cur_officer or "RB desk", role="OFFICER", bureau=cur_bureau,
                         officer=cur_officer, remarks="Approval decision issued.")
            self.act(case, "DISPOSED", end, 17, actor=cur_officer or f"{cur_bureau} desk", role="OFFICER",
                     bureau=cur_bureau, officer=cur_officer, to=outcome, remarks=remarks)
            case.update({"status": "DISPOSED", "disposed_date": end.isoformat(), "outcome": outcome,
                         "outcome_remarks": remarks})
        else:
            last_types = [a["action_type"] for a in self.actions[start_actions:]]
            if o.get("status"):
                status = o["status"]
            elif age <= 2 or "ACKNOWLEDGED" not in last_types:
                status = "RECEIVED"
            elif "TRANSFERRED" in last_types and cur_officer is None:
                status = "TRANSFERRED"
            elif escalated_now:
                status = "ESCALATED"
            elif "INSTITUTION_REPLY_RECEIVED" in last_types or is_process:
                status = "UNDER_PROCESS"
            else:
                status = "PENDING" if rng.random() < 0.6 else "UNDER_PROCESS"
            case["status"] = status
            case["next_action"], nad = self._next_action(status, last_types, anchor, due)
            case["next_action_due"] = nad.isoformat() if nad else None
        mine = self.actions[start_actions:]
        mine.sort(key=lambda a: a["action_at"])
        self.actions[start_actions:] = mine
        last = mine[-1]
        case["last_action_type"] = last["action_type"]
        case["last_action_at"] = last["action_at"]
        case["last_action_summary"] = ACTION_TYPES.get(last["action_type"], last["action_type"]) + (
            f": {last['remarks']}" if last.get("remarks") else "")
        case["updated_at"] = last["action_at"]
        return case

    def _outcome(self, ev: Event, inst: Inst) -> str:
        if ev.category == "APPROVAL_RENEWAL":
            return "PROCESS_COMPLETED"
        p_sub = min(0.6, max(0.12, 0.24 + 0.14 * (inst.risk - 1)))
        if ev.category == "GENERAL_ENQUIRY":
            return _pick([("NOT_MAINTAINABLE", 50), ("UNSUBSTANTIATED", 30), ("WITHDRAWN", 20)], self.rng)
        return _pick([("SUBSTANTIATED", p_sub * 100), ("PARTIALLY_SUBSTANTIATED", 15),
                      ("UNSUBSTANTIATED", (0.73 - p_sub) * 100), ("WITHDRAWN", 7), ("NOT_MAINTAINABLE", 5)], self.rng)

    @staticmethod
    def _next_action(status: str, last_types: list[str], anchor: date, due: date) -> tuple[str, date | None]:
        if status == "RECEIVED":
            return "Acknowledge and assign an officer", anchor + timedelta(days=2)
        if status == "TRANSFERRED":
            return "Receiving Bureau/Cell to accept transfer and assign officer", anchor + timedelta(days=3)
        if status == "ESCALATED":
            return "Competent Authority to review escalation", anchor + timedelta(days=7)
        if "INSTITUTION_REPLY_RECEIVED" in last_types:
            return "Review institution reply and decide", max(due, anchor + timedelta(days=1))
        if "NOTICE_ISSUED" in last_types:
            return "Await institution reply; follow up", max(due, anchor + timedelta(days=2))
        if "RENEWAL_INITIATED" in last_types or "INTAKE_INCREASE_PROPOSED" in last_types:
            return "Approval decision", max(due, anchor + timedelta(days=5))
        return "Issue notice to institution", anchor + timedelta(days=3)


# ----------------------------------------------------------------------------- orchestration
# Bulk case numbers per originating Bureau/Cell. Hand-seeded demo IDs (RB-2291, PGRC-5530, ...)
# sit in ranges the bulk sequences never reach, so IDs stay stable for every seed.
CASE_NUMBER_START = {"RB": 1001, "PGRC": 6001, "AB": 8001, "SDC": 7001, "LC": 8501, "RO": 9001}


def _wipe(db) -> None:
    tables = [
        "import_row_issues", "import_jobs", "public_signals", "alerts", "priority_overrides", "case_links",
        "overlap_alert_cases", "overlap_alerts", "match_reviews", "case_documents", "case_actions",
        "master_case_members", "complaints", "master_cases", "match_feedback", "institution_aliases",
        "institutions", "trusts", "demo_users", "officers", "category_rules", "app_settings", "states",
        "regions", "bureaus", "id_counters", "seed_runs", "audit_events",
    ]
    for t in tables:
        db.run(f"DELETE FROM {t}")
    db.run("DELETE FROM sqlite_sequence WHERE name IN ('audit_events','case_actions','institution_aliases',"
           "'match_feedback','priority_overrides','import_row_issues','master_case_members','seed_runs')")


def fingerprint(db) -> str:
    """Hash of the deterministic core dataset (used to prove reproducibility)."""
    parts = {
        "institutions": db.all("SELECT id, permanent_id, name, state, district, pincode, intake_total, trust_id "
                               "FROM institutions ORDER BY id"),
        "aliases": db.all("SELECT institution_id, alias, alias_type FROM institution_aliases ORDER BY institution_id, alias"),
        "trusts": db.all("SELECT id, name FROM trusts ORDER BY id"),
        "complaints": db.all(
            "SELECT id, source_ref, external_ref, institution_id, institution_name_raw, category_code, received_date, "
            "bureau_code, origin_bureau_code, assigned_officer_id, status, disposed_date, outcome, complainant_count, "
            "evidence_count, reference_flag, description FROM complaints WHERE created_by = 'seed' ORDER BY id"),
        "actions": db.all("SELECT a.case_id, a.action_type, a.action_at, a.from_value, a.to_value FROM case_actions a "
                          "JOIN complaints c ON c.id = a.case_id WHERE a.is_synthetic = 1 ORDER BY a.case_id, a.action_at, a.id"),
    }
    return sha256_hex(canonical_json(parts))


def generate(db, *, seed: int, anchor: date, reset: bool = False) -> dict[str, Any]:
    """Create the full synthetic dataset. Returns a summary dict (idempotent)."""
    existing = db.one("SELECT * FROM seed_runs ORDER BY id DESC LIMIT 1")
    if existing and not reset:
        return {"skipped": True, "seed": existing["seed"], "anchor": existing["anchor_date"],
                "fingerprint": existing["fingerprint"], "counts": existing["counts_json"]}
    from . import demo_story  # local import to avoid a cycle

    rng = random.Random(seed)
    with db.tx():
        if reset or existing:
            _wipe(db)
        now_fixed = f"{anchor.isoformat()}T04:30:00Z"
        seed_reference(db, now_fixed)
        seed_rules(db, now_fixed)
        for tid, name, state in TRUSTS:
            db.insert("trusts", {
                "id": tid, "name": name, "registration_ref": f"SYN-SOC-{tid[-2:]}-{rng.randint(1000, 9999)}",
                "state": state, "provenance": "SYNTHETIC — generated relationship, not a real trust/society",
                "is_synthetic": 1, "notes": None, "created_at": now_fixed,
            })
        insts = build_institutions(rng)
        for inst in insts:
            db.insert("institutions", {
                "id": inst.id, "permanent_id": inst.permanent_id, "name": inst.name, "name_norm": normalize_name(inst.name),
                "institution_type": inst.itype, "address_line": inst.address, "city": inst.district,
                "district": inst.district, "state": inst.state, "region_code": inst.region, "pincode": inst.pincode,
                "established_year": inst.established, "intake_total": inst.intake, "intake_source": "SYNTHETIC",
                "courses_json": dumps(inst.courses), "trust_id": inst.trust_id,
                "trust_relation_source": "SYNTHETIC" if inst.trust_id else None, "status": "ACTIVE", "is_synthetic": 1,
                "provenance_json": dumps({"source": "synthetic generator", "generator_version": GENERATOR_VERSION,
                                          "seed": seed}),
                "demo_tag": inst.demo_tag, "created_at": now_fixed, "updated_at": now_fixed,
            })
            for alias, kind in inst.aliases:
                db.run("INSERT OR IGNORE INTO institution_aliases(institution_id, alias, alias_norm, alias_type, source, "
                       "created_by, created_at) VALUES (?,?,?,?,?,?,?)",
                       (inst.id, alias, normalize_name(alias), kind, "SEED", "seed", now_fixed))

        builder = Builder(anchor, rng)
        story = demo_story.build(builder, {i.id: i for i in insts}, anchor)
        n_demo = len(story["case_ids"])

        process_events = approval_events(insts, anchor, rng)
        n_dups = 30
        target_complaints = TARGET_CASES - n_demo - len(process_events) - n_dups
        base_rate = 2.6
        events = generate_events(insts, anchor, rng, base_rate)
        while len(events) < target_complaints:
            base_rate *= 1.15
            events = generate_events(insts, anchor, rng, base_rate)
        protected = [e for e in events if e.protected]
        others = [e for e in events if not e.protected]
        keep = rng.sample(range(len(others)), k=target_complaints - len(protected))
        events = protected + [others[i] for i in sorted(keep)]
        events.sort(key=lambda e: (e.received, e.inst.id, e.category))
        # Near-duplicates: the same grievance filed again (same or different Bureau/Cell).
        candidates = [e for e in events if e.received <= anchor - timedelta(days=3)]
        dup_sources = rng.sample(candidates, k=n_dups)
        all_events = events + process_events
        dups: list[Event] = []
        for src in dup_sources:
            gap = rng.randint(1, 25) if rng.random() < 0.75 else rng.randint(30, 110)
            d = min(anchor, src.received + timedelta(days=gap))
            dups.append(Event(inst=src.inst, category=src.category, received=d, dup_of=src,
                              shared_external=rng.random() < 0.4))
        all_events += dups
        all_events.sort(key=lambda e: (e.received, e.inst.id, e.category, e.dup_of is not None))

        counters = dict(CASE_NUMBER_START)
        realised: dict[int, dict[str, Any]] = {}
        for ev in all_events:
            overrides: dict[str, Any] = {}
            if ev.dup_of is not None:
                src_case = realised[id(ev.dup_of)]
                ev.paraphrase_of = src_case["description"]
                ev.dup_subject = src_case["subject"]
                if rng.random() < 0.5:
                    overrides["bureau"] = src_case["origin_bureau_code"]
                if ev.shared_external and src_case.get("external_ref"):
                    overrides["external_ref"] = src_case["external_ref"]
                    overrides["channel"] = "CPGRAMS"
            if ev.process in ("EOA", "INTAKE"):
                overrides["bureau"] = "RB"
            a0, d0 = len(builder.actions), len(builder.docs)
            temp_id = f"TMP-{len(realised):05d}"
            case = builder.realise(ev, temp_id, overrides=overrides)
            origin = case["origin_bureau_code"]
            case_id = f"{origin}-{counters[origin]}"
            counters[origin] += 1
            for row in builder.actions[a0:]:
                row["case_id"] = case_id
            for row in builder.docs[d0:]:
                row["case_id"] = case_id
            case["id"] = case_id
            realised[id(ev)] = case

        db.insert_many("complaints", builder.cases)
        db.insert_many("case_actions", builder.actions)
        db.insert_many("case_documents", builder.docs)
        for bureau, nxt in counters.items():
            bump_counter(db, f"case:{bureau}", nxt)
        for cid in story["case_ids"]:
            b, n = cid.split("-", 1)
            bump_counter(db, f"case:{b}", int(n) + 1)
        bump_counter(db, "doc", builder.doc_seq + 1)
        demo_story.insert_signals(db, anchor)

        counts = {
            "institutions": db.val("SELECT COUNT(*) FROM institutions"),
            "trusts": db.val("SELECT COUNT(*) FROM trusts"),
            "complaints": db.val("SELECT COUNT(*) FROM complaints"),
            "case_actions": db.val("SELECT COUNT(*) FROM case_actions"),
            "documents": db.val("SELECT COUNT(*) FROM case_documents"),
            "aliases": db.val("SELECT COUNT(*) FROM institution_aliases"),
            "public_signals": db.val("SELECT COUNT(*) FROM public_signals"),
        }
        fp = fingerprint(db)
        db.insert("seed_runs", {"seed": seed, "anchor_date": anchor.isoformat(), "generator_version": GENERATOR_VERSION,
                                "counts_json": dumps(counts), "fingerprint": fp, "created_at": now_fixed})
    return {"skipped": False, "seed": seed, "anchor": anchor.isoformat(), "fingerprint": fp, "counts": counts,
            "demo": story}
