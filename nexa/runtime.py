from __future__ import annotations

import logging
from typing import Optional

from nexa.config import AppSettings, load_settings
from nexa.database.db import add_log, close_db, init_db
from nexa.ntfy import NtfySender
from nexa.service.processor import MessageProcessor
from nexa.telegram.listener import TelethonListener

logger = logging.getLogger(__name__)


class AppRuntime:
    """Owns Telethon / processor / ntfy workers."""

    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or load_settings()
        self.listener = TelethonListener(self.settings)
        self.processor = MessageProcessor(self.settings)
        self.sender = NtfySender(self.settings)
        self._started = False
        self._db_ready = False

    def reload_settings(self) -> AppSettings:
        self.settings = load_settings()
        self.listener.reload_settings(self.settings)
        self.processor.reload_settings(self.settings)
        self.sender.reload_settings(self.settings)
        return self.settings

    async def ensure_db(self) -> None:
        self.reload_settings()
        await init_db(self.settings)
        self._db_ready = True

    async def start(self) -> None:
        if self._started:
            return
        await self.ensure_db()
        await self.listener.start()
        await self.processor.start()
        await self.sender.start()
        self._started = True
        await add_log("NexaPulseBot 运行时已启动", source="runtime")

    async def stop(self) -> None:
        if not self._started:
            return
        await self.sender.stop()
        await self.processor.stop()
        await self.listener.stop()
        await add_log("NexaPulseBot 运行时已停止", source="runtime")
        self._started = False

    async def shutdown(self) -> None:
        if self._started:
            await self.stop()
        await close_db()
        self._db_ready = False

    @property
    def started(self) -> bool:
        return self._started

    @property
    def db_ready(self) -> bool:
        return self._db_ready
