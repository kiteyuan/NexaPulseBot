from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from nexa.config import AppSettings, load_settings
from nexa.database.db import add_log, session_scope
from nexa.database.models import Channel, Message, SendStatus
from nexa.media.store import resolve_media_path
from nexa.ntfy.client import NtfyClient, normalize_topic
from nexa.service.worker import AsyncWorker

logger = logging.getLogger(__name__)

_FILE_CAPTION_MAX = 400


def topic_is_disabled(topic: str, disabled: list[str]) -> bool:
    name = normalize_topic(topic)
    if not name:
        return True
    disabled_set = {normalize_topic(t) for t in (disabled or []) if normalize_topic(t)}
    return name in disabled_set


class NtfySender(AsyncWorker):
    """Poll ready messages and publish via ntfy."""

    source = "ntfy"
    task_name = "ntfy-sender"

    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        super().__init__(settings)
        self.client = NtfyClient(self.settings.ntfy)

    def reload_settings(self, settings: AppSettings) -> None:
        super().reload_settings(settings)
        self.client.reload_settings(settings.ntfy)

    def _started_message(self) -> str:
        return "ntfy 推送服务已启动"

    def _stopped_message(self) -> str:
        return "ntfy 推送服务已停止"

    async def tick(self) -> bool:
        sent = await self.send_batch(limit=5)
        return sent > 0

    async def send_batch(self, limit: int = 5) -> int:
        async with session_scope() as session:
            result = await session.execute(
                select(Message)
                .where(Message.send_status == SendStatus.READY.value)
                .order_by(Message.id.asc())
                .limit(limit)
            )
            message_ids = [m.id for m in result.scalars().all()]

        for message_id in message_ids:
            await self._send_one(message_id)
        return len(message_ids)

    async def _send_one(self, message_id: int) -> None:
        async with session_scope() as session:
            msg = await session.get(Message, message_id)
            if msg is None or msg.send_status != SendStatus.READY.value:
                return
            channel = await session.get(Channel, msg.channel_id)
            text = notification_body(msg.llm_result, msg.content or "")
            media = [str(p) for p in (msg.media_paths or []) if p]
            title = notification_title(msg.llm_result, msg.content or "")
            topic = normalize_topic(channel.ntfy_topic if channel else "")

        if not topic:
            await self._mark_failed(message_id, "频道未分配 ntfy 主题")
            await add_log(
                "推送失败: 频道未分配主题（菜单 → ntfy 主题管理 → 分配主题）",
                level="ERROR",
                source="ntfy",
            )
            return

        if topic_is_disabled(topic, load_settings().ntfy.disabled_topics):
            # Keep ready — enabling the topic resumes push without requeue
            return

        try:
            await self._publish(text=text, media=media, title=title, topic=topic)
        except Exception as exc:  # noqa: BLE001
            await self._mark_failed(message_id, str(exc))
            await add_log(f"ntfy 推送失败: {exc}", level="ERROR", source="ntfy")
            return

        async with session_scope() as session:
            msg = await session.get(Message, message_id)
            if msg:
                msg.send_status = SendStatus.SENT.value
        await add_log(f"ntfy 推送成功 [{title}] → {topic}", source="ntfy")

    async def _publish(
        self,
        *,
        text: str,
        media: list[str],
        title: str,
        topic: str,
    ) -> None:
        if not media:
            if not text:
                raise RuntimeError("空消息")
            await self.client.publish(text, title=title, topic=topic)
            return

        paths = [resolve_media_path(rel, self.settings) for rel in media]
        existing = [p for p in paths if p.is_file()]
        if not existing and not text:
            raise RuntimeError("无文字且图片文件缺失")
        if not existing:
            await self.client.publish(text, title=title, topic=topic)
            return

        # Long body → JSON (Unicode-safe); images → native uploads (inline preview)
        body = text.strip()
        caption = ""
        if body and len(body) <= _FILE_CAPTION_MAX:
            caption = body
        elif body:
            await self.client.publish(body, title=title, topic=topic)

        for index, path in enumerate(existing):
            await self.client.publish_file(
                path,
                message=caption if index == 0 else "",
                title=title,
                topic=topic,
                filename=_image_filename(path, index=index),
            )
            if index + 1 < len(existing):
                await asyncio.sleep(0.25)

    @staticmethod
    async def _mark_failed(message_id: int, error: str) -> None:
        async with session_scope() as session:
            msg = await session.get(Message, message_id)
            if msg:
                msg.send_status = SendStatus.FAILED.value
                msg.error_message = error


def notification_title(llm_result: Optional[dict[str, Any]], content: str) -> str:
    if isinstance(llm_result, dict):
        t = str(llm_result.get("title") or "").strip()
        if t:
            return t[:80]
    line = (content or "").strip().splitlines()[0] if (content or "").strip() else ""
    line = " ".join(line.split())
    if line:
        return line[:40] + ("…" if len(line) > 40 else "")
    return "资讯速递"


def notification_body(llm_result: Optional[dict[str, Any]], content: str) -> str:
    if isinstance(llm_result, dict):
        body = str(llm_result.get("body") or llm_result.get("summary") or "").strip()
        if body:
            return body
    return (content or "").strip()


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _image_filename(path: Path, *, index: int = 0) -> str:
    suffix = path.suffix.lower()
    if suffix in _IMAGE_EXTS:
        return path.name
    return f"image_{index}.jpg"
