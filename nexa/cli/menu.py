from __future__ import annotations

"""Interactive menu — explicit top-level sections."""

import argparse
from typing import Optional

from sqlalchemy import select

from nexa.cli import commands
from nexa.cli import display as ui
from nexa.config import TRANSLATE_OPTIONS, load_settings, save_settings
from nexa.database.db import init_db, session_scope
from nexa.database.models import Account, Channel, Message, SendStatus
from nexa.llm.catalog import PROVIDERS
from nexa.ntfy.client import normalize_topic


def _config_ns(**kwargs: object) -> argparse.Namespace:
    base = dict(
        config_cmd="set",
        ntfy_base_url=None,
        ntfy_topic=None,
        ntfy_token=None,
        ntfy_priority=None,
        llm_enabled=None,
        llm_provider=None,
        llm_base_url=None,
        llm_key=None,
        llm_model=None,
        llm_temperature=None,
        llm_translate=None,
        min_length=None,
    )
    base.update(kwargs)
    return argparse.Namespace(**base)


async def run_menu() -> int:
    while True:
        key = ui.pick(
            "主菜单",
            [
                ("account", "Telegram 账号"),
                ("channel", "Telegram 频道"),
                ("topic", "ntfy 主题管理"),
                ("llm", "LLM 设置"),
                ("logs", "查看日志"),
            ],
            back="退出",
        )
        if not key:
            print("再见")
            return 0
        try:
            if key == "account":
                await _menu_account()
            elif key == "channel":
                await _menu_channel()
            elif key == "topic":
                await _menu_topics()
            elif key == "llm":
                await _menu_llm()
            elif key == "logs":
                await _menu_logs()
        except KeyboardInterrupt:
            print("\n已取消")
            ui.clear_pending()
        except Exception as exc:  # noqa: BLE001
            print(f"  · 错误: {exc}")
            ui.pause()


# ── Telegram 账号 ────────────────────────────────────────────────


async def _menu_account() -> None:
    crumb = "主菜单 › Telegram 账号"
    while True:
        key = ui.pick(
            "Telegram 账号",
            [
                ("list", "列出账号"),
                ("add", "添加账号"),
                ("login", "扫码登录"),
                ("delete", "删除账号"),
            ],
            crumb=crumb,
        )
        if not key:
            return
        if key == "list":
            await commands.cmd_account(argparse.Namespace(account_cmd="list"))
            ui.pause()
        elif key == "add":
            name = ui.ask("账号名")
            api_id = ui.ask("API ID")
            api_hash = ui.ask("API Hash")
            if not (name and api_id and api_hash):
                print("  · 三项都必填")
                ui.pause()
                continue
            await commands.cmd_account(
                argparse.Namespace(
                    account_cmd="add",
                    name=name,
                    api_id=int(api_id),
                    api_hash=api_hash,
                )
            )
            ui.pause()
        elif key == "login":
            await commands.cmd_account(argparse.Namespace(account_cmd="list"))
            aid = ui.ask("账号 id")
            if not aid:
                continue
            pwd = ui.ask("2FA 密码（无则回车）", "")
            print("  · 若 bot 在跑请先: docker compose stop bot")
            print("  · 然后: docker compose run --rm --no-deps bot python -m nexa.cli")
            await commands.cmd_account(
                argparse.Namespace(
                    account_cmd="login",
                    account_id=int(aid),
                    password=pwd,
                )
            )
            ui.pause()
        elif key == "delete":
            await commands.cmd_account(argparse.Namespace(account_cmd="list"))
            aid = ui.ask("账号 id")
            if not aid:
                continue
            if ui.ask(f"确认删除 #{aid}？输入 yes", "").lower() != "yes":
                print("  · 已取消")
                ui.pause()
                continue
            await commands.cmd_account(
                argparse.Namespace(account_cmd="delete", account_id=int(aid))
            )
            ui.pause()


# ── Telegram 频道（不再单独启用/禁用：有主题即接入）──────────────


async def _menu_channel() -> None:
    crumb = "主菜单 › Telegram 频道"
    account_id: Optional[int] = None
    while True:
        acc = f"账号 #{account_id}" if account_id else "未选账号"
        key = ui.pick(
            acc,
            [
                ("pick", "切换账号"),
                ("list", "列出频道"),
                ("sync", "同步频道"),
            ],
            crumb=crumb,
        )
        if not key:
            return
        if key == "pick":
            account_id = await _pick_account_id()
            continue

        if account_id is None:
            account_id = await _pick_account_id()
            if account_id is None:
                continue

        if key == "list":
            await commands.cmd_channel(
                argparse.Namespace(channel_cmd="list", account=account_id)
            )
            ui.pause()
        elif key == "sync":
            print("  · 若 bot 在跑请先: docker compose stop bot")
            print("  · 然后: docker compose run --rm --no-deps bot python -m nexa.cli")
            await commands.cmd_channel(
                argparse.Namespace(channel_cmd="sync", account=account_id)
            )
            ui.pause()


async def _pick_account_id() -> Optional[int]:
    settings = load_settings()
    await init_db(settings)
    async with session_scope() as session:
        accounts = list(
            (await session.execute(select(Account).order_by(Account.id))).scalars()
        )
    if not accounts:
        print("  · 还没有账号，先去「Telegram 账号 → 添加」")
        ui.pause()
        return None
    if len(accounts) == 1:
        a = accounts[0]
        print(f"  · 使用账号 #{a.id} {a.name}")
        return a.id
    ui.print_rows(
        ("ID", "名称", "状态", "手机"),
        [(str(a.id), a.name, a.status, a.phone or "-") for a in accounts],
        (4, 16, 10, 16),
    )
    aid = ui.ask("账号 id")
    if not aid:
        return None
    return int(aid)


# ── ntfy 主题管理 ────────────────────────────────────────────────


async def _menu_topics() -> None:
    crumb = "主菜单 › ntfy 主题"
    while True:
        key = ui.pick(
            "ntfy 主题管理",
            [
                ("list", "列出主题"),
                ("add", "添加主题"),
                ("assign", "分配主题"),
                ("disable", "禁用主题"),
                ("enable", "启用主题"),
                ("delete", "删除主题"),
                ("acl", "ntfy 主题鉴权"),
                ("conn", "ntfy 连接测试"),
                ("send", "ntfy 推送测试"),
                ("ntfy", "ntfy 连接设置"),
            ],
            crumb=crumb,
        )
        if not key:
            return
        if key == "list":
            await _list_topics()
            ui.pause()
        elif key == "add":
            await _add_topic()
        elif key == "assign":
            await _assign_topic()
        elif key == "disable":
            await _disable_topic()
        elif key == "enable":
            await _enable_topic()
        elif key == "delete":
            await _delete_topic()
        elif key == "acl":
            await _menu_topic_acl()
        elif key == "conn":
            await commands.cmd_ntfy(argparse.Namespace(ntfy_cmd="test"))
            ui.pause()
        elif key == "send":
            await _list_topics()
            topic = await _pick_topic_name(allow_empty=False, only_active=True)
            if not topic:
                continue
            await commands.cmd_ntfy(
                argparse.Namespace(ntfy_cmd="send-test", topic=topic)
            )
            ui.pause()
        elif key == "ntfy":
            s = load_settings()
            base = ui.ask("地址", s.ntfy.base_url or "http://127.0.0.1:2586")
            token = ui.ask("Token（回车保持）", "")
            pri = ui.ask("优先级 1-5", str(s.ntfy.priority or 3))
            await commands.cmd_config(
                _config_ns(
                    ntfy_base_url=base,
                    ntfy_token=token if token else None,
                    ntfy_priority=int(pri) if pri else None,
                )
            )
            ui.pause()


async def _menu_topic_acl() -> None:
    """Control anonymous (*) ACL per topic via ntfy access."""
    from nexa.ntfy import acl as ntfy_acl

    crumb = "主菜单 › ntfy 主题 › 鉴权"
    while True:
        key = ui.pick(
            "ntfy 主题鉴权",
            [
                ("list", "查看当前 ACL"),
                ("set", "设置主题游客权限"),
            ],
            crumb=crumb,
        )
        if not key:
            return
        if key == "list":
            ok, out = ntfy_acl.list_access()
            print()
            print(out if out else "（无输出）")
            if not ok:
                print("  · 失败：见上方说明")
            ui.pause()
        elif key == "set":
            await _set_topic_guest_acl()


async def _set_topic_guest_acl() -> None:
    from nexa.ntfy import acl as ntfy_acl

    topic = await _pick_topic_name(allow_empty=False)
    if not topic:
        return

    ok, acl_text = ntfy_acl.list_access()
    current = ntfy_acl.parse_guest_mode_from_acl(acl_text, topic) if ok else None
    if current:
        print(f"  · 主题「{topic}」游客当前: {ntfy_acl.guest_mode_label(current)}")
    elif ok:
        print(f"  · 主题「{topic}」游客当前: 跟随服务器默认（多为 deny-all）")

    print("\n  说明: 只改匿名用户(*)；Bot 仍用 Token 发帖，不受游客权限影响。")
    print("  服务器默认一般为 deny-all，未单独放行的主题游客不可访问。\n")

    modes = list(ntfy_acl.GUEST_MODES.items())
    options = [(code, f"{label} — {desc}") for code, (label, desc) in modes]
    mode = ui.pick("游客权限", options, crumb=f"主题 {topic}")
    if not mode:
        return

    ok, out = ntfy_acl.set_guest_access(topic, mode)
    print()
    if out:
        print(out)
    if ok:
        print(f"  · 已设置「{topic}」→ {ntfy_acl.guest_mode_label(mode)}")
    else:
        print("  · 设置失败")
    ui.pause()


async def _sync_topic_catalog() -> list[str]:
    """Merge settings.topics with topics already used by channels; persist."""
    settings = load_settings()
    await init_db(settings)
    catalog = [normalize_topic(t) for t in (settings.ntfy.topics or []) if normalize_topic(t)]
    async with session_scope() as session:
        used = list((await session.execute(select(Channel.ntfy_topic))).scalars())
    for t in used:
        name = normalize_topic(t or "")
        if name and name not in catalog:
            catalog.append(name)
    # stable unique
    seen: list[str] = []
    for t in catalog:
        if t not in seen:
            seen.append(t)
    if seen != list(settings.ntfy.topics or []):
        settings.ntfy.topics = seen
        save_settings(settings)
    return seen


async def _list_topics() -> None:
    topics = await _sync_topic_catalog()
    settings = load_settings()
    await init_db(settings)
    disabled = {
        normalize_topic(t) for t in (settings.ntfy.disabled_topics or []) if normalize_topic(t)
    }
    async with session_scope() as session:
        channels = list(
            (await session.execute(select(Channel).order_by(Channel.id))).scalars()
        )

    if not topics:
        print("  · 还没有主题，先「添加主题」")
        return

    print("  说明: 分配到主题的频道才会采集；禁用主题会暂停采集/推送，绑定保留\n")
    for name in topics:
        members = [c for c in channels if normalize_topic(c.ntfy_topic or "") == name]
        state = "禁用" if name in disabled else "启用"
        print(f"  [{name}]  {state}  ·  {len(members)} 个频道")
        if not members:
            print("    （空）")
            continue
        for c in members:
            label = f"@{c.username}" if c.username else (c.title or str(c.telegram_id))
            print(f"    #{c.id}  {ui.trunc(label, 36)}")


async def _add_topic() -> None:
    topics = await _sync_topic_catalog()
    if topics:
        print("  已有: " + ", ".join(topics))
    name = normalize_topic(ui.ask("新主题名（如 ai / solidot）"))
    if not name:
        print("  · 未填写")
        ui.pause()
        return
    if name in topics:
        print(f"  · 主题「{name}」已存在")
        ui.pause()
        return
    settings = load_settings()
    settings.ntfy.topics = list(topics) + [name]
    # ensure not left in disabled by accident
    settings.ntfy.disabled_topics = [
        t for t in (settings.ntfy.disabled_topics or []) if normalize_topic(t) != name
    ]
    save_settings(settings)
    print(f"  · 已添加主题「{name}」—— 接下来去「分配主题」绑频道")
    ui.pause()


async def _pick_topic_name(
    *,
    allow_empty: bool,
    only_active: bool = False,
    only_disabled: bool = False,
) -> str:
    topics = await _sync_topic_catalog()
    settings = load_settings()
    disabled = {
        normalize_topic(t) for t in (settings.ntfy.disabled_topics or []) if normalize_topic(t)
    }
    choices = topics
    if only_active:
        choices = [t for t in topics if t not in disabled]
    if only_disabled:
        choices = [t for t in topics if t in disabled]
    if not choices:
        print("  · 没有可选主题")
        ui.pause()
        return ""
    print("  主题:")
    for i, name in enumerate(choices, start=1):
        mark = " [禁用]" if name in disabled else ""
        print(f"    {i}. {name}{mark}")
    raw = ui.ask("选编号或输入名称" + ("（回车取消）" if allow_empty else ""))
    if not raw:
        return ""
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(choices):
            return choices[idx - 1]
    name = normalize_topic(raw)
    if name not in choices:
        print(f"  · 主题「{name}」不在可选列表")
        ui.pause()
        return ""
    return name


async def _assign_topic() -> None:
    topic = await _pick_topic_name(allow_empty=False)
    if not topic:
        return
    account_id = await _pick_account_id()
    if account_id is None:
        return
    await commands.cmd_channel(
        argparse.Namespace(channel_cmd="list", account=account_id)
    )
    ids = ui.ask(f"将哪些频道分配到「{topic}」（id 逗号分隔）")
    if not ids:
        return
    await commands.cmd_channel(
        argparse.Namespace(
            channel_cmd="topic",
            account=account_id,
            ids=ids,
            topic=topic,
        )
    )
    print("  · 已分配（这些频道将开始采集推送；需 bot 在跑）")
    ui.pause()


async def _disable_topic() -> None:
    topic = await _pick_topic_name(allow_empty=False, only_active=True)
    if not topic:
        return
    settings = load_settings()
    disabled = [
        normalize_topic(t) for t in (settings.ntfy.disabled_topics or []) if normalize_topic(t)
    ]
    if topic not in disabled:
        disabled.append(topic)
    settings.ntfy.disabled_topics = disabled
    save_settings(settings)
    print(f"  · 已禁用「{topic}」（频道绑定保留，暂停采集/推送）")
    print("  · 恢复请用「启用主题」")
    ui.pause()


async def _enable_topic() -> None:
    topic = await _pick_topic_name(allow_empty=False, only_disabled=True)
    if not topic:
        return
    settings = load_settings()
    settings.ntfy.disabled_topics = [
        normalize_topic(t)
        for t in (settings.ntfy.disabled_topics or [])
        if normalize_topic(t) and normalize_topic(t) != topic
    ]
    save_settings(settings)
    print(f"  · 已启用「{topic}」")
    ui.pause()


async def _delete_topic() -> None:
    """Remove topic from catalog and clear all channel bindings."""
    topic = await _pick_topic_name(allow_empty=False)
    if not topic:
        return
    settings = load_settings()
    await init_db(settings)
    async with session_scope() as session:
        members = list(
            (
                await session.execute(
                    select(Channel).where(Channel.ntfy_topic == topic)
                )
            ).scalars()
        )
    print(f"  将删除主题「{topic}」")
    if members:
        print(f"  并解除 {len(members)} 个频道的绑定:")
        for c in members:
            label = f"@{c.username}" if c.username else (c.title or str(c.telegram_id))
            print(f"    #{c.id}  {ui.trunc(label, 36)}")
    if ui.ask("确认删除？输入 yes", "").lower() != "yes":
        print("  · 已取消")
        ui.pause()
        return

    by_account: dict[int, list[str]] = {}
    for c in members:
        by_account.setdefault(c.account_id, []).append(str(c.id))
    for account_id, cids in by_account.items():
        await commands.cmd_channel(
            argparse.Namespace(
                channel_cmd="topic",
                account=account_id,
                ids=",".join(cids),
                topic="",
            )
        )

    topics = await _sync_topic_catalog()
    settings = load_settings()
    settings.ntfy.topics = [t for t in topics if t != topic]
    settings.ntfy.disabled_topics = [
        normalize_topic(t)
        for t in (settings.ntfy.disabled_topics or [])
        if normalize_topic(t) and normalize_topic(t) != topic
    ]
    save_settings(settings)
    print(f"  · 已删除主题「{topic}」")
    ui.pause()


# ── LLM 设置 ─────────────────────────────────────────────────────


async def _menu_llm() -> None:
    crumb = "主菜单 › LLM 设置"
    while True:
        s = load_settings()
        tr = (s.llm.translate_to or "off").strip().lower()
        tr_label = TRANSLATE_OPTIONS.get(tr, tr)
        key = ui.pick(
            "LLM 设置",
            [
                ("config", "LLM 配置"),
                ("translate", f"LLM 翻译（当前：{tr_label}）"),
                ("filter", "过滤规则"),
                ("test", "LLM 连接测试"),
            ],
            crumb=crumb,
        )
        if not key:
            return
        if key == "config":
            await _llm_config()
        elif key == "translate":
            await _llm_translate()
        elif key == "filter":
            await _filter_config()
        elif key == "test":
            await commands.cmd_llm(argparse.Namespace(llm_cmd="test"))
            ui.pause()


async def _llm_translate() -> None:
    s = load_settings()
    current = (s.llm.translate_to or "off").strip().lower()
    options = list(TRANSLATE_OPTIONS.items())
    print("\n  推送语言（审核通过后：清广告 + 译为目标语言；专有名词保留原文）:")
    for i, (code, label) in enumerate(options, start=1):
        mark = " ←" if code == current else ""
        print(f"    {i}. {label} ({code}){mark}")
    pick = ui.ask("编号", "")
    if not pick.isdigit():
        print("  · 已取消")
        ui.pause()
        return
    idx = int(pick)
    if not (1 <= idx <= len(options)):
        print("  · 无效编号")
        ui.pause()
        return
    code = options[idx - 1][0]
    await commands.cmd_config(_config_ns(llm_translate=code))
    ui.pause()


async def _llm_config() -> None:
    s = load_settings()
    print("\n  厂商:")
    for i, p in enumerate(PROVIDERS, start=1):
        print(f"    {i}. {p.label}")
    pick = ui.ask("厂商编号（回车跳过）", "")
    provider = s.llm.provider
    base_url = s.llm.base_url
    model = s.llm.model
    if pick.isdigit():
        idx = int(pick)
        if 1 <= idx <= len(PROVIDERS):
            preset = PROVIDERS[idx - 1]
            provider = preset.key
            if preset.base_url:
                base_url = preset.base_url
            if preset.models:
                print("  模型:")
                for j, m in enumerate(preset.models, start=1):
                    print(f"    {j}. {m}")
                mp = ui.ask("模型编号或名称", preset.models[0])
                if mp.isdigit() and 1 <= int(mp) <= len(preset.models):
                    model = preset.models[int(mp) - 1]
                else:
                    model = mp or preset.models[0]
    enabled = ui.ask("启用 LLM？ true/false", "true" if s.llm.enabled else "false")
    base_url = ui.ask("Base URL", base_url)
    key = ui.ask("API Key（回车保持）", "")
    model = ui.ask("Model", model)
    temp = ui.ask("Temperature", str(s.llm.temperature))
    await commands.cmd_config(
        _config_ns(
            llm_enabled=enabled,
            llm_provider=provider,
            llm_base_url=base_url,
            llm_key=key if key else None,
            llm_model=model,
            llm_temperature=float(temp),
        )
    )
    ui.pause()


async def _filter_config() -> None:
    s = load_settings()
    ml = ui.ask("最短字数", str(s.filter.min_length))
    kw = ui.ask(
        "屏蔽关键词（逗号分隔）",
        ",".join(s.filter.block_keywords or []),
    )
    s.filter.min_length = int(ml)
    s.filter.block_keywords = [x.strip() for x in kw.split(",") if x.strip()]
    save_settings(s)
    print("  · 已保存过滤规则")
    ui.pause()


# ── 查看日志 ─────────────────────────────────────────────────────


async def _menu_logs() -> None:
    crumb = "主菜单 › 日志"
    while True:
        key = ui.pick(
            "查看日志",
            [
                ("status", "状态总览"),
                ("logs", "最近日志"),
                ("requeue", "重发失败"),
            ],
            crumb=crumb,
        )
        if not key:
            return
        if key == "status":
            await commands.cmd_status(argparse.Namespace())
            ui.pause()
        elif key == "logs":
            limit = ui.ask("条数", "50")
            await commands.cmd_logs(argparse.Namespace(limit=int(limit or 50)))
            ui.pause()
        elif key == "requeue":
            await _requeue_failed()
            ui.pause()


async def _requeue_failed() -> None:
    settings = load_settings()
    await init_db(settings)
    async with session_scope() as session:
        result = await session.execute(
            select(Message).where(Message.send_status == SendStatus.FAILED.value)
        )
        rows = list(result.scalars().all())
        if not rows:
            print("  · 没有 failed 消息")
            return
        print(f"  · 将重发 {len(rows)} 条 failed → ready")
        if ui.ask("确认？输入 yes", "").lower() != "yes":
            print("  · 已取消")
            return
        for msg in rows:
            msg.send_status = SendStatus.READY.value
            msg.error_message = None
    print("  · 已入队")
