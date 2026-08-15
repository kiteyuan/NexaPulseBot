from __future__ import annotations

from pathlib import Path

from nexa.config import AppSettings


def resolve_session_stem(session_path: str, settings: AppSettings) -> str:
    """Return Telethon session path without .session suffix."""
    sessions_dir = settings.resolve_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = Path(session_path)
    if not path.is_absolute():
        path = sessions_dir / path.name
    return str(path.with_suffix(""))
