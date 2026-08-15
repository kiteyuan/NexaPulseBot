from __future__ import annotations

import logging

from sqlalchemy import select

from nexa.database.db import add_log, session_scope
from nexa.database.models import Channel, LLMStatus, Message, SendStatus
from nexa.llm.client import create_llm_client
from nexa.service.dedup import passes_rules
from nexa.service.worker import AsyncWorker

logger = logging.getLogger(__name__)


class MessageProcessor(AsyncWorker):
    """Poll pending messages → rules → L2 hash → optional LLM → send_status."""

    source = "processor"
    task_name = "message-processor"

    def _started_message(self) -> str:
        return "消息处理服务已启动"

    def _stopped_message(self) -> str:
        return "消息处理服务已停止"

    async def tick(self) -> bool:
        return await self.process_batch(limit=20) > 0

    async def process_batch(self, limit: int = 20) -> int:
        async with session_scope() as session:
            result = await session.execute(
                select(Message)
                .where(Message.llm_status == LLMStatus.PENDING.value)
                .order_by(Message.id.asc())
                .limit(limit)
            )
            message_ids = [m.id for m in result.scalars().all()]

        for message_id in message_ids:
            await self._process_one(message_id)
        return len(message_ids)

    async def _process_one(self, message_id: int) -> None:
        # Phase 1: load + rule/dedup; maybe finalize without LLM
        async with session_scope() as session:
            msg = await session.get(Message, message_id)
            if msg is None or msg.llm_status != LLMStatus.PENDING.value:
                return

            channel = await session.get(Channel, msg.channel_id)
            channel_label = (
                (channel.username and f"@{channel.username}")
                or (channel.title if channel else None)
                or str(msg.channel_id)
            )
            content = msg.content
            content_hash_value = msg.content_hash
            media_count = len(msg.media_paths or [])
            has_media = media_count > 0

            ok, reason = passes_rules(
                content,
                min_length=self.settings.filter.min_length,
                block_keywords=self.settings.filter.block_keywords,
                has_media=has_media,
            )
            if not ok:
                msg.llm_status = LLMStatus.REJECTED.value
                msg.send_status = SendStatus.IDLE.value
                msg.error_message = reason
                finalized = ("reject", f"规则过滤拒绝 [{channel_label}]: {reason}", "INFO")
            else:
                dup = await session.execute(
                    select(Message.id)
                    .where(
                        Message.content_hash == content_hash_value,
                        Message.id != msg.id,
                        Message.llm_status.in_(
                            [LLMStatus.APPROVED.value, LLMStatus.SKIPPED.value]
                        ),
                    )
                    .limit(1)
                )
                if dup.scalar_one_or_none() is not None:
                    msg.llm_status = LLMStatus.REJECTED.value
                    msg.send_status = SendStatus.IDLE.value
                    msg.error_message = "文本 hash 重复"
                    finalized = (
                        "reject",
                        f"去重拒绝 [{channel_label}]: 文本 hash 重复",
                        "INFO",
                    )
                elif not self.settings.llm.enabled:
                    msg.llm_status = LLMStatus.SKIPPED.value
                    msg.send_status = SendStatus.READY.value
                    msg.llm_result = {
                        "send": True,
                        "title": _fallback_title(content),
                        "body": (content or "").strip(),
                        "type": "Other",
                        "importance": 5,
                        "reason": "LLM关闭直通",
                    }
                    msg.importance = 5
                    finalized = (
                        "done",
                        f"LLM关闭，直通待发送 [{channel_label}]",
                        "INFO",
                    )
                else:
                    # Claim message so another poll won't pick it up
                    msg.llm_status = "processing"
                    finalized = ("llm", "", "INFO")

        kind, log_text, log_level = finalized
        if kind != "llm":
            await add_log(log_text, level=log_level, source="processor")
            return

        # Phase 2: LLM call outside DB transaction
        llm = create_llm_client(self.settings.llm)
        if llm is None:
            async with session_scope() as session:
                msg = await session.get(Message, message_id)
                if msg:
                    msg.llm_status = LLMStatus.SKIPPED.value
                    msg.send_status = SendStatus.READY.value
            await add_log(f"LLM关闭，直通待发送 [{channel_label}]", source="processor")
            return

        if has_media and not content.strip():
            llm_input = "[仅图片，无文字说明]"
        else:
            llm_input = content.strip() or "[空消息]"

        try:
            review = await llm.review_message(llm_input, media_count=media_count)
        except Exception as exc:  # noqa: BLE001
            async with session_scope() as session:
                msg = await session.get(Message, message_id)
                if msg:
                    msg.llm_status = LLMStatus.ERROR.value
                    msg.send_status = SendStatus.IDLE.value
                    msg.error_message = str(exc)
            await add_log(
                f"LLM审核失败 [{channel_label}]: {exc}",
                level="ERROR",
                source="processor",
            )
            return

        async with session_scope() as session:
            msg = await session.get(Message, message_id)
            if msg is None:
                return
            data = review.model_dump()
            title = (review.title or "").strip() or _fallback_title(content)
            body = (review.body or review.summary or "").strip() or (content or "").strip()
            data["title"] = title[:80]
            data["body"] = body
            msg.llm_result = data
            msg.importance = float(review.importance)
            reason = (review.reason or "").strip()
            reason_note = f" — {reason}" if reason else ""
            if review.send:
                msg.llm_status = LLMStatus.APPROVED.value
                msg.send_status = SendStatus.READY.value
                outcome = (
                    f"LLM审核通过 [{channel_label}] 标题「{data['title']}」"
                    f" 重要性 {review.importance}{reason_note}"
                )
            else:
                msg.llm_status = LLMStatus.REJECTED.value
                msg.send_status = SendStatus.IDLE.value
                outcome = f"LLM审核拒绝 [{channel_label}] 重要性 {review.importance}{reason_note}"

        await add_log(outcome, source="processor")


def _fallback_title(content: str) -> str:
    line = (content or "").strip().splitlines()[0] if (content or "").strip() else ""
    line = " ".join(line.split())
    if not line:
        return "资讯速递"
    return line[:40] + ("…" if len(line) > 40 else "")
