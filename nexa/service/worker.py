from __future__ import annotations

import asyncio
import logging
from typing import Optional

from nexa.config import AppSettings, load_settings
from nexa.database.db import add_log

logger = logging.getLogger(__name__)


class AsyncWorker:
    """Shared start/stop/idle-loop for processor and outbound senders."""

    source: str = "system"
    task_name: str = "worker"

    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or load_settings()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def reload_settings(self, settings: AppSettings) -> None:
        self.settings = settings

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name=self.task_name)
        await add_log(self._started_message(), source=self.source)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await add_log(self._stopped_message(), source=self.source)

    def _started_message(self) -> str:
        return f"{self.task_name} 已启动"

    def _stopped_message(self) -> str:
        return f"{self.task_name} 已停止"

    async def _loop(self) -> None:
        while self._running:
            try:
                did_work = await self.tick()
                if not did_work:
                    await asyncio.sleep(self.settings.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("%s loop error", self.task_name)
                await add_log(f"{self.task_name}异常: {exc}", level="ERROR", source=self.source)
                await asyncio.sleep(self.settings.poll_interval_seconds)

    async def tick(self) -> bool:
        """Do one unit of work. Return True if work happened (skip idle sleep)."""
        raise NotImplementedError
