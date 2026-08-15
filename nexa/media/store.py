from __future__ import annotations

from pathlib import Path
from typing import Optional

from nexa.config import AppSettings, load_settings


def resolve_media_path(relative: str, settings: Optional[AppSettings] = None) -> Path:
    settings = settings or load_settings()
    root = settings.resolve_media_dir()
    return (root / relative).resolve()
