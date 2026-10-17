"""文章路由（/api/v1/articles 与 /api/v1/admin/articles）。

路由声明顺序有讲究：`/search`、`/archives` 必须写在 `/{slug}` 之前，
否则 "search" 会被当成 slug 吃掉（FastAPI 按声明顺序匹配）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_blogger, get_session
from app.core.response import success
from app.schemas.requests import (
    BatchIdsRequest,
    CreateArticleRequest,
    UpdateArticleRequest,
    UpdateArticleStatusRequest,
)
from app.services import article_service

router = APIRouter(tags=["article"])


# ---------------------------------------------------------------- public


@router.get("/articles")
async def list_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    category_id: int = 0,
    tag: int = 0,
    keyword: str = "",
    session: AsyncSession = Depends(get_session),
) -> dict:
    data = await article_service.list_articles(session, page, page_size, category_id, tag, keyword)
    return success(data)


@router.get("/articles/search")
async def search_articles(
    keyword: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return success(await article_service.search_articles(session, keyword, page, page_size))


@router.get("/articles/archives")
async def archives(session: AsyncSession = Depends(get_session)) -> dict:
    return success(await article_service.get_archives(session))


@router.get("/articles/{slug}")
async def article_detail(slug: str, session: AsyncSession = Depends(get_session)) -> dict:
    return success(await article_service.get_article_detail(session, slug))


# ----------------------------------------------------------------- admin


admin_router = APIRouter(
    prefix="/admin/articles", tags=["admin:article"], dependencies=[Depends(require_blogger)]
)


@admin_router.get("")
async def admin_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: str = "",
    keyword: str = "",
    category_id: int = 0,
    session: AsyncSession = Depends(get_session),
) -> dict:
    data = await article_service.admin_list_articles(
        session, page, page_size, status, keyword, category_id
    )
    return success(data)


@admin_router.get("/{article_id}")
async def admin_detail(article_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    return success(await article_service.get_admin_detail(session, article_id))


@admin_router.post("")
async def create_article(
    payload: CreateArticleRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    article_id = await article_service.create_article(session, payload)
    return success({"id": article_id})


@admin_router.put("/{article_id}")
async def update_article(
    article_id: int,
    payload: UpdateArticleRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await article_service.update_article(session, article_id, payload)
    return success(None)


@admin_router.put("/{article_id}/status")
async def update_status(
    article_id: int,
    payload: UpdateArticleStatusRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await article_service.update_article_status(session, article_id, payload.status)
    return success(None)


@admin_router.delete("/{article_id}")
async def delete_article(article_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    await article_service.delete_article(session, article_id)
    return success(None)


@admin_router.post("/batch-delete")
async def batch_delete(payload: BatchIdsRequest, session: AsyncSession = Depends(get_session)) -> dict:
    await article_service.batch_delete_articles(session, payload.ids)
    return success(None)
