"""Small shared helpers: canonical JSON, hashing, ID allocation, safe names."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any


def canonical_json(value: Any) -> str:
    """Deterministic JSON used for hashing (sorted keys, no whitespace, UTF-8)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(text: str | None, default: Any = None) -> Any:
    if text is None or text == "":
        return default
    return json.loads(text)


def next_id(db, counter: str, prefix: str, width: int = 4, start: int = 1) -> str:
    """Allocate the next sequential ID for `counter` (must be called inside a transaction)."""
    row = db.one("SELECT value FROM id_counters WHERE name = ?", (counter,))
    value = start if row is None else int(row["value"])
    if row is None:
        db.run("INSERT INTO id_counters(name, value) VALUES (?, ?)", (counter, value + 1))
    else:
        db.run("UPDATE id_counters SET value = ? WHERE name = ?", (value + 1, counter))
    return f"{prefix}{value:0{width}d}"


def bump_counter(db, counter: str, at_least: int) -> None:
    """Ensure the counter will hand out numbers >= at_least (used after seeding fixed IDs)."""
    row = db.one("SELECT value FROM id_counters WHERE name = ?", (counter,))
    if row is None:
        db.run("INSERT INTO id_counters(name, value) VALUES (?, ?)", (counter, at_least))
    elif int(row["value"]) < at_least:
        db.run("UPDATE id_counters SET value = ? WHERE name = ?", (at_least, counter))


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str, default: str = "file") -> str:
    """Strip directories and unsafe characters so a name can never escape a folder."""
    base = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    base = base.replace("\\", "/").split("/")[-1]
    base = _SAFE.sub("_", base).strip("._")
    return (base or default)[:120]


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
