# NexaPulseBot

[![Docker](https://img.shields.io/badge/ghcr.io-kiteyuan%2Fnexapulsebot-blue?logo=docker)](https://github.com/kiteyuan/NexaPulseBot/pkgs/container/nexapulsebot)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)

**English** | [简体中文](./README.zh-CN.md)

Telegram channel monitor → rules / optional LLM review → **self-hosted [ntfy](https://ntfy.sh)** push.  
CLI-only operations. No web admin UI.

```text
Telegram  ──poll──►  SQLite  ──filter / LLM──►  ntfy topics  ──►  phone / desktop
```

## Features

- **Periodic Telegram ingest** — enabled by assigning channels to ntfy topics
- **Dedup & filters** — hash dedup, min length, block keywords
- **LLM gate** — approve / reject, notification title + cleaned body in one call
- **Multi-topic ntfy** — catalog, assign, disable / enable, delete
- **Image posts** — native ntfy uploads (inline preview); multi-image albums supported
- **Docker-first** — pull `ghcr.io/kiteyuan/nexapulsebot`, compose brings up ntfy + bot

## Quick start (Docker Compose)

Minimal files on the server: `docker-compose.yml`, `deploy/`, `ntfy/etc/server.yml.example`.

```bash
mkdir -p config data/media sessions ntfy/cache ntfy/etc ntfy/data
cp -n ntfy/etc/server.yml.example ntfy/etc/ 2>/dev/null || true

docker compose pull
docker compose up -d
```

What happens on first boot:

| Service | Role |
|---------|------|
| `ntfy` | Self-hosted push server (`127.0.0.1:2586`) |
| `ntfy-init` | Creates admin user, token → `ntfy/bot.env`, `ntfy/credentials.txt` |
| `bot` | Generates `config/settings.json` if missing, then runs the worker |

```bash
# Interactive menu (Telegram / topics / LLM)
docker compose exec bot python -m nexa.cli

# Update bot image
docker compose pull bot && docker compose up -d bot

# Stop
docker compose down
```

> Put the GHCR package **Public**, or `docker login ghcr.io` on the server.  
> Override image: `NEXA_IMAGE=ghcr.io/kiteyuan/nexapulsebot:latest`.

Edit `ntfy/etc/server.yml` (`base-url`) for your public domain behind a reverse proxy.

## Architecture

```text
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Telegram   │────►│  NexaPulse   │────►│    ntfy     │
│  channels   │     │  bot + SQLite│     │  (topics)   │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
                    config/settings.json
                    sessions/  data/
```

**Topic model:** a channel is active only when assigned to an ntfy topic.  
Disable a topic to pause poll/push without unbinding channels; delete removes the topic and bindings.

## Configuration

| Location | Purpose |
|----------|---------|
| `config/settings.json` | LLM, ntfy token/topics, filters (volume; not baked into image) |
| `data/nexa.db` | Accounts, channels, message queue, logs |
| `sessions/` | Telethon login sessions |
| `ntfy/` | ntfy config, auth DB, credentials |

Typical menu flow:

1. **Telegram account** — add + QR login *(stop competing session locks: avoid sync/login while another process holds the same `.session`)*  
2. **Telegram channels** — sync list  
3. **ntfy topics** — add topic → assign channels  
4. **LLM** — optional review settings  
5. Subscribe the same topic names in the ntfy app

## Local build / development

```bash
# Build image locally instead of pulling
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build

# Run without Docker
python -m venv .venv && source .venv/bin/activate   # Windows: Scripts\activate
pip install -r requirements.txt
python -m nexa.cli          # menu
python -m nexa.cli run      # workers
```

Images are published by GitHub Actions on `main` / `v*` tags (`linux/amd64`, `linux/arm64`).

## Project layout

```text
nexa/           Application code (telegram, llm, ntfy, cli)
config/         settings example + runtime settings.json
deploy/         compose entrypoint & ntfy-init scripts
ntfy/           Self-hosted ntfy volumes
data/           SQLite + media
sessions/       Telegram sessions
```

## License

[MIT](./LICENSE)
