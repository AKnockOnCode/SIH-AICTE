"""SQLite access layer with explicit transactions and versioned SQL migrations.

Why not an ORM? SQLAlchemy could not be installed in the build sandbox (package
registry blocked), so the data layer uses the standard-library `sqlite3` driver with
hand-written, mostly portable SQL. All writes go through `Conn.tx()`, which opens a
`BEGIN IMMEDIATE` transaction (nested calls become SAVEPOINTs). Migrations live in
`app/db/migrations/NNNN_name.sql` and are recorded in `schema_migrations` with a
checksum so an edited, already-applied migration is detected.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..core.clock import now_iso
from ..core.util import sha256_hex

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_init_lock = threading.Lock()
_initialized: set[str] = set()


class Conn:
    """Thin wrapper around a sqlite3 connection returning plain dicts."""

    def __init__(self, raw: sqlite3.Connection):
        self.raw = raw
        self._depth = 0

    # -- reads -----------------------------------------------------------------
    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.raw.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        row = self.raw.execute(sql, tuple(params)).fetchone()
        return dict(row) if row is not None else None

    def val(self, sql: str, params: Iterable[Any] = (), default: Any = None) -> Any:
        row = self.raw.execute(sql, tuple(params)).fetchone()
        if row is None or row[0] is None:
            return default
        return row[0]

    # -- writes ----------------------------------------------------------------
    def run(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self.raw.execute(sql, tuple(params))

    def many(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        self.raw.executemany(sql, [tuple(r) for r in rows])

    def insert(self, table: str, row: dict[str, Any]) -> int:
        cols = ", ".join(row.keys())
        marks = ", ".join("?" for _ in row)
        cur = self.raw.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
        return int(cur.lastrowid or 0)

    def insert_many(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        cols = list(rows[0].keys())
        marks = ", ".join("?" for _ in cols)
        self.raw.executemany(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({marks})",
            [tuple(r[c] for c in cols) for r in rows],
        )

    def update(self, table: str, key_col: str, key_val: Any, changes: dict[str, Any]) -> int:
        if not changes:
            return 0
        sets = ", ".join(f"{c} = ?" for c in changes)
        cur = self.raw.execute(
            f"UPDATE {table} SET {sets} WHERE {key_col} = ?", (*changes.values(), key_val)
        )
        return cur.rowcount

    @property
    def in_tx(self) -> bool:
        return self._depth > 0

    @contextmanager
    def tx(self) -> Iterator[Conn]:
        """Transaction (outermost: BEGIN IMMEDIATE; nested: SAVEPOINT)."""
        depth = self._depth
        if depth == 0:
            self.raw.execute("BEGIN IMMEDIATE")
        else:
            self.raw.execute(f"SAVEPOINT sp{depth}")
        self._depth += 1
        try:
            yield self
        except BaseException:
            self._depth -= 1
            if depth == 0:
                self.raw.execute("ROLLBACK")
            else:
                self.raw.execute(f"ROLLBACK TO sp{depth}")
                self.raw.execute(f"RELEASE sp{depth}")
            raise
        else:
            self._depth -= 1
            if depth == 0:
                self.raw.execute("COMMIT")
            else:
                self.raw.execute(f"RELEASE sp{depth}")

    def close(self) -> None:
        self.raw.close()


def _raw_connect(path: Path) -> sqlite3.Connection:
    raw = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute("PRAGMA busy_timeout = 15000")
    raw.execute("PRAGMA synchronous = NORMAL")
    return raw


def _split_sql(script: str) -> list[str]:
    statements, buf = [], ""
    for line in script.splitlines(keepends=True):
        if not buf and line.strip().startswith("--"):
            continue
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                statements.append(buf.strip())
            buf = ""
    if buf.strip():
        statements.append(buf.strip())
    return statements


def migrate(conn: Conn) -> list[str]:
    """Apply pending migrations in order. Returns names applied in this call."""
    conn.run(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version TEXT PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied = {r["version"]: r for r in conn.all("SELECT * FROM schema_migrations")}
    done: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.name.split("_", 1)[0]
        script = path.read_text(encoding="utf-8")
        checksum = sha256_hex(script)
        if version in applied:
            if applied[version]["checksum"] != checksum:
                raise RuntimeError(
                    f"Migration {path.name} changed after it was applied. "
                    "Add a new migration instead of editing an applied one (or reset the demo DB)."
                )
            continue
        with conn.tx():
            for stmt in _split_sql(script):
                conn.run(stmt)
            conn.run(
                "INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES (?,?,?,?)",
                (version, path.name, checksum, now_iso()),
            )
        done.append(path.name)
    return done


def init_db(path: Path) -> None:
    """Create the database file (WAL mode) and apply migrations, once per process."""
    key = str(path)
    with _init_lock:
        if key in _initialized and path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = _raw_connect(path)
        try:
            raw.execute("PRAGMA journal_mode = WAL")
            migrate(Conn(raw))
        finally:
            raw.close()
        _initialized.add(key)


def forget_initialized(path: Path | None = None) -> None:
    with _init_lock:
        if path is None:
            _initialized.clear()
        else:
            _initialized.discard(str(path))


@contextmanager
def connect(path: Path) -> Iterator[Conn]:
    init_db(path)
    conn = Conn(_raw_connect(path))
    try:
        yield conn
    finally:
        conn.close()


def open_default() -> Conn:
    """Open a connection to the configured database (caller must close)."""
    from ..core.config import get_settings

    path = get_settings().db_path
    init_db(path)
    return Conn(_raw_connect(path))
