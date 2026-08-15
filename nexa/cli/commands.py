from __future__ import annotations

import asyncio
import json
import os
import subprocess
from typing import Any

import qrcode
from sqlalchemy import select

from nexa.config import SETTINGS_PATH, load_settings, save_settings
from nexa.database.db import fetch_logs, init_db, session_scope
from nexa.database.models import Account, Channel, Message, SendStatus
from nexa.llm.catalog import PROVIDERS, provider_key_for_save
from nexa.llm.client import LLMClient
from nexa.ntfy import NtfyClient
from nexa.runtime import AppRuntime
from nexa.telegram import TelethonListener, create_account, delete_account
from nexa.timeutil import to_utc_iso


def _parse_ids(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    if not out:
        raise ValueError("未提供有效 id")
    return out


def _print_qr(url: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    print("\n请用手机 Telegram：设置 → 设备 → 连接桌面设备 → 扫码\n")
    qr.print_ascii(invert=True)
    print(f"\n若无法扫码，打开链接: {url}\n")


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


async def cmd_run(_args: Any) -> int:
    runtime = AppRuntime()
    await runtime.start()
    print("服务已启动（TG 半小时轮询 / 处理 / ntfy 推送）。Ctrl+C 退出。")
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runtime.shutdown()
        print("服务已停止")
    return 0


async def cmd_status(_args: Any) -> int:
    settings = load_settings()
    await init_db(settings)
    async with session_scope() as session:
        accounts = list(
            (await session.execute(select(Account).order_by(Account.id))).scalars()
        )
        channels = list(
            (
                await session.execute(
                    select(Channel)
                    .where(Channel.ntfy_topic != "")
                    .order_by(Channel.id)
                )
            ).scalars()
        )
        ready = list(
            (
                await session.execute(
                    select(Message.id).where(Message.send_status == SendStatus.READY.value)
                )
            ).scalars()
        )
        failed = list(
            (
                await session.execute(
                    select(Message.id).where(Message.send_status == SendStatus.FAILED.value)
                )
            ).scalars()
        )

    print("── 配置")
    topics = ", ".join(settings.ntfy.topics) if settings.ntfy.topics else "（无）"
    print(f"  ntfy  {settings.ntfy.base_url}  prio={settings.ntfy.priority}")
    print(f"  主题  {topics}")
    print(
        f"  LLM   enabled={settings.llm.enabled}  "
        f"{settings.llm.provider}/{settings.llm.model}"
    )
    print("── 账号")
    if not accounts:
        print("  （无）")
    else:
        from nexa.cli.display import print_rows

        print_rows(
            ("ID", "名称", "状态", "手机", "同步"),
            [
                (
                    str(a.id),
                    a.name,
                    a.status,
                    a.phone or "-",
                    (to_utc_iso(a.last_sync) or "-")[:19],
                )
                for a in accounts
            ],
            (4, 12, 8, 14, 19),
        )
    print("── 已分配主题的频道")
    if not channels:
        print("  （无）")
    else:
        from nexa.cli.display import channel_label, print_rows

        print_rows(
            ("ID", "频道", "主题"),
            [
                (
                    str(c.id),
                    channel_label(c.username, c.title, int(c.telegram_id)),
                    (c.ntfy_topic or "").strip() or "-",
                )
                for c in channels
            ],
            (4, 28, 16),
        )
    print(f"── 队列  ready={len(ready)}  failed={len(failed)}")
    return 0


async def cmd_config(args: Any) -> int:
    if args.config_cmd == "show":
        settings = load_settings()
        data = settings.model_dump()
        if data.get("llm", {}).get("api_key"):
            data["llm"]["api_key"] = "***"
        if data.get("ntfy", {}).get("token"):
            data["ntfy"]["token"] = "***"
        print(_json(data))
        print(f"\n文件: {SETTINGS_PATH}")
        return 0

    if args.config_cmd == "edit":
        load_settings()
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
        return int(subprocess.call([editor, str(SETTINGS_PATH)]))

    if args.config_cmd == "set":
        settings = load_settings()
        changed: list[str] = []
        if getattr(args, "ntfy_base_url", None) is not None:
            settings.ntfy.base_url = args.ntfy_base_url.strip()
            changed.append("ntfy.base_url")
        if getattr(args, "ntfy_topic", None) is not None:
            from nexa.ntfy.client import normalize_topic

            name = normalize_topic(args.ntfy_topic)
            if name and name not in settings.ntfy.topics:
                settings.ntfy.topics = list(settings.ntfy.topics) + [name]
                changed.append("ntfy.topics")
        if getattr(args, "ntfy_token", None) is not None:
            settings.ntfy.token = args.ntfy_token.strip()
            changed.append("ntfy.token")
        if getattr(args, "ntfy_priority", None) is not None:
            settings.ntfy.priority = int(args.ntfy_priority)
            changed.append("ntfy.priority")
        if args.llm_enabled is not None:
            settings.llm.enabled = args.llm_enabled == "true"
            changed.append("llm.enabled")
        if args.llm_provider is not None:
            settings.llm.provider = provider_key_for_save(args.llm_provider)
            changed.append("llm.provider")
        if args.llm_base_url is not None:
            settings.llm.base_url = args.llm_base_url.strip()
            changed.append("llm.base_url")
        if args.llm_key is not None:
            settings.llm.api_key = args.llm_key.strip()
            changed.append("llm.api_key")
        if args.llm_model is not None:
            settings.llm.model = args.llm_model.strip()
            changed.append("llm.model")
        if args.llm_temperature is not None:
            settings.llm.temperature = float(args.llm_temperature)
            changed.append("llm.temperature")
        if args.min_length is not None:
            settings.filter.min_length = int(args.min_length)
            changed.append("filter.min_length")
        if not changed:
            print("未指定修改项。示例:")
            print(
                "  python -m nexa.cli config set "
                "--ntfy-base-url http://127.0.0.1:2586 --ntfy-topic tech"
            )
            return 2
        save_settings(settings)
        print("已保存: " + ", ".join(changed))
        return 0

    return 2


async def cmd_account(args: Any) -> int:
    settings = load_settings()
    await init_db(settings)

    if args.account_cmd == "list":
        async with session_scope() as session:
            rows = list(
                (await session.execute(select(Account).order_by(Account.id))).scalars()
            )
        if not rows:
            print("  （无账号）")
            return 0
        from nexa.cli.display import print_rows

        print_rows(
            ("ID", "名称", "状态", "手机", "同步"),
            [
                (
                    str(a.id),
                    a.name,
                    a.status,
                    a.phone or "-",
                    (to_utc_iso(a.last_sync) or "-")[:19],
                )
                for a in rows
            ],
            (4, 12, 8, 14, 19),
        )
        return 0

    if args.account_cmd == "add":
        acc = await create_account(
            name=args.name.strip(),
            api_id=int(args.api_id),
            api_hash=args.api_hash.strip(),
            settings=settings,
        )
        print(f"已添加账号 #{acc.id} {acc.name}")
        return 0

    if args.account_cmd == "login":
        return await _login_qr(int(args.account_id), password=args.password or "")

    if args.account_cmd == "delete":
        name = await delete_account(int(args.account_id), settings=settings)
        print(f"已删除账号 #{args.account_id} {name}")
        print("若服务在跑，请 docker compose restart bot")
        return 0

    return 2


async def _login_qr(account_id: int, *, password: str) -> int:
    settings = load_settings()
    await init_db(settings)
    listener = TelethonListener(settings)
    try:
        url = await listener.begin_qr_login(account_id)
    except Exception as exc:  # noqa: BLE001
        print(f"无法开始扫码: {exc}")
        return 1

    _print_qr(url)
    print("等待扫码…（超时会自动刷新二维码）")

    while True:
        status = await listener.wait_qr_login(
            account_id,
            password=password or None,
            timeout=25.0,
        )
        if status == "ok":
            print("登录成功")
            return 0
        if status == "need_2fa":
            pwd = password
            if not pwd:
                pwd = input("需要两步验证密码，请输入后回车: ").strip()
            if not pwd:
                print("未输入密码")
                return 1
            try:
                await listener.submit_qr_2fa(account_id, pwd)
                print("登录成功（2FA）")
                return 0
            except Exception as exc:  # noqa: BLE001
                print(f"2FA 失败: {exc}")
                return 1
        try:
            url = await listener.refresh_qr_login(account_id)
            print("二维码已刷新，请重新扫码")
            _print_qr(url)
        except Exception as exc:  # noqa: BLE001
            print(f"刷新二维码失败: {exc}")
            return 1


async def _list_channels(account_id: int) -> None:
    from nexa.cli.display import channel_label, print_rows

    async with session_scope() as session:
        rows = list(
            (
                await session.execute(
                    select(Channel)
                    .where(Channel.account_id == account_id)
                    .order_by(Channel.id)
                )
            ).scalars()
        )
    if not rows:
        print("  （无频道，先同步）")
        return
    print(f"  账号 #{account_id}  · 有主题 = 已接入推送")
    print_rows(
        ("ID", "频道", "主题"),
        [
            (
                str(c.id),
                channel_label(c.username, c.title, int(c.telegram_id)),
                (c.ntfy_topic or "").strip() or "-",
            )
            for c in rows
        ],
        (4, 28, 16),
    )


async def cmd_channel(args: Any) -> int:
    settings = load_settings()
    await init_db(settings)
    account_id = int(args.account)

    if args.channel_cmd == "list":
        await _list_channels(account_id)
        return 0

    if args.channel_cmd == "sync":
        listener = TelethonListener(settings)
        synced = await listener.sync_channels(account_id)
        print(f"已同步 {len(synced)} 个频道")
        await _list_channels(account_id)
        return 0

    if args.channel_cmd == "topic":
        from nexa.ntfy.client import normalize_topic

        ids = _parse_ids(args.ids)
        topic = normalize_topic(args.topic)
        async with session_scope() as session:
            for cid in ids:
                ch = await session.get(Channel, cid)
                if ch is None or ch.account_id != account_id:
                    print(f"跳过无效 id #{cid}")
                    continue
                ch.ntfy_topic = topic
                ch.enabled = bool(topic)
                print(f"#{cid} → {topic or '（已取消主题）'}")
        await _list_channels(account_id)
        return 0

    return 2


async def cmd_ntfy(args: Any) -> int:
    settings = load_settings()
    client = NtfyClient(settings.ntfy)
    if args.ntfy_cmd == "test":
        ok, msg = await client.test_auth()
        print(("OK: " if ok else "FAIL: ") + msg)
        return 0 if ok else 1
    if args.ntfy_cmd == "send-test":
        topic = getattr(args, "topic", "") or ""
        ok, msg = await client.test_send(topic=topic)
        print(("OK: " if ok else "FAIL: ") + msg)
        return 0 if ok else 1
    return 2


async def cmd_llm(args: Any) -> int:
    settings = load_settings()
    if args.llm_cmd == "providers":
        for p in PROVIDERS:
            print(f"{p.key}\t{p.label}\t{p.base_url}")
            if p.models:
                more = "…" if len(p.models) > 6 else ""
                print("  models: " + ", ".join(p.models[:6]) + more)
        return 0
    if args.llm_cmd == "test":
        client = LLMClient(settings.llm)
        ok, msg = await client.test_connection()
        print(("OK: " if ok else "FAIL: ") + msg)
        return 0 if ok else 1
    return 2


async def cmd_logs(args: Any) -> int:
    settings = load_settings()
    await init_db(settings)
    rows = await fetch_logs(limit=int(args.limit))
    for r in rows:
        ts = to_utc_iso(r.created_at) or ""
        print(f"[{ts}] {r.level} {r.source}: {r.message}")
    return 0
