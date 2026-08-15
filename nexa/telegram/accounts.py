from __future__ import annotations

from pathlib import Path
from typing import Optional

from nexa.config import AppSettings, load_settings
from nexa.database.db import session_scope
from nexa.database.models import Account, Channel


async def create_account(
    *,
    name: str,
    api_id: int,
    api_hash: str,
    phone: str = "",
    settings: Optional[AppSettings] = None,
) -> Account:
    settings = settings or load_settings()
    settings.resolve_sessions_dir().mkdir(parents=True, exist_ok=True)
    session_name = f"{name}.session"
    async with session_scope() as session:
        account = Account(
            name=name,
            session_path=session_name,
            api_id=api_id,
            api_hash=api_hash,
            phone=phone or "",
            status="offline",
        )
        session.add(account)
        await session.flush()
        await session.refresh(account)
        return Account(
            id=account.id,
            name=account.name,
            session_path=account.session_path,
            api_id=account.api_id,
            api_hash=account.api_hash,
            phone=account.phone,
            status=account.status,
            last_sync=account.last_sync,
        )


async def delete_account(account_id: int, *, settings: Optional[AppSettings] = None) -> str:
    settings = settings or load_settings()
    async with session_scope() as session:
        account = await session.get(Account, account_id)
        if account is None:
            raise ValueError("账号不存在")
        name = account.name
        session_path = account.session_path
        await session.delete(account)

    stem = Path(session_path).name
    sessions_dir = settings.resolve_sessions_dir()
    for suffix in (".session", ".session-journal"):
        path = sessions_dir / f"{Path(stem).stem}{suffix}"
        if path.is_file():
            path.unlink(missing_ok=True)
    return name


async def set_channel_ntfy_topic(channel_id: int, topic: str) -> None:
    from nexa.ntfy.client import normalize_topic

    async with session_scope() as session:
        channel = await session.get(Channel, channel_id)
        if channel is None:
            raise ValueError("频道不存在")
        name = normalize_topic(topic)
        channel.ntfy_topic = name
        # 有主题 = 参与采集/推送；无主题 = 停用
        channel.enabled = bool(name)
