from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

from nexa.config import LLMSettings
from nexa.llm.prompts import REVIEW_SYSTEM_PROMPT, build_review_user_prompt


class ReviewResult(BaseModel):
    send: bool
    type: str = "Other"
    importance: int = Field(default=5, ge=1, le=10)
    reason: str = ""
    title: str = ""
    # Cleaned push body (strip trailing promo); empty → sender falls back to original
    body: str = ""
    # Legacy alias; prefer body
    summary: str = ""


class LLMClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        return headers

    def _chat_url(self) -> str:
        return self.settings.base_url.rstrip("/") + "/chat/completions"

    def _models_url(self) -> str:
        return self.settings.base_url.rstrip("/") + "/models"

    async def test_connection(self) -> tuple[bool, str]:
        payload = {
            "model": self.settings.model,
            "temperature": 0,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self._chat_url(),
                    headers=self._headers(),
                    json=payload,
                )
            if resp.status_code >= 400:
                return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
            return True, "连接成功"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    async def list_models(self) -> tuple[bool, list[str], str]:
        """Fetch model IDs from OpenAI-compatible GET /models."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(self._models_url(), headers=self._headers())
            if resp.status_code >= 400:
                return False, [], f"HTTP {resp.status_code}: {resp.text[:300]}"
            data = resp.json()
            items = data.get("data") if isinstance(data, dict) else data
            if not isinstance(items, list):
                return False, [], f"无法解析模型列表: {str(data)[:200]}"
            ids: list[str] = []
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    ids.append(str(item["id"]))
                elif isinstance(item, str):
                    ids.append(item)
            ids = sorted(set(ids), key=str.lower)
            if not ids:
                return False, [], "接口返回空模型列表"
            return True, ids, f"已拉取 {len(ids)} 个模型"
        except Exception as exc:  # noqa: BLE001
            return False, [], str(exc)

    async def review_message(self, content: str, *, media_count: int = 0) -> ReviewResult:
        payload = {
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "messages": [
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_review_user_prompt(content, media_count=media_count),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                self._chat_url(),
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        text = self._extract_content(data)
        return self._parse_review(text)

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str:
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Unexpected LLM response: {data}") from exc

    @staticmethod
    def _parse_review(text: str) -> ReviewResult:
        cleaned = text.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
        if fence:
            cleaned = fence.group(1).strip()
        try:
            raw = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM did not return JSON: {cleaned[:200]}") from exc
        try:
            return ReviewResult.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid review schema: {exc}") from exc


def create_llm_client(settings: LLMSettings) -> Optional[LLMClient]:
    if not settings.enabled:
        return None
    return LLMClient(settings)
