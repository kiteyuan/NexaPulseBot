from __future__ import annotations

"""Manage ntfy topic ACL via the official `ntfy access` CLI.

Runs against the shared auth DB (mounted at /var/lib/ntfy in Docker),
with a fallback to `docker compose exec ntfy` when the binary is only
available in the ntfy service.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# Anonymous / everyone
EVERYONE = "*"

GUEST_MODES: dict[str, tuple[str, str]] = {
    "read-only": ("游客只读", "匿名可订阅；发帖仍需登录/Token（推荐公开订阅）"),
    "deny": ("游客禁止", "匿名不可读不可写；订阅也需登录/Token"),
    "read-write": ("游客读写", "匿名可订阅也可发帖（不安全，一般不推荐）"),
}


def _auth_paths_ok() -> bool:
    auth = Path(os.getenv("NTFY_AUTH_FILE", "/var/lib/ntfy/user.db"))
    # DB may not exist yet; etc config is a strong signal we are wired for ACL
    if auth.parent.is_dir():
        return True
    return Path("/etc/ntfy/server.yml").is_file()


def _build_commands(args: list[str]) -> list[list[str]]:
    """Candidate argv lists to try in order."""
    cmds: list[list[str]] = []
    ntfy_bin = shutil.which("ntfy")
    if ntfy_bin and _auth_paths_ok():
        cmds.append([ntfy_bin, *args])
    # Host-side menu / local dev with compose
    for docker in ("docker", "docker.exe"):
        if shutil.which(docker):
            cmds.append([docker, "compose", "exec", "-T", "ntfy", "ntfy", *args])
            cmds.append([docker, "compose", "-f", "docker-compose.yml", "exec", "-T", "ntfy", "ntfy", *args])
            break
    if shutil.which("docker-compose"):
        cmds.append(["docker-compose", "exec", "-T", "ntfy", "ntfy", *args])
    return cmds


def run_ntfy_access(*args: str, timeout: float = 30.0) -> tuple[bool, str]:
    """Run `ntfy access ...`. Returns (ok, combined stdout/stderr)."""
    argv_tail = ["access", *[str(a) for a in args]]
    candidates = _build_commands(argv_tail)
    if not candidates:
        return (
            False,
            "无法调用 ntfy access：容器内未挂载 ntfy 鉴权目录，且本机没有 docker/ntfy。\n"
            "请确认 docker-compose 已为 bot 挂载 ./ntfy/data 与 ./ntfy/etc，并更新镜像。",
        )

    errors: list[str] = []
    for cmd in candidates:
        try:
            env = os.environ.copy()
            # Help CLI find auth DB when server.yml is present
            env.setdefault("NTFY_AUTH_FILE", "/var/lib/ntfy/user.db")
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
            out = ((proc.stdout or "") + (proc.stderr or "")).strip()
            if proc.returncode == 0:
                return True, out or "ok"
            errors.append(f"$ {' '.join(cmd)}\n  exit {proc.returncode}: {out or '(no output)'}")
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            errors.append(f"$ {' '.join(cmd)}\n  timeout")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"$ {' '.join(cmd)}\n  {exc}")

    return False, "调用 ntfy access 失败:\n" + "\n".join(errors)


def list_access() -> tuple[bool, str]:
    return run_ntfy_access()


def set_guest_access(topic: str, mode: str) -> tuple[bool, str]:
    """Set anonymous (*) ACL for one topic. mode: read-only | deny | read-write."""
    topic = topic.strip().strip("/")
    if not topic:
        return False, "主题名为空"
    if mode not in GUEST_MODES:
        return False, f"未知模式: {mode}（可选: {', '.join(GUEST_MODES)}）"
    perm = "deny" if mode == "deny" else mode
    return run_ntfy_access(EVERYONE, topic, perm)


def guest_mode_label(mode: str) -> str:
    return GUEST_MODES.get(mode, (mode, ""))[0]


def parse_guest_mode_from_acl(acl_text: str, topic: str) -> Optional[str]:
    """Best-effort: find anonymous rule for topic in `ntfy access` output."""
    topic = topic.strip().strip("/")
    in_anon = False
    for raw in acl_text.splitlines():
        line = raw.strip()
        lower = line.lower()
        if lower.startswith("user *") or "role: anonymous" in lower:
            in_anon = True
            continue
        if lower.startswith("user ") and not lower.startswith("user *"):
            in_anon = False
            continue
        if not in_anon:
            continue
        if f"topic {topic}" in lower or f"topic '{topic}'" in lower:
            if "read-write" in lower or "read write" in lower:
                return "read-write"
            if "read-only" in lower or "read only" in lower:
                return "read-only"
            if "no access" in lower or "deny" in lower:
                return "deny"
    return None
