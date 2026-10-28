"""Runtime configuration read from environment variables (see `.env.example`).

Everything has an offline-safe default. Nothing here requires network access or a key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader (no third-party dependency). Real environment variables win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if key.strip() and value:
            os.environ.setdefault(key.strip(), value)


def _path(suffix: str, default: Path) -> Path:
    value = os.environ.get(f"AGNIDRISHTI_{suffix}") or os.environ.get(f"SAMANVAY_{suffix}") or os.environ.get(suffix)
    p = Path(value) if value else default
    return p if p.is_absolute() else (REPO_DIR / p).resolve()


def _sqlite_path_from_url(url: str) -> Path:
    """Accepts `sqlite:///relative/path.db` or `sqlite:////absolute/path.db`."""
    if not url.startswith("sqlite:///"):
        raise RuntimeError(
            "Only SQLite DATABASE_URLs (sqlite:///path) are supported in this build. "
            "See README 'Known limitations' (PostgreSQL is not supported)."
        )
    raw = url[len("sqlite:///"):]
    p = Path(raw)
    return p if p.is_absolute() else (REPO_DIR / p).resolve()


@dataclass(frozen=True)
class Settings:
    database_url: str
    db_path: Path
    storage_dir: Path
    models_dir: Path
    frontend_dist: Path
    seed: int
    seed_anchor: str | None
    today_override: str | None
    default_demo_user: str
    anthropic_model: str
    llm_timeout_s: float
    max_upload_mb: int
    log_level: str
    anthropic_api_key: str | None = field(default=None, repr=False)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


_settings: Settings | None = None


def load_settings() -> Settings:
    _load_dotenv(REPO_DIR / ".env")
    default_db = BACKEND_DIR / "var" / "agnidrishti.db"
    if not default_db.exists() and (BACKEND_DIR / "var" / "samanvay.db").exists():
        default_db = BACKEND_DIR / "var" / "samanvay.db"
    url = os.environ.get("DATABASE_URL") or f"sqlite:///{default_db}"
    return Settings(
        database_url=url,
        db_path=_sqlite_path_from_url(url),
        storage_dir=_path("STORAGE_DIR", BACKEND_DIR / "var" / "storage"),
        models_dir=_path("MODELS_DIR", BACKEND_DIR / "var" / "models"),
        frontend_dist=_path("FRONTEND_DIST", REPO_DIR / "frontend" / "dist"),
        seed=int(os.environ.get("AGNIDRISHTI_SEED") or os.environ.get("SAMANVAY_SEED", "26264")),
        seed_anchor=os.environ.get("AGNIDRISHTI_SEED_ANCHOR") or os.environ.get("SAMANVAY_SEED_ANCHOR") or None,
        today_override=os.environ.get("AGNIDRISHTI_TODAY") or os.environ.get("SAMANVAY_TODAY") or None,
        default_demo_user=os.environ.get("AGNIDRISHTI_DEFAULT_DEMO_USER") or os.environ.get("SAMANVAY_DEFAULT_DEMO_USER", "senior.mgmt"),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5"),
        llm_timeout_s=float(os.environ.get("ANTHROPIC_TIMEOUT_S", "20")),
        max_upload_mb=int(os.environ.get("AGNIDRISHTI_MAX_UPLOAD_MB") or os.environ.get("SAMANVAY_MAX_UPLOAD_MB", "10")),
        log_level=os.environ.get("AGNIDRISHTI_LOG_LEVEL") or os.environ.get("SAMANVAY_LOG_LEVEL", "INFO"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
    )


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    """Used by tests after changing environment variables."""
    global _settings
    _settings = None
