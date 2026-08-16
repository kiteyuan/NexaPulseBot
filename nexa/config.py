from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
EXAMPLE_PATH = CONFIG_DIR / "settings.example.json"


# off = no translation; otherwise BCP-47-ish short codes used in prompts
TRANSLATE_OPTIONS: dict[str, str] = {
    "off": "关闭（不翻译）",
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}


class LLMSettings(BaseModel):
    enabled: bool = False
    provider: str = "DeepSeek"
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-v4-flash"
    temperature: float = 0.3
    # off | zh | en | ja | ko — translate cleaned body/title after review
    translate_to: str = "off"


class NtfySettings(BaseModel):
    """Self-hosted or public ntfy publisher."""

    base_url: str = "http://127.0.0.1:2586"
    # Topics created in menu; channels must be assigned to one of these
    topics: list[str] = Field(default_factory=list)
    # Disabled topics keep channel bindings but stop poll/push
    disabled_topics: list[str] = Field(default_factory=list)
    token: str = ""
    priority: int = 3


class FilterSettings(BaseModel):
    min_length: int = 20
    block_keywords: list[str] = Field(default_factory=lambda: ["广告", "加群", "优惠券"])


class AppSettings(BaseModel):
    database_path: str = "data/nexa.db"
    sessions_dir: str = "sessions"
    media_dir: str = "data/media"
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ntfy: NtfySettings = Field(default_factory=NtfySettings)
    filter: FilterSettings = Field(default_factory=FilterSettings)
    # Processor / ntfy sender idle poll
    poll_interval_seconds: float = 2.0
    # Telegram channel fetch interval (default 30 minutes)
    telegram_poll_interval_seconds: float = 1800.0

    def resolve_db_path(self) -> Path:
        path = Path(self.database_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path

    def resolve_sessions_dir(self) -> Path:
        path = Path(self.sessions_dir)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path

    def resolve_media_dir(self) -> Path:
        path = Path(self.media_dir)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path


def ensure_settings_file() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.exists():
        if EXAMPLE_PATH.exists():
            SETTINGS_PATH.write_text(EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            SETTINGS_PATH.write_text(
                AppSettings().model_dump_json(indent=2),
                encoding="utf-8",
            )
    return SETTINGS_PATH


def _apply_env_overrides(settings: AppSettings) -> AppSettings:
    """Docker Compose can inject NEXA_* without rewriting settings.json."""
    if v := os.getenv("NEXA_NTFY_BASE_URL", "").strip():
        settings.ntfy.base_url = v
    if v := os.getenv("NEXA_NTFY_TOKEN", "").strip():
        settings.ntfy.token = v
    if v := os.getenv("NEXA_NTFY_PRIORITY", "").strip():
        settings.ntfy.priority = int(v)
    if v := os.getenv("NEXA_LLM_ENABLED", "").strip().lower():
        settings.llm.enabled = v in ("1", "true", "yes", "on")
    if v := os.getenv("NEXA_LLM_BASE_URL", "").strip():
        settings.llm.base_url = v
    if v := os.getenv("NEXA_LLM_KEY", "").strip():
        settings.llm.api_key = v
    if v := os.getenv("NEXA_LLM_MODEL", "").strip():
        settings.llm.model = v
    if v := os.getenv("NEXA_LLM_TRANSLATE", "").strip().lower():
        if v in TRANSLATE_OPTIONS:
            settings.llm.translate_to = v
    if v := os.getenv("NEXA_TG_POLL_INTERVAL", "").strip():
        settings.telegram_poll_interval_seconds = float(v)
    return settings


def load_settings() -> AppSettings:
    path = ensure_settings_file()
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    # Drop legacy blocks
    data.pop("qq", None)
    data.pop("imagebed", None)
    ntfy = data.get("ntfy")
    if isinstance(ntfy, dict):
        legacy = (ntfy.pop("topic", None) or "").strip().strip("/")
        topics = list(ntfy.get("topics") or [])
        if legacy and legacy not in topics:
            topics.append(legacy)
        ntfy["topics"] = topics
        ntfy.setdefault("disabled_topics", [])
    llm = data.get("llm")
    if isinstance(llm, dict):
        tr = str(llm.get("translate_to") or "off").strip().lower()
        llm["translate_to"] = tr if tr in TRANSLATE_OPTIONS else "off"
    settings = AppSettings.model_validate(data)
    return _apply_env_overrides(settings)


def save_settings(settings: AppSettings) -> None:
    ensure_settings_file()
    SETTINGS_PATH.write_text(
        settings.model_dump_json(indent=2),
        encoding="utf-8",
    )


def update_settings(**kwargs: Any) -> AppSettings:
    settings = load_settings()
    data = settings.model_dump()
    for key, value in kwargs.items():
        if key in data and isinstance(value, dict) and isinstance(data[key], dict):
            data[key].update(value)
        else:
            data[key] = value
    updated = AppSettings.model_validate(data)
    save_settings(updated)
    return load_settings()
