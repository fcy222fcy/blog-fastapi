"""浏览事件数据访问。

去重的关键在 `content_view_events` 的联合唯一索引：
`(content_type, content_id, visitor_key, view_date)`。
插入成功 = 今天第一次访问，计数 +1；插入被忽略 = 已经算过，不重复计数。

这套设计把「判断是否重复」下沉到数据库唯一约束，避免「先查再写」在并发下
双写成功导致的虚高浏览量。库里只存 HMAC 指纹，不保存原始 IP 或 UUID。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnsupportedContentType, ViewTargetNotFound
from app.models.article import Article
from app.models.audit import (
    CONTENT_TYPE_ARTICLE,
    CONTENT_TYPE_DAILY_QUESTION,
    SUPPORTED_CONTENT_TYPES,
    ContentViewEvent,
)
from app.models.daily_question import DailyQuestion


def _insert_ignore(session: AsyncSession, values: dict) -> object:
    dialect = session.bind.dialect.name if session.bind else "sqlite"
    if dialect == "mysql":
        return mysql_insert(ContentViewEvent).values(**values).prefix_with("IGNORE")
    return sqlite_insert(ContentViewEvent).values(**values).on_conflict_do_nothing(
        index_elements=["content_type", "content_id", "visitor_key", "view_date"]
    )


async def record_view(
    session: AsyncSession, content_type: str, content_id: int, visitor_key: str, view_date: date
) -> tuple[bool, int]:
    """返回 (是否计入本次浏览, 当前总浏览量)。"""
    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise UnsupportedContentType(content_type)

    if content_type == CONTENT_TYPE_ARTICLE:
        model = Article
    else:
        model = DailyQuestion

    exists = (
        await session.execute(select(model.id).where(model.id == content_id))
    ).scalar_one_or_none()
    if exists is None:
        raise ViewTargetNotFound(content_type, content_id)

    result = await session.execute(
        _insert_ignore(
            session,
            {
                "content_type": content_type,
                "content_id": content_id,
                "visitor_key": visitor_key,
                "view_date": view_date,
            },
        )
    )
    counted = bool(result.rowcount)

    if counted:
        await session.execute(
            update(model).where(model.id == content_id).values(view_count=model.view_count + 1)
        )

    await session.flush()
    current = (
        await session.execute(select(model.view_count).where(model.id == content_id))
    ).scalar_one()
    return counted, int(current or 0)


async def count_by_date(session: AsyncSession, content_type: str, view_date: date) -> int:
    stmt = select(func.count(ContentViewEvent.id)).where(
        ContentViewEvent.content_type == content_type,
        ContentViewEvent.view_date == view_date,
    )
    return int((await session.execute(stmt)).scalar() or 0)
