#!/bin/sh
# Bot container entrypoint: ensure config exists, then run CMD.
set -eu

mkdir -p /app/config /app/data/media /app/sessions

if [ ! -f /app/config/settings.json ]; then
  if [ -f /app/defaults/settings.example.json ]; then
    cp /app/defaults/settings.example.json /app/config/settings.json
    echo "已生成 /app/config/settings.json"
  else
    echo "警告: 缺少 settings.json 与 example" >&2
  fi
fi

exec "$@"
