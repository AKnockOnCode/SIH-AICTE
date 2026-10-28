"""Institution-name canonicalisation used by matching, search and seeding.

Steps: Unicode fold -> lower-case -> '&' to 'and' -> strip punctuation -> expand common
abbreviations (Engg., Inst., Tech., Mgmt. ...) -> drop stop-words, campus words and
location words (state/district names) -> collapse whitespace. Location is compared
separately as an address signal, so "SIET, Bhopal" and "SIET" share one canonical form.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

ABBREVIATIONS = {
    "inst": "institute", "instt": "institute", "insti": "institute", "institue": "institute",
    "engg": "engineering", "engr": "engineering", "engin": "engineering", "eng": "engineering",
    "tech": "technology", "techn": "technology", "technol": "technology",
    "coll": "college", "clg": "college", "colg": "college",
    "mgmt": "management", "mgt": "management", "mngt": "management",
    "univ": "university", "pharm": "pharmacy", "phar": "pharmacy",
    "sci": "science", "scs": "sciences", "res": "research", "polytech": "polytechnic",
    "poly": "polytechnic", "comp": "computer", "appl": "applications", "arch": "architecture",
    "edu": "education", "educ": "education", "soc": "society", "estd": "established",
}
STOPWORDS = {"of", "the", "and", "for", "in", "at", "an", "a", "to"}
CAMPUS_WORDS = {"campus", "main", "branch", "unit", "off", "city", "new", "old"}


def _location_words() -> set[str]:
    from ..seed.reference import STATES

    words: set[str] = set()
    for state, (_region, districts) in STATES.items():
        words.update(state.lower().split())
        for district, _pin in districts:
            words.update(district.lower().split())
    # Keep generic words that also occur inside institution names.
    return words - {"new", "north", "nagar", "urban", "pradesh", "metropolitan", "east", "west", "south"}


_LOCATIONS: set[str] | None = None


def location_words() -> set[str]:
    global _LOCATIONS
    if _LOCATIONS is None:
        _LOCATIONS = _location_words()
    return _LOCATIONS


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=20000)
def canonical_tokens(text: str) -> tuple[str, ...]:
    tokens = []
    for tok in fold(text).split():
        tok = ABBREVIATIONS.get(tok, tok)
        if tok in STOPWORDS or tok in CAMPUS_WORDS:
            continue
        tokens.append(tok)
    locs = location_words()
    stripped = [t for t in tokens if t not in locs]
    return tuple(stripped or tokens)


def normalize_name(text: str) -> str:
    return " ".join(canonical_tokens(text))


def acronym(text: str) -> str:
    """Initials of canonical tokens: 'Sankalp Institute of Engg & Tech' -> 'siet'."""
    return "".join(t[0] for t in canonical_tokens(text) if t)


def compact(text: str) -> str:
    """Letters and digits only (catches 'S.I.E.T' -> 'siet')."""
    return re.sub(r"[^a-z0-9]", "", fold(text))


def normalize_pincode(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits if len(digits) == 6 else None


def normalize_permanent_id(value: str | None) -> str | None:
    if not value:
        return None
    v = re.sub(r"\s+", "", str(value)).upper()
    return v or None
