"""CLI: python -m app.seed [--reset] [--yes] [--anchor YYYY-MM-DD] [--seed N]

Default behaviour is safe: seed only if the database is empty. `--reset` wipes the demo
database (including its audit log) and regenerates it; it asks for confirmation unless
`--yes` is given.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from ..core.config import get_settings
from ..db.database import connect
from .runner import run_seed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed", description="Seed the AgniDrishti demo database.")
    parser.add_argument("--reset", action="store_true", help="wipe and regenerate the demo dataset")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation on --reset")
    parser.add_argument("--anchor", help="dataset 'today' (YYYY-MM-DD); default: today or AGNIDRISHTI_SEED_ANCHOR")
    parser.add_argument("--seed", type=int, help="random seed (default AGNIDRISHTI_SEED or 26264)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    if args.reset and not args.yes:
        answer = input(f"This deletes ALL data in {settings.db_path} (demo DB). Type 'reset' to continue: ")
        if answer.strip().lower() != "reset":
            print("Aborted.")
            return 1
    with connect(settings.db_path) as db:
        summary = run_seed(db, seed=args.seed, anchor=args.anchor, reset=args.reset)
    summary.pop("demo", None)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
