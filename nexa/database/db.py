from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from nexa.config import AppSettings, load_settings
from nexa.database.models import Base, RuntimeLog

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory


async def init_db(settings: Optional[AppSettings] = None) -> AsyncEngine:
    global _engine, _session_factory

    settings = settings or load_settings()
    db_path = settings.resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    if _engine is not None and _session_factory is not None:
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_migrate_schema)
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA busy_timeout=60000")
        return _engine

    _engine = create_async_engine(
        url,
        echo=False,
        connect_args={"timeout": 60},
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_schema)
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA busy_timeout=60000")

    return _engine


def _migrate_schema(sync_conn) -> None:
    """Additive SQLite migrations for existing databases."""
    msg_cols = {row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info(messages)").fetchall()}
    if "media_paths" not in msg_cols:
        sync_conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN media_paths JSON")

    ch_cols = {row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info(channels)").fetchall()}
    if "last_message_id" not in ch_cols:
        sync_conn.exec_driver_sql(
            "ALTER TABLE channels ADD COLUMN last_message_id BIGINT NOT NULL DEFAULT 0"
        )
    if "ntfy_topic" not in ch_cols:
        sync_conn.exec_driver_sql(
            "ALTER TABLE channels ADD COLUMN ntfy_topic VARCHAR(128) NOT NULL DEFAULT ''"
        )


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def add_log(message: str, *, level: str = "INFO", source: str = "system") -> None:
    async with session_scope() as session:
        session.add(RuntimeLog(level=level, source=source, message=message))


async def fetch_logs(limit: int = 200) -> list[RuntimeLog]:
    async with session_scope() as session:
        result = await session.execute(
            select(RuntimeLog).order_by(RuntimeLog.id.desc()).limit(limit)
        )
        logs = list(result.scalars().all())
        return list(reversed(logs))
