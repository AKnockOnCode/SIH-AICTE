"""Retrain the local models (python -m app.tools.train_models).

* complaint-category classifier (TF-IDF + logistic regression on synthetic texts)
* institution matcher (logistic regression on synthetic name-variant pairs)
* SLA breach model (Cox proportional hazards, refitted from the current case history)

Models are stored under AGNIDRISHTI_MODELS_DIR / SAMANVAY_MODELS_DIR (default backend/var/models). They are also trained
automatically on first start, so this command is only needed after changing the data or seed.
"""

from __future__ import annotations

import json
import sys

from ..core import clock
from ..core.config import get_settings
from ..db.database import connect
from ..institutions import matcher
from ..scoring import classifier
from ..sla import breach


def main() -> int:
    settings = get_settings()
    out = {"classifier": classifier.train(seed=settings.seed)}
    with connect(settings.db_path) as db:
        out["matcher"] = {k: v for k, v in matcher.train_model(db, seed=settings.seed).items() if k in ("metrics", "trained_at")}
        model = breach.fit(db, clock.today())
        out["breach"] = {k: model.get(k) for k in ("status", "c_index", "n_cases", "n_events")}
    print(json.dumps(out, indent=2, default=str)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
