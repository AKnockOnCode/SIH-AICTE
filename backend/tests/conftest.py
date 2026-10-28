"""Shared fixtures.

A seeded template database is generated once per test session with a frozen date
(anchor = SAMANVAY_TODAY = 2026-10-27). Tests that mutate data get their own copy.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

ANCHOR = "2026-10-27"


def _point_settings_at(db_path: Path, models_dir: Path, storage_dir: Path) -> None:
    from app.core.config import reset_settings
    from app.db.database import forget_initialized

    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["AGNIDRISHTI_TODAY"] = ANCHOR
    os.environ["SAMANVAY_TODAY"] = ANCHOR
    os.environ["AGNIDRISHTI_SEED_ANCHOR"] = ANCHOR
    os.environ["SAMANVAY_SEED_ANCHOR"] = ANCHOR
    os.environ["AGNIDRISHTI_MODELS_DIR"] = str(models_dir)
    os.environ["SAMANVAY_MODELS_DIR"] = str(models_dir)
    os.environ["AGNIDRISHTI_STORAGE_DIR"] = str(storage_dir)
    os.environ["SAMANVAY_STORAGE_DIR"] = str(storage_dir)
    os.environ["ANTHROPIC_API_KEY"] = ""  # empty (not unset) so a developer .env cannot inject a real key into tests
    reset_settings()
    forget_initialized()


@pytest.fixture(scope="session")
def session_dirs(tmp_path_factory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("agnidrishti")
    dirs = {"base": base, "models": base / "models", "storage": base / "storage"}
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    return dirs


@pytest.fixture(scope="session")
def template_db(session_dirs) -> Path:
    from app.db.database import connect
    from app.seed.runner import run_seed

    path = session_dirs["base"] / "template.db"
    _point_settings_at(path, session_dirs["models"], session_dirs["storage"])
    with connect(path) as db:
        run_seed(db, anchor=ANCHOR, reset=True)
    return path


def _copy_db(src: Path, dst: Path) -> None:
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dst))
    with d:
        s.backup(d)
    s.close()
    d.close()


@pytest.fixture
def db_path(template_db, tmp_path, session_dirs) -> Path:
    dst = tmp_path / "test.db"
    _copy_db(template_db, dst)
    _point_settings_at(dst, session_dirs["models"], tmp_path / "storage")
    return dst


@pytest.fixture
def db(db_path):
    from app.db.database import connect

    with connect(db_path) as conn:
        yield conn


@pytest.fixture
def ro_db(template_db, session_dirs):
    """Read-only use of the shared template (do not mutate)."""
    from app.db.database import connect

    _point_settings_at(template_db, session_dirs["models"], session_dirs["storage"])
    with connect(template_db) as conn:
        yield conn
