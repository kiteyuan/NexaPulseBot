from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.custom.dialog import Dialog
from telethon.tl.types import Channel as TgChannel
from telethon.tl.types import Chat, User

from nexa.config import AppSettings, load_settings
from nexa.database.db import add_log, session_scope
from nexa.database.models import Account, Channel
from nexa.telegram.ingest import download_images, ingest_message, is_image_message
from nexa.telegram.paths import resolve_session_stem

logger = logging.getLogger(__name__)


class TelethonListener:
    """Manage Telethon sessions: poll topic-assigned channels into SQLite."""

    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or load_settings()
        self._clients: dict[int, TelegramClient] = {}
        self._client_tasks: dict[int, asyncio.Task] = {}
        self._qr_logins: dict[int, object] = {}
        self._running = False

    def reload_settings(self, settings: AppSettings) -> None:
        self.settings = settings

    def _session_stem(self, session_path: str) -> str:
        return resolve_session_stem(session_path, self.settings)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        async with session_scope() as session:
            accounts = list((await session.execute(select(Account))).scalars().all())

        for account in accounts:
            try:
                await self._start_account(account.id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("failed to start account %s", account.name)
                await add_log(
                    f"账号启动失败 {account.name}: {exc}",
                    level="ERROR",
                    source="telegram",
                )
        await add_log("Telegram 轮询服务已启动", source="telegram")

    async def stop(self) -> None:
        self._running = False
        for account_id in list(self._clients.keys()):
            await self._disconnect_account(account_id)
        self._qr_logins.clear()
        await add_log("Telegram 轮询服务已停止", source="telegram")

    async def _disconnect_account(self, account_id: int) -> None:
        task = self._client_tasks.pop(account_id, None)
        self._qr_logins.pop(account_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        client = self._clients.pop(account_id, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                logger.exception("disconnect account %s", account_id)

    async def _start_account(self, account_id: int) -> None:
        async with session_scope() as session:
            account = await session.get(Account, account_id)
            if account is None:
                return
            snap = {
                "id": account.id,
                "name": account.name,
                "api_id": account.api_id,
                "api_hash": account.api_hash,
                "session_path": account.session_path,
            }

        if snap["id"] in self._clients:
            return

        client = TelegramClient(
            self._session_stem(snap["session_path"]),
            snap["api_id"],
            snap["api_hash"],
        )
        await client.connect()
        if not await client.is_user_authorized():
            async with session_scope() as session:
                acc = await session.get(Account, account_id)
                if acc:
                    acc.status = "needs_login"
            await add_log(f"账号 {snap['name']} 需要登录", level="WARN", source="telegram")
            await client.disconnect()
            return

        self._clients[account_id] = client
        async with session_scope() as session:
            acc = await session.get(Account, account_id)
            if acc:
                acc.status = "online"
                acc.last_sync = datetime.now(timezone.utc)

        interval = float(self.settings.telegram_poll_interval_seconds or 1800)
        await add_log(
            f"账号 {snap['name']} 已上线（每 {int(interval)} 秒轮询频道）",
            source="telegram",
        )
        self._client_tasks[account_id] = asyncio.create_task(
            self._account_poll_loop(account_id),
            name=f"tg-poll-{account_id}",
        )

    async def _account_poll_loop(self, account_id: int) -> None:
        while self._running:
            try:
                await self._poll_account_channels(account_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("poll account %s failed", account_id)
                await add_log(
                    f"轮询失败 account={account_id}: {exc}",
                    level="ERROR",
                    source="telegram",
                )
            interval = float(self.settings.telegram_poll_interval_seconds or 1800)
            slept = 0.0
            while self._running and slept < interval:
                step = min(5.0, interval - slept)
                await asyncio.sleep(step)
                slept += step

    async def _poll_account_channels(self, account_id: int) -> None:
        client = self._clients.get(account_id)
        if client is None or not client.is_connected():
            return
        async with session_scope() as session:
            result = await session.execute(
                select(Channel).where(
                    Channel.account_id == account_id,
                    Channel.ntfy_topic != "",
                )
            )
            channels = [
                {
                    "id": c.id,
                    "telegram_id": int(c.telegram_id),
                    "username": c.username,
                    "title": c.title or "",
                    "last_message_id": int(c.last_message_id or 0),
                    "ntfy_topic": (c.ntfy_topic or "").strip(),
                }
                for c in result.scalars().all()
            ]
            acc = await session.get(Account, account_id)
            if acc:
                acc.last_sync = datetime.now(timezone.utc)

        disabled = {
            (t or "").strip().strip("/")
            for t in (load_settings().ntfy.disabled_topics or [])
            if (t or "").strip()
        }
        channels = [ch for ch in channels if ch["ntfy_topic"] not in disabled]

        if not channels:
            return

        total_new = 0
        for ch in channels:
            try:
                total_new += await self._poll_one_channel(client, account_id, ch)
            except Exception as exc:  # noqa: BLE001
                logger.exception("poll channel %s", ch["id"])
                label = f"@{ch['username']}" if ch["username"] else ch["title"] or ch["telegram_id"]
                await add_log(f"轮询频道失败 {label}: {exc}", level="ERROR", source="telegram")

        if total_new:
            await add_log(f"本轮轮询入库 {total_new} 条", source="telegram")

    async def _poll_one_channel(
        self,
        client: TelegramClient,
        account_id: int,
        ch: dict[str, Any],
    ) -> int:
        entity = await _resolve_entity(client, ch)
        last_id = int(ch["last_message_id"] or 0)

        if last_id <= 0:
            latest = await client.get_messages(entity, limit=1)
            cursor = int(latest[0].id) if latest else 0
            async with session_scope() as session:
                row = await session.get(Channel, ch["id"])
                if row:
                    row.last_message_id = cursor
            return 0

        fetched: list[Any] = []
        async for msg in client.iter_messages(entity, min_id=last_id, reverse=True, limit=200):
            fetched.append(msg)
        if not fetched:
            return 0

        albums: dict[int, list[Any]] = {}
        singles: list[Any] = []
        for msg in fetched:
            gid = getattr(msg, "grouped_id", None)
            if gid:
                albums.setdefault(int(gid), []).append(msg)
            else:
                singles.append(msg)

        ingested = 0
        max_id = last_id
        for msg in singles:
            max_id = max(max_id, int(msg.id))
            if await self._ingest_polled_message(client, account_id, ch, msg):
                ingested += 1

        for parts in albums.values():
            parts = sorted(parts, key=lambda m: int(m.id))
            for p in parts:
                max_id = max(max_id, int(p.id))
            if await self._ingest_polled_album(client, account_id, ch, parts):
                ingested += 1

        async with session_scope() as session:
            row = await session.get(Channel, ch["id"])
            if row and max_id > int(row.last_message_id or 0):
                row.last_message_id = max_id
        return ingested

    async def _ingest_polled_message(
        self,
        client: TelegramClient,
        account_id: int,
        ch: dict[str, Any],
        message: object,
    ) -> bool:
        text = (getattr(message, "message", None) or "").strip()
        has_image = is_image_message(message)
        if not text and not has_image:
            return False
        media_paths: list[str] = []
        if has_image:
            media_paths = await download_images(
                client,
                message,
                settings=self.settings,
                channel_db_id=int(ch["id"]),
                telegram_message_id=int(getattr(message, "id")),
            )
        if not text and not media_paths:
            return False
        await ingest_message(
            account_id=account_id,
            telegram_channel_id=int(ch["telegram_id"]),
            telegram_message_id=int(getattr(message, "id")),
            content=text,
            media_paths=media_paths,
            channel_title=ch["title"],
            username=ch["username"],
        )
        return True

    async def _ingest_polled_album(
        self,
        client: TelegramClient,
        account_id: int,
        ch: dict[str, Any],
        parts: list[Any],
    ) -> bool:
        texts: list[str] = []
        media_paths: list[str] = []
        for index, message in enumerate(parts):
            text = (getattr(message, "message", None) or "").strip()
            if text:
                texts.append(text)
            if is_image_message(message):
                media_paths.extend(
                    await download_images(
                        client,
                        message,
                        settings=self.settings,
                        channel_db_id=int(ch["id"]),
                        telegram_message_id=int(getattr(message, "id")),
                        index=index,
                    )
                )
        content = "\n".join(texts).strip()
        if not content and not media_paths:
            return False
        await ingest_message(
            account_id=account_id,
            telegram_channel_id=int(ch["telegram_id"]),
            telegram_message_id=int(parts[0].id),
            content=content,
            media_paths=media_paths,
            channel_title=ch["title"],
            username=ch["username"],
        )
        return True

    async def reload_account_filters(self, account_id: int) -> None:
        await self._disconnect_account(account_id)
        if self._running:
            await self._start_account(account_id)

    async def begin_qr_login(self, account_id: int) -> str:
        async with session_scope() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise ValueError("账号不存在")
            snap = {
                "name": account.name,
                "api_id": account.api_id,
                "api_hash": account.api_hash,
                "session_path": account.session_path,
            }

        await self._disconnect_account(account_id)
        client = TelegramClient(
            self._session_stem(snap["session_path"]),
            snap["api_id"],
            snap["api_hash"],
        )
        await client.connect()
        if await client.is_user_authorized():
            async with session_scope() as session:
                acc = await session.get(Account, account_id)
                if acc:
                    acc.status = "online"
                    acc.last_sync = datetime.now(timezone.utc)
            await client.disconnect()
            if self._running:
                await self._start_account(account_id)
            raise RuntimeError("该账号已登录，无需扫码")

        qr_login = await client.qr_login()
        self._clients[account_id] = client
        self._qr_logins[account_id] = qr_login
        async with session_scope() as session:
            acc = await session.get(Account, account_id)
            if acc:
                acc.status = "qr_pending"
        await add_log(f"账号 {snap['name']} 已生成登录二维码，请用手机扫码", source="telegram")
        return qr_login.url

    async def refresh_qr_login(self, account_id: int) -> str:
        qr_login = self._qr_logins.get(account_id)
        if qr_login is None:
            return await self.begin_qr_login(account_id)
        await qr_login.recreate()  # type: ignore[attr-defined]
        return qr_login.url  # type: ignore[attr-defined]

    async def wait_qr_login(
        self,
        account_id: int,
        *,
        password: Optional[str] = None,
        timeout: float = 30.0,
    ) -> str:
        client = self._clients.get(account_id)
        qr_login = self._qr_logins.get(account_id)
        if client is None or qr_login is None:
            raise RuntimeError("请先生成二维码")

        async with session_scope() as session:
            account = await session.get(Account, account_id)
            name = account.name if account else str(account_id)

        try:
            await qr_login.wait(timeout=timeout)  # type: ignore[attr-defined]
        except asyncio.TimeoutError:
            return "timeout"
        except SessionPasswordNeededError:
            if not password:
                async with session_scope() as session:
                    acc = await session.get(Account, account_id)
                    if acc:
                        acc.status = "need_2fa"
                return "need_2fa"
            await client.sign_in(password=password)

        await self._finalize_login(account_id, name=name, client=client)
        return "ok"

    async def submit_qr_2fa(self, account_id: int, password: str) -> None:
        client = self._clients.get(account_id)
        if client is None:
            raise RuntimeError("登录会话已失效，请重新生成二维码")
        if not password:
            raise ValueError("请填写 2FA 密码")
        async with session_scope() as session:
            account = await session.get(Account, account_id)
            name = account.name if account else str(account_id)
        await client.sign_in(password=password)
        await self._finalize_login(account_id, name=name, client=client)

    async def _finalize_login(
        self,
        account_id: int,
        *,
        name: str,
        client: TelegramClient,
    ) -> None:
        phone = ""
        try:
            me = await client.get_me()
            phone = getattr(me, "phone", None) or ""
            if phone and not phone.startswith("+"):
                phone = f"+{phone}"
        except Exception:  # noqa: BLE001
            pass

        async with session_scope() as session:
            acc = await session.get(Account, account_id)
            if acc:
                acc.status = "online"
                acc.last_sync = datetime.now(timezone.utc)
                if phone:
                    acc.phone = phone

        self._qr_logins.pop(account_id, None)
        self._client_tasks.pop(account_id, None)
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        self._clients.pop(account_id, None)
        if self._running:
            await self._start_account(account_id)
        await add_log(f"账号 {name} 扫码登录成功", source="telegram")

    async def sync_channels(self, account_id: int) -> list[dict]:
        client = self._clients.get(account_id)
        temporary = False
        async with session_scope() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise ValueError("账号不存在")
            snap = {
                "api_id": account.api_id,
                "api_hash": account.api_hash,
                "session_path": account.session_path,
                "name": account.name,
            }

        try:
            if client is None:
                client = TelegramClient(
                    self._session_stem(snap["session_path"]),
                    snap["api_id"],
                    snap["api_hash"],
                )
                temporary = True
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    raise RuntimeError("账号未登录")

            dialogs = await client.get_dialogs()
            entries: list[dict[str, Any]] = []
            for dialog in dialogs:
                if not _is_broadcast_or_channel(dialog):
                    continue
                entity = dialog.entity
                tg_id = int(entity.id)
                username = getattr(entity, "username", None)
                title = dialog.name or username or str(tg_id)
                entries.append(
                    {
                        "telegram_id": tg_id,
                        "username": username,
                        "title": title,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            if temporary and client is not None:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            raise _friendly_lock_error(exc) from exc

        # Release Telethon session before writing nexa.db (avoid dual lock with bot)
        if temporary:
            await client.disconnect()

        synced: list[dict] = []
        try:
            async with session_scope() as session:
                for entry in entries:
                    tg_id = int(entry["telegram_id"])
                    result = await session.execute(
                        select(Channel).where(
                            Channel.account_id == account_id,
                            Channel.telegram_id == tg_id,
                        )
                    )
                    channel = result.scalar_one_or_none()
                    if channel is None:
                        channel = Channel(
                            account_id=account_id,
                            telegram_id=tg_id,
                            username=entry["username"],
                            title=entry["title"],
                            enabled=False,
                        )
                        session.add(channel)
                    else:
                        channel.username = entry["username"]
                        channel.title = entry["title"]
                synced.append(
                    {
                        "telegram_id": tg_id,
                        "username": entry["username"],
                        "title": entry["title"],
                        "ntfy_topic": (channel.ntfy_topic or "").strip(),
                    }
                )
                acc = await session.get(Account, account_id)
                if acc:
                    acc.last_sync = datetime.now(timezone.utc)
        except Exception as exc:  # noqa: BLE001
            raise _friendly_lock_error(exc) from exc

        await add_log(f"账号 {snap['name']} 同步频道 {len(synced)} 个", source="telegram")
        return synced


def _friendly_lock_error(exc: BaseException) -> BaseException:
    text = str(exc).lower()
    if "database is locked" in text or "database locked" in text:
        return RuntimeError(
            "数据库被占用（多半是 bot 正在跑，与菜单抢同一份 Telethon session / SQLite）。\n"
            "  1) docker compose stop bot\n"
            "  2) docker compose run --rm --no-deps bot python -m nexa.cli\n"
            "     （bot 已停止时不能用 exec，要用 run 开临时菜单）\n"
            "  3) 同步/登录完成后: docker compose start bot"
        )
    return exc if isinstance(exc, Exception) else RuntimeError(str(exc))


async def _resolve_entity(client: TelegramClient, ch: dict[str, Any]) -> Any:
    if ch.get("username"):
        return await client.get_entity(ch["username"])
    tid = int(ch["telegram_id"])
    try:
        return await client.get_entity(tid)
    except Exception:  # noqa: BLE001
        return await client.get_entity(int(f"-100{tid}"))


def _is_broadcast_or_channel(dialog: Dialog) -> bool:
    entity = dialog.entity
    if isinstance(entity, TgChannel):
        return True
    if isinstance(entity, (Chat, User)):
        return False
    return bool(getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False))
