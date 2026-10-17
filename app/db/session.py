"""数据库引擎与会话管理。

同时支持 MySQL（生产，与 Go 版共用同一个库）和 SQLite（本地零依赖跑通）。
会话通过 FastAPI 依赖注入下发，请求结束自动关闭；事务由各 service 显式控制。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import Base

logger = get_logger("db")

_url = settings.resolved_database_url

if _url.startswith("sqlite"):
    # SQLite 需要父目录存在，否则 aiosqlite 打开失败
    if ":///" in _url and not _url.endswith(":memory:"):
        from pathlib import Path

        db_path = _url.split(":///", 1)[1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(
        _url,
        echo=settings.db_echo,
        future=True,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_async_engine(
        _url,
        echo=settings.db_echo,
        future=True,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=10,
        max_overflow=20,
    )

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话。"""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """非请求场景（定时任务、后台协程）使用的会话。"""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """建表。等价于 Go 版 AutoMigrate（只补缺表，不改已有列）。"""
    # 必须先 import 全部模型，让 metadata 完整注册
    from app import models  # noqa: F401  pylint: disable=unused-import

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据表已就绪: %s", "SQLite" if settings.is_sqlite else "MySQL")


async def dispose() -> None:
    await engine.dispose()
