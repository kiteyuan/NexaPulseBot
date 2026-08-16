# NexaPulseBot

[![Docker](https://img.shields.io/badge/ghcr.io-kiteyuan%2Fnexapulsebot-blue?logo=docker)](https://github.com/kiteyuan/NexaPulseBot/pkgs/container/nexapulsebot)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)

[English](./README.md) | **简体中文**

Telegram 频道采集 → 规则 / 可选 LLM 审核 → **自建 [ntfy](https://ntfy.sh)** 推送。  
纯终端 CLI 管理，无 Web 后台。

```text
Telegram  ──轮询──►  SQLite  ──过滤 / LLM──►  ntfy 主题  ──►  手机 / 桌面
```

## 特性

- **定时采集 Telegram** — 频道分配到 ntfy 主题后即开始采集
- **去重与过滤** — 文本 hash、最短字数、屏蔽词
- **LLM 审核** — 一次调用完成通过/拒绝、通知标题与正文清理
- **多主题 ntfy** — 主题清单、分配、禁用/启用、删除
- **图文推送** — ntfy 原生传图（便于内嵌预览），支持多图
- **Docker 优先** — 拉取 `ghcr.io/kiteyuan/nexapulsebot`，compose 一键起 ntfy + bot

## 快速开始（Docker Compose）

服务器至少准备：`docker-compose.yml`、`deploy/`、`ntfy/etc/server.yml.example`。

```bash
mkdir -p config data/media sessions ntfy/cache ntfy/etc ntfy/data
cp -n ntfy/etc/server.yml.example ntfy/etc/ 2>/dev/null || true

docker compose pull
docker compose up -d
```

首次启动会：

| 服务 | 作用 |
|------|------|
| `ntfy` | 自建推送服务（`127.0.0.1:2586`） |
| `ntfy-init` | 创建管理员与 Token → `ntfy/bot.env`、`ntfy/credentials.txt` |
| `bot` | 若无 `settings.json` 则自动生成，然后跑采集/推送 |

```bash
# 交互菜单（账号 / 主题 / LLM）
# bot 在跑时：
docker compose exec bot python -m nexa.cli
# 已 stop bot（登录/同步要独占 session）时：
docker compose run --rm --no-deps bot python -m nexa.cli

# 更新 bot 镜像
docker compose pull bot && docker compose up -d bot

# 停止
docker compose down
```

> 请将 GHCR 包设为 **Public**，或在服务器执行 `docker login ghcr.io`。  
> 自定义镜像：`NEXA_IMAGE=ghcr.io/kiteyuan/nexapulsebot:latest`。

公网反代时请修改 `ntfy/etc/server.yml` 中的 `base-url`。

## 架构

```text
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Telegram   │────►│  NexaPulse   │────►│    ntfy     │
│  频道       │     │  bot + SQLite│     │  （多主题） │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
                    config/settings.json
                    sessions/  data/
```

**主题模型：** 只有分配了 ntfy 主题的频道才会采集。  
**禁用主题** 暂停采集/推送但保留绑定；**删除主题** 会解除绑定并移除清单。

## 配置说明

| 位置 | 用途 |
|------|------|
| `config/settings.json` | LLM、ntfy Token/主题清单、过滤规则（挂载，不打进镜像） |
| `data/nexa.db` | 账号、频道、消息队列、日志 |
| `sessions/` | Telethon 登录态 |
| `ntfy/` | ntfy 配置、鉴权库、凭据 |

推荐菜单流程：

1. **Telegram 账号** — 添加并扫码登录（同步/登录时勿与正在占用同一 session 的 bot 进程冲突）  
2. **Telegram 频道** — 同步列表  
3. **ntfy 主题管理** — 添加主题 → 分配频道  
4. **LLM 审核设置** — 可选  
5. 手机 ntfy App 订阅同名主题  

## 本地构建 / 开发

```bash
# 不用预构建镜像，本地 build
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build

# 不用 Docker
python -m venv .venv && source .venv/bin/activate   # Windows: Scripts\activate
pip install -r requirements.txt
python -m nexa.cli          # 菜单
python -m nexa.cli run      # 前台跑采集+推送
```

推送到 `main` / `v*` tag 时，GitHub Actions 会构建并发布 `linux/amd64`、`linux/arm64` 镜像。

## 目录结构

```text
nexa/           业务代码（telegram / llm / ntfy / cli）
config/         配置示例与运行时 settings.json
deploy/         compose 入口与 ntfy-init 脚本
ntfy/           自建 ntfy 数据与配置
data/           SQLite + 媒体
sessions/       Telegram session
```

## 许可证

[MIT](./LICENSE)
