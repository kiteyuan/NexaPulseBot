from __future__ import annotations

import hashlib
import re
import unicodedata


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.strip().lower()
    text = _WHITESPACE_RE.sub("", text)
    return text


def content_hash(text: str) -> str:
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def passes_rules(
    text: str,
    *,
    min_length: int,
    block_keywords: list[str],
    has_media: bool = False,
) -> tuple[bool, str]:
    body = (text or "").strip()
    if not body and not has_media:
        return False, f"内容过短（<{min_length}）"
    # 有图时不卡字数（短说明 / 纯图都放行），仍查屏蔽词
    if body and not has_media and len(body) < min_length:
        return False, f"内容过短（<{min_length}）"
    if body:
        lower = body.lower()
        for kw in block_keywords:
            if kw and kw.lower() in lower:
                return False, f"命中屏蔽词: {kw}"
    return True, ""
