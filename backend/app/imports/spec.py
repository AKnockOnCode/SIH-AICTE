"""Import data dictionary and value parsers (institutions, complaints, public signals)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from ..core.constants import OUTCOME_LABELS, STATUS_LABELS

FIELDS: dict[str, list[dict[str, Any]]] = {
    "INSTITUTIONS": [
        {"key": "name", "label": "Institution name", "required": True, "type": "text",
         "synonyms": ["institution", "institution name", "college", "college name", "name of institution", "institute", "name"],
         "description": "Official name as in the source."},
        {"key": "permanent_id", "label": "AICTE Permanent ID", "required": False, "type": "text",
         "synonyms": ["aicte id", "permanent id", "aicte permanent id", "pid", "institute id", "aicte permanent id no"],
         "description": "Exact identifier; used for exact matching and updates."},
        {"key": "state", "label": "State", "required": True, "type": "state", "synonyms": ["state", "state name", "state/ut"],
         "description": "State/UT name or common code (e.g. MH, MP)."},
        {"key": "district", "label": "District / city", "required": False, "type": "text", "synonyms": ["district", "city", "town"]},
        {"key": "address", "label": "Address", "required": False, "type": "text", "synonyms": ["address", "full address"]},
        {"key": "pincode", "label": "Pincode", "required": False, "type": "pincode", "synonyms": ["pin", "pincode", "pin code", "postal code"]},
        {"key": "institution_type", "label": "Institution type", "required": False, "type": "text",
         "synonyms": ["type", "institution type", "program", "programme"]},
        {"key": "established_year", "label": "Year established", "required": False, "type": "year",
         "synonyms": ["established", "year of establishment", "estd", "established year"]},
        {"key": "intake_total", "label": "Total intake", "required": False, "type": "int",
         "synonyms": ["intake", "total intake", "sanctioned intake", "approved intake"]},
        {"key": "courses", "label": "Courses (separate with ;)", "required": False, "type": "list",
         "synonyms": ["courses", "programmes", "programs"]},
        {"key": "trust_name", "label": "Trust / society", "required": False, "type": "text",
         "synonyms": ["trust", "society", "trust/society", "management", "trust name"]},
        {"key": "aliases", "label": "Other names (separate with ;)", "required": False, "type": "list",
         "synonyms": ["aliases", "other names", "former name", "also known as"]},
        {"key": "source_note", "label": "Source / provenance note", "required": False, "type": "text",
         "synonyms": ["source", "source url", "provenance"]},
    ],
    "COMPLAINTS": [
        {"key": "source_case_id", "label": "Source complaint/case ID", "required": False, "type": "text",
         "synonyms": ["complaint id", "case id", "complaint no", "registration no", "file no", "reference no", "complaint number"],
         "description": "Preserved as the source identifier; an internal AgniDrishti ID is always generated."},
        {"key": "institution_name", "label": "Institution name", "required": False, "type": "text",
         "synonyms": ["institution", "college", "college name", "institution name", "name of institution", "institute"],
         "description": "Required unless a Permanent ID is given. Matched to the Institution Master."},
        {"key": "permanent_id", "label": "AICTE Permanent ID", "required": False, "type": "text",
         "synonyms": ["aicte id", "permanent id", "aicte permanent id", "institute id"]},
        {"key": "institution_state", "label": "Institution state", "required": False, "type": "state", "synonyms": ["state"]},
        {"key": "institution_district", "label": "Institution district / city", "required": False, "type": "text",
         "synonyms": ["district", "city"]},
        {"key": "institution_pincode", "label": "Institution pincode", "required": False, "type": "pincode",
         "synonyms": ["pincode", "pin", "pin code"]},
        {"key": "category", "label": "Category / nature", "required": True, "type": "category",
         "synonyms": ["category", "nature", "nature of complaint", "complaint type", "type", "complaint category"]},
        {"key": "received_date", "label": "Date of receipt", "required": True, "type": "date",
         "synonyms": ["date of receipt", "received", "received date", "date", "receipt date", "received on"]},
        {"key": "bureau", "label": "Bureau / Cell", "required": True, "type": "bureau",
         "synonyms": ["bureau", "cell", "bureau/cell", "handled by", "section", "bureau / cell"]},
        {"key": "status", "label": "Status", "required": False, "type": "status", "synonyms": ["status", "current status"]},
        {"key": "subject", "label": "Subject", "required": False, "type": "text", "synonyms": ["subject", "title", "brief"]},
        {"key": "description", "label": "Description", "required": False, "type": "text",
         "synonyms": ["description", "details", "complaint details", "complaint text", "grievance", "grievance details"]},
        {"key": "assigned_officer", "label": "Assigned officer (ID or designation)", "required": False, "type": "officer",
         "synonyms": ["officer", "assigned officer", "dealing officer", "dealing hand"]},
        {"key": "complainant_count", "label": "Number of complainants", "required": False, "type": "int",
         "synonyms": ["complainants", "no of complainants", "number of complainants", "complainant count"]},
        {"key": "evidence", "label": "Evidence attached (yes/no or count)", "required": False, "type": "evidence",
         "synonyms": ["evidence", "documents attached", "attachments", "evidence attached"]},
        {"key": "reference_flag", "label": "Court/VIP/Parliament reference", "required": False, "type": "reference",
         "synonyms": ["reference", "court/vip", "vip reference", "court reference", "reference flag"]},
        {"key": "disposed_date", "label": "Date of disposal", "required": False, "type": "date",
         "synonyms": ["disposed on", "disposal date", "date of disposal", "disposed date"]},
        {"key": "outcome", "label": "Outcome", "required": False, "type": "outcome", "synonyms": ["outcome", "result", "decision"]},
        {"key": "external_ref", "label": "External reference (e.g. CPGRAMS no.)", "required": False, "type": "text",
         "synonyms": ["cpgrams no", "cpgrams", "external ref", "grievance no", "external reference"]},
    ],
    "PUBLIC_SIGNALS": [
        {"key": "title", "label": "Title", "required": True, "type": "text", "synonyms": ["title", "headline"]},
        {"key": "publisher", "label": "Publisher / agency", "required": True, "type": "text",
         "synonyms": ["publisher", "agency", "source", "source name"]},
        {"key": "source_url", "label": "Source URL", "required": True, "type": "url", "synonyms": ["url", "link", "source url"]},
        {"key": "published_date", "label": "Published date", "required": False, "type": "date",
         "synonyms": ["published", "published date", "date"]},
        {"key": "summary", "label": "Short factual summary (own words)", "required": True, "type": "text",
         "synonyms": ["summary", "description"]},
        {"key": "signal_type", "label": "Type (OFFICIAL_NOTICE or NEWS_REPORT)", "required": False, "type": "signal_type",
         "synonyms": ["type", "signal type"]},
        {"key": "institution_text", "label": "Institution named in the source", "required": False, "type": "text",
         "synonyms": ["institution", "institution name", "college"]},
    ],
}

STATE_CODES = {
    "MH": "Maharashtra", "MP": "Madhya Pradesh", "UP": "Uttar Pradesh", "TN": "Tamil Nadu", "KA": "Karnataka", "TS": "Telangana",
    "TG": "Telangana", "AP": "Andhra Pradesh", "DL": "Delhi", "HR": "Haryana", "PB": "Punjab", "RJ": "Rajasthan", "GJ": "Gujarat",
    "WB": "West Bengal", "OD": "Odisha", "OR": "Odisha", "BR": "Bihar", "JH": "Jharkhand", "AS": "Assam", "KL": "Kerala", "GA": "Goa",
    "CG": "Chhattisgarh", "CT": "Chhattisgarh", "UK": "Uttarakhand", "UT": "Uttarakhand", "HP": "Himachal Pradesh",
    "ML": "Meghalaya", "PY": "Puducherry",
}
CATEGORY_SYNONYMS = {
    "ragging": "RAGGING", "sexual harassment": "SEXUAL_HARASSMENT", "harassment": "SEXUAL_HARASSMENT", "crime": "CAMPUS_CRIME",
    "campus crime": "CAMPUS_CRIME", "violence": "CAMPUS_CRIME", "strike": "VIOLENT_STRIKE", "violent strike": "VIOLENT_STRIKE",
    "unapproved": "FAKE_UNAPPROVED", "fake": "FAKE_UNAPPROVED", "unapproved course": "FAKE_UNAPPROVED",
    "infrastructure": "REGULATORY_NONCOMPLIANCE", "faculty": "REGULATORY_NONCOMPLIANCE", "non-compliance": "REGULATORY_NONCOMPLIANCE",
    "regulatory": "REGULATORY_NONCOMPLIANCE", "fee": "FEE_FRAUD", "fees": "FEE_FRAUD", "excess fee": "FEE_FRAUD",
    "fee refund": "FEE_FRAUD", "capitation": "FEE_FRAUD", "certificates": "WITHHELD_CERTIFICATES", "certificate": "WITHHELD_CERTIFICATES",
    "documents withheld": "WITHHELD_CERTIFICATES", "scholarship": "SCHOLARSHIP", "exam": "EXAMINATION", "examination": "EXAMINATION",
    "result": "EXAMINATION", "results": "EXAMINATION", "approval": "APPROVAL_RENEWAL", "renewal": "APPROVAL_RENEWAL",
    "general": "GENERAL_ENQUIRY", "other": "GENERAL_ENQUIRY", "enquiry": "GENERAL_ENQUIRY", "others": "GENERAL_ENQUIRY",
}
BUREAU_SYNONYMS = {"regulation bureau": "RB", "regulation": "RB", "public grievance redressal cell": "PGRC", "grievance cell": "PGRC",
                   "pgrc cell": "PGRC", "approval bureau": "AB", "student development cell": "SDC", "legal cell": "LC",
                   "regional office": "RO", "regional offices": "RO", "ro": "RO"}
STATUS_SYNONYMS = {"new": "RECEIVED", "received": "RECEIVED", "pending": "PENDING", "in process": "UNDER_PROCESS",
                   "under process": "UNDER_PROCESS", "processing": "UNDER_PROCESS", "transferred": "TRANSFERRED",
                   "escalated": "ESCALATED", "disposed": "DISPOSED", "closed": "DISPOSED", "disposed off": "DISPOSED"}
OUTCOME_SYNONYMS = {"substantiated": "SUBSTANTIATED", "partly substantiated": "PARTIALLY_SUBSTANTIATED",
                    "partially substantiated": "PARTIALLY_SUBSTANTIATED", "not substantiated": "UNSUBSTANTIATED",
                    "unsubstantiated": "UNSUBSTANTIATED", "rejected": "UNSUBSTANTIATED", "withdrawn": "WITHDRAWN",
                    "not maintainable": "NOT_MAINTAINABLE", "process completed": "PROCESS_COMPLETED"}
DATE_FORMATS = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%Y/%m/%d", "%d-%m-%y",
                "%d/%m/%y"]


class ParseError(ValueError):
    pass


def norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, float) and v != v)


def parse_value(ftype: str, raw: Any, ctx: dict[str, Any]) -> Any:
    """Parse one cell. Raises ParseError with a human-readable reason."""
    if is_blank(raw):
        return None
    if ftype == "text":
        return str(raw).strip()[:5000]
    if ftype in ("int", "year"):
        try:
            v = int(float(str(raw).replace(",", "").strip()))
        except ValueError:
            raise ParseError(f"'{raw}' is not a whole number") from None
        if ftype == "year" and not (1850 <= v <= date.today().year):
            raise ParseError(f"year {v} out of range")
        if v < 0:
            raise ParseError("must not be negative")
        return v
    if ftype == "date":
        if isinstance(raw, datetime):
            d = raw.date()
        elif isinstance(raw, date):
            d = raw
        else:
            text = str(raw).strip()
            d = None
            for fmt in DATE_FORMATS:
                try:
                    d = datetime.strptime(text, fmt).date()
                    break
                except ValueError:
                    continue
            if d is None:
                raise ParseError(f"'{raw}' is not a recognised date (use DD-MM-YYYY or YYYY-MM-DD)")
        if d < date(2000, 1, 1) or d > ctx["today"]:
            raise ParseError(f"date {d.isoformat()} is outside 2000-01-01..today")
        return d
    if ftype == "state":
        text = str(raw).strip()
        code = STATE_CODES.get(text.upper())
        for s in ctx["states"]:
            if s.lower() == text.lower() or s == code:
                return s
        raise ParseError(f"unknown state '{raw}'")
    if ftype == "pincode":
        digits = re.sub(r"\D", "", str(raw).split(".")[0])
        if len(digits) != 6:
            raise ParseError(f"pincode '{raw}' is not 6 digits")
        return digits
    if ftype == "list":
        return [p.strip() for p in re.split(r"[;|]", str(raw)) if p.strip()]
    if ftype == "category":
        n = norm(raw)
        for code, label in ctx["categories"].items():
            if n in (norm(code), norm(label)):
                return code
        if n in CATEGORY_SYNONYMS:
            return CATEGORY_SYNONYMS[n]
        raise ParseError(f"unknown category '{raw}' (use a code such as FEE_FRAUD or a label such as 'Fee fraud / excess fee')")
    if ftype == "bureau":
        n = norm(raw)
        for code, name in ctx["bureaus"].items():
            if n in (norm(code), norm(name)):
                return code
        if n in BUREAU_SYNONYMS:
            return BUREAU_SYNONYMS[n]
        raise ParseError(f"unknown Bureau/Cell '{raw}' (use one of {', '.join(ctx['bureaus'])})")
    if ftype == "status":
        n = norm(raw)
        for code, label in STATUS_LABELS.items():
            if n in (norm(code), norm(label)):
                return code
        if n in STATUS_SYNONYMS:
            return STATUS_SYNONYMS[n]
        raise ParseError(f"unknown status '{raw}'")
    if ftype == "outcome":
        n = norm(raw)
        for code, label in OUTCOME_LABELS.items():
            if n in (norm(code), norm(label)):
                return code
        if n in OUTCOME_SYNONYMS:
            return OUTCOME_SYNONYMS[n]
        raise ParseError(f"unknown outcome '{raw}'")
    if ftype == "evidence":
        n = norm(raw)
        if n in ("yes", "y", "true", "attached"):
            return 1
        if n in ("no", "n", "false", "none", "nil"):
            return 0
        try:
            return max(0, int(float(n)))
        except ValueError:
            raise ParseError(f"evidence must be yes/no or a count, got '{raw}'") from None
    if ftype == "reference":
        n = norm(raw).upper()
        if n in ("", "NONE", "NO", "NIL"):
            return "NONE"
        for flag in ("COURT", "VIP", "PARLIAMENT"):
            if flag in n:
                return flag
        raise ParseError(f"reference must be NONE, COURT, VIP or PARLIAMENT, got '{raw}'")
    if ftype == "officer":
        text = str(raw).strip()
        for oid, info in ctx["officers"].items():
            if text.upper() == oid or norm(text) == norm(info["display_name"]):
                return oid
        raise ParseError(f"unknown officer '{raw}' (use an officer ID such as OFF-PGRC-03)")
    if ftype == "url":
        text = str(raw).strip()
        if not re.match(r"^https?://[^\s]+$", text):
            raise ParseError("must be an http(s) URL")
        return text
    if ftype == "signal_type":
        n = norm(raw).upper().replace(" ", "_")
        if n in ("OFFICIAL_NOTICE", "NEWS_REPORT"):
            return n
        raise ParseError("type must be OFFICIAL_NOTICE or NEWS_REPORT")
    raise ParseError(f"unsupported field type {ftype}")


def suggest_mapping(kind: str, columns: list[str]) -> dict[str, str]:
    from ..institutions.fuzzy import ratio

    mapping: dict[str, str] = {}
    used: set[str] = set()
    ncols = {c: norm(c) for c in columns}
    for f in FIELDS[kind]:
        cands = {norm(f["key"]), norm(f["label"]), *[norm(s) for s in f["synonyms"]]}
        exact = next((c for c, n in ncols.items() if n in cands and c not in used), None)
        if exact:
            mapping[f["key"]] = exact
            used.add(exact)
    for f in FIELDS[kind]:
        if f["key"] in mapping:
            continue
        cands = {norm(f["label"]), *[norm(s) for s in f["synonyms"]]}
        best, score = None, 0.0
        for c, n in ncols.items():
            if c in used:
                continue
            s = max(ratio(n, x) for x in cands)
            if s > score:
                best, score = c, s
        if best and score >= 82:
            mapping[f["key"]] = best
            used.add(best)
    return mapping
