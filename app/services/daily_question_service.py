"""每日一问业务逻辑。

对外只暴露「今天及以前」的已发布题目：
- `get_all_published` / `latest` / `next` 都在 SQL 层带了 `date <= today`
- `get_question_by_date` 额外做一次日期比对，防止有人直接猜未来日期

点赞按 IP 去重，与评论点赞同一套「唯一索引 + 冲突忽略」的做法。
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    CODE_DAILY_QUESTION_DATE_EXISTS,
    CODE_DAILY_QUESTION_NOT_FOUND,
    CODE_INVALID_PARAMS,
    BizError,
)
from app.core.response import normalize_page
from app.models.daily_question import STATUS_PUBLISHED, STATUS_SCHEDULED, VALID_STATUSES, DailyQuestion
from app.repositories import daily_question_repository as repo
from app.schemas.requests import CreateDailyQuestionRequest, UpdateDailyQuestionRequest

logger = logging.getLogger("blog.service.daily_question")


def _to_response(question: DailyQuestion) -> dict:
    return {
        "id": question.id,
        "question": question.question,
        "answer": question.answer or "",
        "date": question.date,
        "like_count": question.like_count or 0,
        "comment_count": question.comment_count or 0,
        "view_count": question.view_count or 0,
        "status": question.status,
        "created_at": question.created_at,
    }


async def get_latest(session: AsyncSession) -> dict:
    question = await repo.get_latest(session)
    if question is None:
        raise BizError(CODE_DAILY_QUESTION_NOT_FOUND)
    return _to_response(question)


async def get_all_published(session: AsyncSession) -> list[dict]:
    return [_to_response(q) for q in await repo.get_all_published(session)]


async def get_by_date(session: AsyncSession, value: str) -> dict:
    question = await repo.find_by_date(session, value)
    if question is None or question.status != STATUS_PUBLISHED:
        raise BizError(CODE_DAILY_QUESTION_NOT_FOUND)
    # 未来日期不提前展示
    if question.date > date.today().isoformat():
        raise BizError(CODE_DAILY_QUESTION_NOT_FOUND)
    return _to_response(question)


async def get_previous(session: AsyncSession, value: str) -> dict:
    question = await repo.get_previous(session, value)
    if question is None:
        raise BizError(CODE_DAILY_QUESTION_NOT_FOUND, "没有前一天的问题")
    return _to_response(question)


async def get_next(session: AsyncSession, value: str) -> dict:
    question = await repo.get_next(session, value)
    if question is None:
        raise BizError(CODE_DAILY_QUESTION_NOT_FOUND, "没有后一天的问题")
    return _to_response(question)


async def like_question(session: AsyncSession, question_id: int, visitor_ip: str) -> int:
    count = await repo.like_question(session, question_id, visitor_ip)
    await session.commit()
    logger.info("问题点赞成功 id=%s like_count=%s", question_id, count)
    return count


async def admin_list(
    session: AsyncSession, page: int = 1, page_size: int = 10, status: int | None = None,
    keyword: str = "", date_value: str = "",
) -> dict:
    page, page_size = normalize_page(page, page_size)

    status_filter = -1 if status is None else status
    if status_filter < -1 or status_filter > STATUS_SCHEDULED:
        raise BizError(CODE_INVALID_PARAMS, "无效的问题状态")

    rows, total = await repo.list_questions(
        session, (page - 1) * page_size, page_size, status_filter, keyword, date_value
    )
    return {
        "list": [_to_response(q) for q in rows],
        "total": total,
        "page": page,
        "size": page_size,
        "total_page": (total + page_size - 1) // page_size if page_size else 0,
    }


async def create_question(session: AsyncSession, req: CreateDailyQuestionRequest) -> int:
    if not (req.question or "").strip():
        raise BizError(CODE_INVALID_PARAMS, "问题内容不能为空")
    if not (req.answer or "").strip():
        raise BizError(CODE_INVALID_PARAMS, "答案不能为空")
    if not req.date:
        raise BizError(CODE_INVALID_PARAMS, "日期不能为空")

    if await repo.find_by_date(session, req.date) is not None:
        raise BizError(CODE_DAILY_QUESTION_DATE_EXISTS)

    status = STATUS_PUBLISHED if req.status is None else req.status
    if status not in VALID_STATUSES:
        raise BizError(CODE_INVALID_PARAMS, "无效的问题状态")

    question = DailyQuestion(
        question=req.question, answer=req.answer, date=req.date, status=status
    )
    await repo.create(session, question)
    await session.commit()

    logger.info("创建问题成功 id=%s date=%s", question.id, question.date)
    return question.id


async def update_question(
    session: AsyncSession, question_id: int, req: UpdateDailyQuestionRequest
) -> None:
    question = await repo.find_by_id(session, question_id)
    if question is None:
        raise BizError(CODE_DAILY_QUESTION_NOT_FOUND)

    if req.has_field("question") and req.question:
        question.question = req.question
    if req.has_field("answer") and req.answer is not None:
        question.answer = req.answer
    if req.has_field("date") and req.date:
        existing = await repo.find_by_date(session, req.date)
        if existing is not None and existing.id != question_id:
            raise BizError(CODE_DAILY_QUESTION_DATE_EXISTS)
        question.date = req.date
    if req.has_field("status") and req.status is not None:
        if req.status not in VALID_STATUSES:
            raise BizError(CODE_INVALID_PARAMS, "无效的问题状态")
        question.status = req.status

    await session.commit()
    logger.info("更新问题成功 id=%s", question_id)


async def delete_question(session: AsyncSession, question_id: int) -> None:
    question = await repo.find_by_id(session, question_id)
    if question is None:
        raise BizError(CODE_DAILY_QUESTION_NOT_FOUND)

    await repo.delete_question(session, question_id)
    await session.commit()
    logger.info("删除问题成功 id=%s", question_id)


async def update_status(session: AsyncSession, question_id: int, status: int) -> None:
    if status not in VALID_STATUSES:
        raise BizError(CODE_INVALID_PARAMS, "无效的问题状态")

    question = await repo.find_by_id(session, question_id)
    if question is None:
        raise BizError(CODE_DAILY_QUESTION_NOT_FOUND)

    question.status = status
    await session.commit()
    logger.info("更新问题状态成功 id=%s status=%s", question_id, status)
