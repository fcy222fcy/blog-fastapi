"""每日一问数据访问。

对外查询统一带 `date <= 今天` 与 `status = 已发布` 两个条件：
未来排期的题目即使状态是 published 也不会提前露出。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, CODE_ALREADY_LIKED
from app.models.daily_question import (
    DailyQuestion,
    DailyQuestionLikeLog,
    STATUS_PUBLISHED,
)


def _today() -> str:
    return date.today().isoformat()


async def find_by_id(session: AsyncSession, question_id: int) -> DailyQuestion | None:
    result = await session.execute(select(DailyQuestion).where(DailyQuestion.id == question_id))
    return result.scalar_one_or_none()


async def find_by_date(session: AsyncSession, value: str) -> DailyQuestion | None:
    result = await session.execute(select(DailyQuestion).where(DailyQuestion.date == value))
    return result.scalar_one_or_none()


async def get_all_published(session: AsyncSession) -> list[DailyQuestion]:
    stmt = (
        select(DailyQuestion)
        .where(DailyQuestion.status == STATUS_PUBLISHED, DailyQuestion.date <= _today())
        .order_by(DailyQuestion.date.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_latest(session: AsyncSession) -> DailyQuestion | None:
    stmt = (
        select(DailyQuestion)
        .where(DailyQuestion.status == STATUS_PUBLISHED, DailyQuestion.date <= _today())
        .order_by(DailyQuestion.date.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_previous(session: AsyncSession, value: str) -> DailyQuestion | None:
    stmt = (
        select(DailyQuestion)
        .where(DailyQuestion.status == STATUS_PUBLISHED, DailyQuestion.date < value)
        .order_by(DailyQuestion.date.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_next(session: AsyncSession, value: str) -> DailyQuestion | None:
    stmt = (
        select(DailyQuestion)
        .where(
            DailyQuestion.status == STATUS_PUBLISHED,
            DailyQuestion.date > value,
            DailyQuestion.date <= _today(),
        )
        .order_by(DailyQuestion.date.asc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_questions(
    session: AsyncSession, offset: int, limit: int, status: int = -1, keyword: str = "", date_value: str = ""
) -> tuple[list[DailyQuestion], int]:
    conditions: list[Any] = []
    if status >= 0:
        conditions.append(DailyQuestion.status == status)
    if keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                DailyQuestion.question.like(pattern),
                DailyQuestion.answer.like(pattern),
                DailyQuestion.date.like(pattern),
            )
        )
    if date_value.strip():
        conditions.append(DailyQuestion.date == date_value.strip())

    total = int(
        (await session.execute(select(func.count(DailyQuestion.id)).where(*conditions))).scalar() or 0
    )
    stmt = (
        select(DailyQuestion)
        .where(*conditions)
        .order_by(DailyQuestion.date.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total


async def create(session: AsyncSession, question: DailyQuestion) -> DailyQuestion:
    session.add(question)
    await session.flush()
    return question


async def save(session: AsyncSession, question: DailyQuestion) -> None:
    await session.flush()


async def delete_question(session: AsyncSession, question_id: int) -> None:
    await session.execute(
        delete(DailyQuestionLikeLog).where(DailyQuestionLikeLog.question_id == question_id)
    )
    await session.execute(delete(DailyQuestion).where(DailyQuestion.id == question_id))


def _insert_ignore(session: AsyncSession, question_id: int, visitor_ip: str) -> Any:
    dialect = session.bind.dialect.name if session.bind else "sqlite"
    from datetime import datetime

    values = {"question_id": question_id, "visitor_ip": visitor_ip, "created_at": datetime.now()}
    if dialect == "mysql":
        return mysql_insert(DailyQuestionLikeLog).values(**values).prefix_with("IGNORE")
    return sqlite_insert(DailyQuestionLikeLog).values(**values).on_conflict_do_nothing(
        index_elements=["question_id", "visitor_ip"]
    )


async def like_question(session: AsyncSession, question_id: int, visitor_ip: str) -> int:
    """按 IP 去重点赞，返回最新点赞数。"""
    question = await find_by_id(session, question_id)
    if question is None:
        from app.core.errors import CODE_DAILY_QUESTION_NOT_FOUND

        raise BizError(CODE_DAILY_QUESTION_NOT_FOUND)

    result = await session.execute(_insert_ignore(session, question_id, visitor_ip))
    if not result.rowcount:
        raise BizError(CODE_ALREADY_LIKED)

    await session.execute(
        update(DailyQuestion)
        .where(DailyQuestion.id == question_id)
        .values(like_count=DailyQuestion.like_count + 1)
    )
    await session.flush()
    await session.refresh(question)
    return question.like_count


async def count(session: AsyncSession, status: int = -1) -> int:
    stmt = select(func.count(DailyQuestion.id))
    if status >= 0:
        stmt = stmt.where(DailyQuestion.status == status)
    return int((await session.execute(stmt)).scalar() or 0)


async def sum_like_count(session: AsyncSession) -> int:
    stmt = select(func.coalesce(func.sum(DailyQuestion.like_count), 0))
    return int((await session.execute(stmt)).scalar() or 0)


async def increment_view_count(session: AsyncSession, question_id: int) -> None:
    await session.execute(
        update(DailyQuestion)
        .where(DailyQuestion.id == question_id)
        .values(view_count=DailyQuestion.view_count + 1)
    )
