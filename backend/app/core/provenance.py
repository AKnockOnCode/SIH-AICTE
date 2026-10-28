"""Which kind of data an instance holds, and the matching disclaimer for screens, exports and dossiers."""

from __future__ import annotations

from .constants import MIXED_DISCLAIMER, SYNTHETIC_DISCLAIMER


def data_mode(db) -> str:
    """SYNTHETIC while every complaint is seeded; MIXED once any entered or imported complaint exists."""
    real = db.val("SELECT COUNT(*) FROM complaints WHERE is_synthetic = 0", default=0)
    return "SYNTHETIC" if real == 0 else "MIXED"


def data_disclaimer(db) -> str:
    return SYNTHETIC_DISCLAIMER if data_mode(db) == "SYNTHETIC" else MIXED_DISCLAIMER
