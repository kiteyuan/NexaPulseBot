from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize DB/naive datetimes to aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """ISO-8601 UTC string ending with Z (e.g. 2026-08-12T07:30:42Z)."""
    aware = ensure_utc(dt)
    if aware is None:
        return None
    return aware.strftime("%Y-%m-%dT%H:%M:%SZ")
