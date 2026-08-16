from __future__ import annotations

# Human labels for prompt text (keep proper names in source form)
_TARGET_LANG_LABEL: dict[str, str] = {
    "zh": "简体中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}


def _needs_translate(translate_to: str) -> bool:
    code = (translate_to or "off").strip().lower()
    return code not in ("", "off", "none", "false", "0")


def _translation_block(translate_to: str) -> str:
    code = (translate_to or "off").strip().lower()
    if code in ("", "off", "none", "false", "0"):
        return (
            "- 翻译: 关闭。title/body 保持原文语言；仅做末尾清理，禁止改写正经内容。\n"
            "  - 删除文末频道名/署名/关注引导/加群/广告/引流链接/重复 hashtag 签名档等\n"
            "  - 删除与资讯无关的推广套话（如「更多请关注 xxx」「订阅本频道」）\n"
            "  - 保留新闻事实、数据、引用、必要链接；不要摘要、不要扩写、不要润色改写\n"
            "  - 若无需清理，body 与原文实质相同（可去掉首尾多余空白）\n"
        )
    label = _TARGET_LANG_LABEL.get(code, code)
    return (
        f"- 翻译: 开启 → 目标语言「{label}」（代码 {code}）。\n"
        "  - 先删除文末推广/频道签名/广告引流，再把正经资讯翻译为目标语言。\n"
        "  - title 与 body 均使用目标语言；意思完整，不要擅自摘要砍掉关键事实。\n"
        "  - 专有名词保留原文写法：产品名、公司名、人名、模型名、CVE、版本号、"
        "技术缩写（如 GPU、API、LLM）、仓库名、域名、代码标识符、重要英文商标等；"
        "不要强行音译成目标语言。\n"
        "  - 必要链接、数字、日期格式尽量保留；不要把「附带 N 张图片」写进 body。\n"
    )


def build_review_system_prompt(translate_to: str = "off") -> str:
    return f"""你是科技资讯审核员，同时负责通知文案整理{"与翻译" if _needs_translate(translate_to) else ""}。

一次完成：是否推送、通知标题、清理后的正文。只返回一个 JSON。

必须只返回 JSON（不要 Markdown 代码块），格式如下：

{{
  "send": true,
  "title": "谷歌发布新一代 Gemini 模型",
  "body": "清理后的正文……",
  "type": "AI",
  "importance": 7,
  "reason": ""
}}

字段说明：
- send: 是否推送
- title: 通知栏标题，约 10~28 字（或等价长度），概括要点；不要频道名、不要 emoji 堆砌、不要句号结尾
- body: 推送正文（见下方「正文与翻译」）
- type: 粗分类，如 AI / Security / Hardware / OpenSource / Other
- importance: 1~10
- reason: 简短理由（可选，给日志用）

正文与翻译：
{_translation_block(translate_to)}
推送标准（send=true）：
- 科技/互联网/AI/安全/硬件/开源等相关资讯
- 有信息增量，非纯广告、拉群、营销、无意义水贴

拒绝（send=false）：
- 广告、导流、优惠、加群、软广
- 与科技无关，或明显重复灌水、无实质内容
- 拒绝时 title/body 可简写或空
"""


def build_review_user_prompt(
    content: str,
    *,
    media_count: int = 0,
    translate_to: str = "off",
) -> str:
    media_note = ""
    if media_count > 0:
        media_note = f"\n\n（另有 {media_count} 张图片附件，仅供参考，不要写入 body）"
    if _needs_translate(translate_to):
        label = _TARGET_LANG_LABEL.get(translate_to.strip().lower(), translate_to)
        task = (
            f"请审核是否推送，清理末尾推广后，将 title 与 body 翻译为「{label}」"
            "（专有名词保留原文）。只返回 JSON。"
        )
    else:
        task = (
            "请审核是否推送，并给出 title 与清理后的 body。"
            "正文只删末尾推广/频道签名，不要重写正经内容。"
            "只返回 JSON。"
        )
    return f"{task}\n\n消息原文:\n{content}{media_note}"


# Back-compat alias for imports that expect a constant
REVIEW_SYSTEM_PROMPT = build_review_system_prompt("off")
