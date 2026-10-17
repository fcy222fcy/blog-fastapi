"""分类与标签路由（/api/v1/categories、/api/v1/tags 及其 admin 子路径）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_session, require_blogger
from app.core.response import success
from app.schemas.requests import (
    CreateCategoryRequest,
    CreateTagRequest,
    UpdateCategoryRequest,
    UpdateTagRequest,
)
from app.services import taxonomy_service

router = APIRouter(tags=["taxonomy"])


# ---------------------------------------------------------------- public


@router.get("/categories")
async def list_categories(session: AsyncSession = Depends(get_session)) -> dict:
    return success(await taxonomy_service.list_categories(session))


@router.get("/categories/{category_id}")
async def get_category(category_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    return success(await taxonomy_service.get_category(session, category_id))


@router.get("/tags")
async def list_tags(session: AsyncSession = Depends(get_session)) -> dict:
    return success(await taxonomy_service.list_tags(session))


# ----------------------------------------------------------------- admin

admin_router = APIRouter(tags=["admin:taxonomy"], dependencies=[Depends(require_blogger)])


@admin_router.post("/admin/categories")
async def create_category(
    payload: CreateCategoryRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    return success({"id": await taxonomy_service.create_category(session, payload)})


@admin_router.put("/admin/categories/{category_id}")
async def update_category(
    category_id: int,
    payload: UpdateCategoryRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await taxonomy_service.update_category(session, category_id, payload)
    return success(None)


@admin_router.delete("/admin/categories/{category_id}")
async def delete_category(category_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    await taxonomy_service.delete_category(session, category_id)
    return success(None)


@admin_router.post("/admin/tags")
async def create_tag(payload: CreateTagRequest, session: AsyncSession = Depends(get_session)) -> dict:
    return success({"id": await taxonomy_service.create_tag(session, payload)})


@admin_router.put("/admin/tags/{tag_id}")
async def update_tag(
    tag_id: int, payload: UpdateTagRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    await taxonomy_service.update_tag(session, tag_id, payload)
    return success(None)


@admin_router.delete("/admin/tags/{tag_id}")
async def delete_tag(tag_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    await taxonomy_service.delete_tag(session, tag_id)
    return success(None)
