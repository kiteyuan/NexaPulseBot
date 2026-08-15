from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from nexa.timeutil import utcnow


class Base(DeclarativeBase):
    pass


class LLMStatus(str, Enum):
    PENDING = "pending"
    SKIPPED = "skipped"
    APPROVED = "approved"
    REJECTED = "rejected"
    ERROR = "error"


class SendStatus(str, Enum):
    IDLE = "idle"
    READY = "ready"
    SENT = "sent"
    FAILED = "failed"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    session_path: Mapped[str] = mapped_column(String(512), nullable=False)
    api_id: Mapped[int] = mapped_column(Integer, nullable=False)
    api_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="offline", nullable=False)
    last_sync: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    channels: Mapped[list[Channel]] = relationship(back_populates="account", cascade="all, delete-orphan")


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Per-channel ntfy topic; empty = not subscribed / not polled
    ntfy_topic: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    # Cursor for periodic poll (Telegram message id)
    last_message_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    account: Mapped[Account] = relationship(back_populates="channels")
    messages: Mapped[list[Message]] = relationship(back_populates="channel", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("account_id", "telegram_id", name="uq_account_telegram_channel"),
        Index("ix_channels_enabled", "enabled"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Relative paths under media dir, e.g. ["42/1001_0.jpg"]
    media_paths: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    llm_status: Mapped[str] = mapped_column(String(32), default=LLMStatus.PENDING, nullable=False)
    send_status: Mapped[str] = mapped_column(String(32), default=SendStatus.IDLE, nullable=False)
    llm_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    importance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    channel: Mapped[Channel] = relationship(back_populates="messages")

    __table_args__ = (
        UniqueConstraint("channel_id", "telegram_message_id", name="uq_channel_tg_message"),
        Index("ix_messages_llm_status", "llm_status"),
        Index("ix_messages_send_status", "send_status"),
    )


class RuntimeLog(Base):
    __tablename__ = "runtime_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="system", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
