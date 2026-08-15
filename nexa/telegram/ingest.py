from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from telethon import TelegramClient

from nexa.config import AppSettings
from nexa.database.db import add_log, session_scope
from nexa.database.models import Channel, LLMStatus, Message, SendStatus
from nexa.service.dedup import content_hash


def is_image_message(message: object) -> bool:
    if getattr(message, "photo", None):
        return True
    doc = getattr(message, "document", None)
    if not doc:
        return False
    mime = (getattr(doc, "mime_type", None) or "").lower()
    return mime.startswith("image/")


async def download_images(
    client: TelegramClient,
    message: object,
    *,
    settings: AppSettings,
    channel_db_id: int,
    telegram_message_id: int,
    index: int = 0,
) -> list[str]:
    if not is_image_message(message):
        return []
    media_root = settings.resolve_media_dir()
    dest_dir = media_root / str(channel_db_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{telegram_message_id}_{index}"
    path = await client.download_media(message, file=str(dest))
    if not path:
        return []
    abs_path = Path(path).resolve()
    try:
        rel = abs_path.relative_to(media_root.resolve()).as_posix()
    except ValueError:
        rel = f"{channel_db_id}/{abs_path.name}"
    return [rel]


async def ingest_message(
    *,
    account_id: int,
    telegram_channel_id: int,
    content: str,
    channel_title: str,
    username: Optional[str],
    telegram_message_id: int,
    media_paths: Optional[list[str]] = None,
) -> None:
    media_paths = list(media_paths or [])
    label = f"@{username}" if username else channel_title or str(telegram_channel_id)
    hash_seed = content if content.strip() else ""
    if media_paths:
        hash_seed = f"{hash_seed}\0media:{','.join(media_paths)}"
    try:
        async with session_scope() as session:
            result = await session.execute(
                select(Channel).where(
                    Channel.account_id == account_id,
                    Channel.telegram_id == telegram_channel_id,
                    Channel.ntfy_topic != "",
                )
            )
            channel = result.scalar_one_or_none()
            if channel is None:
                return

            exists = await session.execute(
                select(Message.id)
                .where(
                    Message.channel_id == channel.id,
                    Message.telegram_message_id == telegram_message_id,
                )
                .limit(1)
            )
            if exists.scalar_one_or_none() is not None:
                return

            session.add(
                Message(
                    channel_id=channel.id,
                    telegram_message_id=telegram_message_id,
                    content=content or "",
                    content_hash=content_hash(hash_seed),
                    media_paths=media_paths or None,
                    llm_status=LLMStatus.PENDING.value,
                    send_status=SendStatus.IDLE.value,
                )
            )
    except IntegrityError:
        return

    media_note = f" +{len(media_paths)}图" if media_paths else ""
    await add_log(f"收到 {label}{media_note}", source="telegram")
