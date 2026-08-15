from __future__ import annotations

import argparse
import json
from typing import Any

from nexa.cli import commands


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nexa",
        description="NexaPulseBot 终端控制台（配置 / 登录 / 启停）",
    )
    sub = p.add_subparsers(dest="command")

    sub.add_parser("run", help="前台运行采集+推送")

    sub.add_parser("status", help="查看运行相关状态（账号/频道/队列）")

    cfg = sub.add_parser("config", help="查看或修改 settings.json")
    cfg_sub = cfg.add_subparsers(dest="config_cmd", required=True)
    cfg_sub.add_parser("show", help="打印当前配置")
    cfg_set = cfg_sub.add_parser("set", help="修改配置项")
    cfg_set.add_argument("--ntfy-base-url")
    cfg_set.add_argument("--ntfy-topic", help="向主题清单追加一个主题名")
    cfg_set.add_argument("--ntfy-token")
    cfg_set.add_argument("--ntfy-priority", type=int)
    cfg_set.add_argument("--llm-enabled", choices=["true", "false"])
    cfg_set.add_argument("--llm-provider")
    cfg_set.add_argument("--llm-base-url")
    cfg_set.add_argument("--llm-key")
    cfg_set.add_argument("--llm-model")
    cfg_set.add_argument("--llm-temperature", type=float)
    cfg_set.add_argument("--min-length", type=int)
    cfg_sub.add_parser("edit", help="用 $EDITOR 打开 settings.json")

    acc = sub.add_parser("account", help="Telegram 账号")
    acc_sub = acc.add_subparsers(dest="account_cmd", required=True)
    acc_sub.add_parser("list", help="列出账号")
    acc_add = acc_sub.add_parser("add", help="添加账号")
    acc_add.add_argument("--name", required=True)
    acc_add.add_argument("--api-id", type=int, required=True)
    acc_add.add_argument("--api-hash", required=True)
    acc_login = acc_sub.add_parser("login", help="终端扫码登录")
    acc_login.add_argument("--id", type=int, required=True, dest="account_id")
    acc_login.add_argument("--password", default="", help="2FA 云密码（如有）")
    acc_del = acc_sub.add_parser("delete", help="删除账号")
    acc_del.add_argument("--id", type=int, required=True, dest="account_id")

    ch = sub.add_parser("channel", help="Telegram 频道")
    ch_sub = ch.add_subparsers(dest="channel_cmd", required=True)
    ch_list = ch_sub.add_parser("list", help="列出频道")
    ch_list.add_argument("--account", type=int, required=True)
    ch_sync = ch_sub.add_parser("sync", help="从 TG 同步频道列表")
    ch_sync.add_argument("--account", type=int, required=True)
    ch_topic = ch_sub.add_parser("topic", help="分配/取消频道 ntfy 主题")
    ch_topic.add_argument("--account", type=int, required=True)
    ch_topic.add_argument("--ids", required=True, help="逗号分隔 channel 表 id")
    ch_topic.add_argument("--topic", required=True, help="主题名；空字符串=取消分配")

    ntfy = sub.add_parser("ntfy", help="ntfy 推送")
    ntfy_sub = ntfy.add_subparsers(dest="ntfy_cmd", required=True)
    ntfy_sub.add_parser("test", help="测试 ntfy 可达性")
    ntfy_send = ntfy_sub.add_parser("send-test", help="向指定 topic 发一条测试推送")
    ntfy_send.add_argument("--topic", required=True, help="ntfy 主题名")

    llm = sub.add_parser("llm", help="LLM")
    llm_sub = llm.add_subparsers(dest="llm_cmd", required=True)
    llm_sub.add_parser("test", help="测试 LLM 连接")
    llm_sub.add_parser("providers", help="列出内置厂商预设")

    logs = sub.add_parser("logs", help="打印最近运行日志")
    logs.add_argument("--limit", type=int, default=50)

    sub.add_parser("menu", help="交互式菜单（默认）")

    return p


async def dispatch(args: argparse.Namespace) -> int:
    cmd = args.command
    if cmd in (None, "menu"):
        from nexa.cli.menu import run_menu

        return await run_menu()
    if cmd == "run":
        return await commands.cmd_run(args)
    if cmd == "status":
        return await commands.cmd_status(args)
    if cmd == "config":
        return await commands.cmd_config(args)
    if cmd == "account":
        return await commands.cmd_account(args)
    if cmd == "channel":
        return await commands.cmd_channel(args)
    if cmd == "ntfy":
        return await commands.cmd_ntfy(args)
    if cmd == "llm":
        return await commands.cmd_llm(args)
    if cmd == "logs":
        return await commands.cmd_logs(args)
    print(f"未知命令: {cmd}")
    return 2


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
