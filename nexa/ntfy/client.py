from __future__ import annotations

import mimetypes
from email.header import Header
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import httpx

from nexa.config import NtfySettings


def normalize_topic(value: str) -> str:
    """Strip path noise; keep user-chosen topic name as-is otherwise."""
    return (value or "").strip().strip("/")


def _header_value(value: str, *, max_len: int = 200) -> str:
    """HTTP headers must be single-line latin-1 / RFC 2047 (httpx rejects \\n)."""
    text = (value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    if all(ord(c) < 128 for c in text):
        return text
    encoded = Header(text, "utf-8", maxlinelen=10_000).encode()
    return encoded.replace("\r", "").replace("\n", "")


class NtfyClient:
    """HTTP publisher for self-hosted / public ntfy."""

    def __init__(self, settings: NtfySettings) -> None:
        self.settings = settings

    def reload_settings(self, settings: NtfySettings) -> None:
        self.settings = settings

    def _auth_headers(self) -> dict[str, str]:
        token = (self.settings.token or "").strip()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    def resolve_topic(self, topic: str = "") -> str:
        name = normalize_topic(topic)
        if not name:
            raise RuntimeError("未指定 ntfy topic（频道须先分配主题）")
        return name

    def _topic_url(self, topic: str = "") -> str:
        return f"{self.settings.base_url.rstrip('/')}/{quote(self.resolve_topic(topic), safe='')}"

    def _base_url(self) -> str:
        return self.settings.base_url.rstrip("/")

    async def publish(
        self,
        message: str,
        *,
        title: str = "",
        topic: str = "",
        priority: Optional[int] = None,
        tags: Optional[list[str]] = None,
        attach: str = "",
        click: str = "",
        markdown: bool = False,
    ) -> dict[str, Any]:
        pri = int(priority if priority is not None else self.settings.priority)
        payload: dict[str, Any] = {
            "topic": self.resolve_topic(topic),
            "message": message or "",
            "priority": max(1, min(5, pri)),
        }
        if title.strip():
            payload["title"] = title.strip()[:250]
        if tags:
            payload["tags"] = tags
        if attach.strip():
            payload["attach"] = attach.strip()
        if click.strip():
            payload["click"] = click.strip()
        if markdown:
            payload["markdown"] = True

        headers = self._auth_headers()
        headers["Content-Type"] = "application/json; charset=utf-8"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self._base_url(), headers=headers, json=payload)
        return _parse_ntfy_response(resp)

    async def publish_file(
        self,
        path: Path,
        *,
        message: str = "",
        title: str = "",
        topic: str = "",
        filename: Optional[str] = None,
        priority: Optional[int] = None,
    ) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(str(path))
        name = filename or path.name
        pri = int(priority if priority is not None else self.settings.priority)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        headers = self._auth_headers()
        headers.update(
            {
                "Filename": _header_value(name),
                "Content-Type": mime,
                "Priority": str(max(1, min(5, pri))),
            }
        )
        if title.strip():
            headers["Title"] = _header_value(title.strip()[:80], max_len=120)
        if message.strip():
            headers["Message"] = _header_value(message.strip(), max_len=400)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.put(
                self._topic_url(topic),
                headers=headers,
                content=path.read_bytes(),
            )
        return _parse_ntfy_response(resp, action="upload")

    async def test_auth(self) -> tuple[bool, str]:
        try:
            base = self._base_url()
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(f"{base}/v1/health", headers=self._auth_headers())
                if resp.status_code < 400:
                    return True, f"ntfy 健康检查 OK: {base}"
                probe = await client.get(base, headers=self._auth_headers())
                if probe.status_code >= 500:
                    return False, f"HTTP {probe.status_code}: {probe.text[:200]}"
            return True, f"ntfy 可达: {base}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    async def test_send(
        self,
        message: str = "NexaPulseBot 测试推送",
        *,
        topic: str = "",
    ) -> tuple[bool, str]:
        try:
            used = self.resolve_topic(topic)
            await self.publish(message, title="NexaPulseBot 测试 😋", topic=used)
            return True, f"已推送到 topic={used}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)


def _parse_ntfy_response(resp: httpx.Response, *, action: str = "publish") -> dict[str, Any]:
    if resp.status_code >= 400:
        raise RuntimeError(f"ntfy {action} HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"status": "ok", "body": resp.text[:200]}
