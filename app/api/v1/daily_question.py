"""每日一问路由（/api/v1/daily-questions 与 /api/v1/admin/daily-questions）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_session, require_blogger
from app.core.http import client_ip
from app.core.response import success
from app.schemas.requests import CreateDailyQuestionRequest, UpdateDailyQuestionRequest
from app.services import daily_question_service

router = APIRouter(prefix="/daily-questions", tags=["daily-question"])


@router.get("/latest")
async def latest(session: AsyncSession = Depends(get_session)) -> dict:
    return success(await daily_question_service.get_latest(session))


@router.get("/all")
async def all_published(session: AsyncSession = Depends(get_session)) -> dict:
    return success(await daily_question_service.get_all_published(session))


@router.get("/date/{value}")
async def by_date(value: str, session: AsyncSession = Depends(get_session)) -> dict:
    return success(await daily_question_service.get_by_date(session, value))


@router.get("/previous/{value}")
async def previous(value: str, session: AsyncSession = Depends(get_session)) -> dict:
    return success(await daily_question_service.get_previous(session, value))


@router.get("/next/{value}")
async def next_one(value: str, session: AsyncSession = Depends(get_session)) -> dict:
    return success(await daily_question_service.get_next(session, value))


@router.post("/{question_id}/like")
async def like(
    question_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    count = await daily_question_service.like_question(session, question_id, client_ip(request))
    return success({"like_count": count})


admin_router = APIRouter(
    prefix="/admin/daily-questions",
    tags=["admin:daily-question"],
    dependencies=[Depends(require_blogger)],
)


@admin_router.get("")
async def admin_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: int | None = None,
    keyword: str = "",
    date: str = "",
    session: AsyncSession = Depends(get_session),
) -> dict:
    return success(
        await daily_question_service.admin_list(session, page, page_size, status, keyword, date)
    )


@admin_router.post("")
async def create_question(
    payload: CreateDailyQuestionRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    return success({"id": await daily_question_service.create_question(session, payload)})


@admin_router.put("/{question_id}")
async def update_question(
    question_id: int,
    payload: UpdateDailyQuestionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await daily_question_service.update_question(session, question_id, payload)
    return success(None)


@admin_router.delete("/{question_id}")
async def delete_question(question_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    await daily_question_service.delete_question(session, question_id)
    return success(None)


@admin_router.put("/{question_id}/status")
async def update_status(
    question_id: int, payload: dict, session: AsyncSession = Depends(get_session)
) -> dict:
    await daily_question_service.update_status(session, question_id, int(payload.get("status", -1)))
    return success(None)
