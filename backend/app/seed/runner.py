"""Seed orchestration: generate core data, then run the engines over it (post-process)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from ..audit import chain
from ..core import clock
from ..core.config import get_settings
from ..core.security import SYSTEM_USER
from .generator import generate

log = logging.getLogger("agnidrishti.seed")


def resolve_anchor(anchor: date | str | None = None) -> date:
    if isinstance(anchor, date):
        return anchor
    if anchor:
        return date.fromisoformat(anchor)
    s = get_settings()
    return date.fromisoformat(s.seed_anchor) if s.seed_anchor else clock.today()


def run_seed(db, *, seed: int | None = None, anchor: date | str | None = None, reset: bool = False,
             post: bool = True) -> dict[str, Any]:
    settings = get_settings()
    seed = settings.seed if seed is None else seed
    anchor_d = resolve_anchor(anchor)
    summary = generate(db, seed=seed, anchor=anchor_d, reset=reset)
    if summary.get("skipped"):
        log.info("seed skipped: dataset already present (use --reset to regenerate)")
        return summary
    if post:
        try:
            from .post import post_process
        except ImportError:  # engines not available (Phase 1 only)
            post_process = None
        if post_process is not None:
            summary["post"] = post_process(db, anchor=anchor_d)
    with db.tx():
        chain.record(db, SYSTEM_USER, "SEED_RESET" if reset else "SEED_DATASET", "dataset", f"seed:{seed}",
                     after={"seed": seed, "anchor": anchor_d.isoformat(), "counts": summary["counts"],
                            "fingerprint": summary["fingerprint"]},
                     remarks="Synthetic demo dataset generated (all complaint history is SYNTHETIC).")
    return summary
