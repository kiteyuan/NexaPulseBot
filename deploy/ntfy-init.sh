#!/bin/sh
# One-shot ntfy bootstrap for docker compose (no host docker exec needed).
set -eu

MARKER="/ntfy-host/data/.auth_bootstrapped"
BOT_ENV="/ntfy-host/bot.env"
CREDS="/ntfy-host/credentials.txt"
SETTINGS="/config/settings.json"
ETC="/etc/ntfy"

mkdir -p /ntfy-host/data /ntfy-host/cache /ntfy-host/etc /config \
  /var/cache/ntfy/attachments /var/lib/ntfy

# Ensure server.yml
if [ ! -f "$ETC/server.yml" ]; then
  if [ -f "$ETC/server.yml.example" ]; then
    cp "$ETC/server.yml.example" "$ETC/server.yml"
    echo "已生成 ntfy/etc/server.yml"
  elif [ -f /ntfy-host/etc/server.yml.example ]; then
    cp /ntfy-host/etc/server.yml.example "$ETC/server.yml"
    echo "已生成 ntfy/etc/server.yml"
  else
    echo "错误: 找不到 server.yml.example" >&2
    exit 1
  fi
fi

# Ensure bot.env exists (compose may reference it)
if [ ! -f "$BOT_ENV" ]; then
  printf 'NEXA_NTFY_TOKEN=\n' > "$BOT_ENV"
fi

if [ -f "$MARKER" ]; then
  echo "ntfy 鉴权已初始化，跳过"
  exit 0
fi

echo "等待 ntfy 就绪…"
i=0
while [ "$i" -lt 60 ]; do
  if ntfy user list >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 1
done

if ! ntfy user list >/dev/null 2>&1; then
  echo "警告: ntfy 未就绪，跳过鉴权初始化（可稍后 docker compose run --rm ntfy-init）" >&2
  exit 0
fi

USER_NAME="nexa"
PASS="$(openssl rand -hex 16 2>/dev/null || head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"

if ntfy user list 2>/dev/null | grep -qE "^${USER_NAME}[[:space:]]|user:[[:space:]]*${USER_NAME}"; then
  PASS="(已存在用户，密码未重置；见 credentials.txt 或自行 ntfy user change-pass)"
else
  NTFY_PASSWORD="$PASS" ntfy user add --role=admin "$USER_NAME" >/dev/null
fi

ntfy access "$USER_NAME" '*' read-write >/dev/null 2>&1 || true

TOKEN_OUT="$(ntfy token add "$USER_NAME" 2>&1 || true)"
TOKEN="$(printf '%s\n' "$TOKEN_OUT" | grep -oE 'tk_[A-Za-z0-9]+' | head -n1 || true)"
if [ -z "$TOKEN" ]; then
  echo "警告: 未能创建 token，请手动: docker compose exec ntfy ntfy token add nexa" >&2
  exit 0
fi

printf 'NEXA_NTFY_TOKEN=%s\n' "$TOKEN" > "$BOT_ENV"

if [ -f "$SETTINGS" ]; then
  # Prefer python if present; else leave settings to bot menu
  if command -v python3 >/dev/null 2>&1; then
    TOKEN="$TOKEN" python3 - <<'PY'
import json, os
from pathlib import Path
p = Path("/config/settings.json")
data = json.loads(p.read_text(encoding="utf-8"))
data.setdefault("ntfy", {})
data["ntfy"]["token"] = os.environ["TOKEN"]
data["ntfy"].setdefault("topics", [])
data["ntfy"].setdefault("disabled_topics", [])
p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  fi
fi

umask 077
cat > "$CREDS" <<CREDS
ntfy 鉴权已启用（auth-default-access: deny-all）

Web / App 登录用户: ${USER_NAME}
密码: ${PASS}
Access Token (Bot/App 也可用): ${TOKEN}

公网: 看 ntfy/etc/server.yml 的 base-url
订阅 topic: 在 Bot 菜单「ntfy 主题管理」里添加并分配频道

安卓: 服务器填 base-url，订阅时用上述用户密码或 Token
CREDS

touch "$MARKER"
echo "ntfy 鉴权初始化完成 → ntfy/credentials.txt"
exit 0
