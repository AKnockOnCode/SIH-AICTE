"""Single source of 'today' and 'now'.

SLA, ageing, risk recency and forecasts all depend on the current date. Tests and
rehearsed demos can freeze it with AGNIDRISHTI_TODAY=YYYY-MM-DD (or SAMANVAY_TODAY). Business dates are
Indian Standard Time; stored timestamps are UTC ISO-8601 strings ending in 'Z'.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, time, timedelta, timezone

from .config import get_settings

IST = timezone(timedelta(hours=5, minutes=30))


def today() -> date:
    override = get_settings().today_override
    if override:
        return date.fromisoformat(override)
    return datetime.now(IST).date()


_lock = threading.Lock()
_floor: dict[str, datetime] = {}  # frozen date -> latest timestamp issued or observed on it


def observe(ts: str | None) -> None:
    """Frozen-date mode: register an already stored timestamp so later 'now' values sort after it."""
    override = get_settings().today_override
    if not override or not ts:
        return
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    with _lock:
        if override not in _floor or t > _floor[override]:
            _floor[override] = t


def now_utc() -> datetime:
    override = get_settings().today_override
    real = datetime.now(UTC)
    if not override:
        return real
    # Frozen date: the real time of day on the frozen date, but never earlier than a timestamp already
    # issued or stored, so new events always sort after older ones (also after midnight or a restart).
    d = date.fromisoformat(override)
    candidate = datetime.combine(d, real.astimezone(IST).timetz()).astimezone(UTC)
    end_of_day = datetime.combine(d, time(23, 59, 59, 999000), tzinfo=IST).astimezone(UTC)
    with _lock:
        floor = _floor.get(override)
        if floor is not None and candidate <= floor:
            # whole-second steps: most stored timestamps have second precision
            candidate = min(floor.replace(microsecond=0) + timedelta(seconds=1), end_of_day)
        if floor is None or candidate > floor:
            _floor[override] = candidate
    return candidate


def iso_z(dt: datetime, micro: bool = False) -> str:
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ" if micro else "%Y-%m-%dT%H:%M:%SZ")


def now_iso(micro: bool = False) -> str:
    return iso_z(now_utc(), micro=micro)


def ist_datetime(d: date, hour: int, minute: int = 0) -> datetime:
    """A business-day timestamp (IST wall clock) converted to UTC."""
    return datetime.combine(d, time(hour, minute), tzinfo=IST).astimezone(UTC)


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])
