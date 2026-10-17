"""分类与标签业务逻辑。

有两条与缓存有关的细节值得单独说明：

1. **计数为 0 不一定可信**：`count_articles_in_category` 返回 0 既可能是「真的没有文章」
   也可能是「查询出错」。因此只要有一次计数失败就**跳过缓存写入**，否则一个 0 会被
   固化进 `category:list` 整整 30 分钟，后台长时间显示「0 篇文章」还查不到日志。
2. **删除前必须拦有文章的分类/标签**，否则文章会指向不存在的分类，前台列表直接空窗。
"""

from __future__ import annotations

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache as cache_mod
from app.core.cache import TTL_CATEGORY_LIST, TTL_TAG_LIST, cache
from app.core.errors import (
    CODE_CATEGORY_HAS_ARTICLES,
    CODE_CATEGORY_NAME_EXISTS,
    CODE_CATEGORY_NOT_FOUND,
    CODE_TAG_HAS_ARTICLES,
    CODE_TAG_NAME_EXISTS,
    CODE_TAG_NOT_FOUND,
    BizError,
)
from app.core.text import generate as generate_slug
from app.models.taxonomy import Category, Tag
from app.repositories import taxonomy_repository as repo
from app.schemas.requests import (
    CreateCategoryRequest,
    CreateTagRequest,
    UpdateCategoryRequest,
    UpdateTagRequest,
)

logger = logging.getLogger("blog.service.taxonomy")


# ------------------------------------------------------------------- category


async def list_categories(session: AsyncSession) -> list[dict]:
    cached = await cache.get_json(cache_mod.KEY_CATEGORY_LIST)
    if cached is not None:
        return cached

    categories = await repo.list_categories(session)
    result: list[dict] = []
    counts_trustworthy = True

    for category in categories:
        try:
            count = await repo.count_articles_in_category(session, category.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("获取分类文章数失败 category_id=%s: %s", category.id, exc)
            count = 0
            counts_trustworthy = False
        result.append(
            {
                "id": category.id,
                "name": category.name,
                "slug": category.slug,
                "description": category.description or "",
                "icon": category.icon or "",
                "sort_order": category.sort_order or 0,
                "article_count": count,
            }
        )

    if counts_trustworthy:
        cache.fire_and_forget(cache.set_json(cache_mod.KEY_CATEGORY_LIST, result, TTL_CATEGORY_LIST))
    return result


async def get_category(session: AsyncSession, category_id: int) -> dict:
    category = await repo.find_category_by_id(session, category_id)
    if category is None:
        raise BizError(CODE_CATEGORY_NOT_FOUND)

    count = await repo.count_articles_in_category(session, category.id)
    return {
        "id": category.id,
        "name": category.name,
        "slug": category.slug,
        "description": category.description or "",
        "icon": category.icon or "",
        "sort_order": category.sort_order or 0,
        "article_count": count,
    }


async def create_category(session: AsyncSession, req: CreateCategoryRequest) -> int:
    if await repo.find_category_by_name(session, req.name):
        raise BizError(CODE_CATEGORY_NAME_EXISTS)

    slug = req.slug.strip()
    if not slug:
        slug = generate_slug(req.name)
        if await repo.find_category_by_slug(session, slug):
            slug = f"{slug}-{int(time.time())}"

    category = Category(
        name=req.name,
        slug=slug,
        description=req.description or "",
        icon=req.icon or "",
        sort_order=req.sort_order,
    )
    await repo.create_category(session, category)
    await session.commit()

    logger.info("创建分类成功 id=%s name=%s", category.id, category.name)
    cache.fire_and_forget(cache.delete(cache_mod.KEY_CATEGORY_LIST))
    return category.id


async def update_category(session: AsyncSession, category_id: int, req: UpdateCategoryRequest) -> None:
    category = await repo.find_category_by_id(session, category_id)
    if category is None:
        raise BizError(CODE_CATEGORY_NOT_FOUND)

    if req.has_field("name") and req.name:
        existing = await repo.find_category_by_name(session, req.name)
        if existing is not None and existing.id != category_id:
            raise BizError(CODE_CATEGORY_NAME_EXISTS)
        category.name = req.name
    if req.has_field("slug") and req.slug is not None:
        category.slug = req.slug
    if req.has_field("description") and req.description is not None:
        category.description = req.description
    if req.has_field("icon") and req.icon is not None:
        category.icon = req.icon
    if req.has_field("sort_order") and req.sort_order:
        category.sort_order = req.sort_order

    await session.commit()
    logger.info("更新分类成功 id=%s", category_id)
    cache.fire_and_forget(cache.delete(cache_mod.KEY_CATEGORY_LIST))


async def delete_category(session: AsyncSession, category_id: int) -> None:
    category = await repo.find_category_by_id(session, category_id)
    if category is None:
        raise BizError(CODE_CATEGORY_NOT_FOUND)

    count = await repo.count_articles_in_category(session, category_id)
    if count > 0:
        raise BizError(CODE_CATEGORY_HAS_ARTICLES)

    await repo.delete_category(session, category_id)
    await session.commit()
    logger.info("删除分类成功 id=%s", category_id)
    cache.fire_and_forget(cache.delete(cache_mod.KEY_CATEGORY_LIST))


# ------------------------------------------------------------------------ tag


async def list_tags(session: AsyncSession) -> list[dict]:
    cached = await cache.get_json(cache_mod.KEY_TAG_LIST)
    if cached is not None:
        return cached

    tags = await repo.list_tags(session)
    result: list[dict] = []
    counts_trustworthy = True

    for tag in tags:
        try:
            count = await repo.count_articles_with_tag(session, tag.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("获取标签文章数失败 tag_id=%s: %s", tag.id, exc)
            count = 0
            counts_trustworthy = False
        result.append(
            {
                "id": tag.id,
                "name": tag.name,
                "slug": tag.slug,
                "article_count": count,
                "created_at": tag.created_at,
            }
        )

    if counts_trustworthy:
        cache.fire_and_forget(cache.set_json(cache_mod.KEY_TAG_LIST, result, TTL_TAG_LIST))
    return result


async def create_tag(session: AsyncSession, req: CreateTagRequest) -> int:
    if await repo.find_tag_by_name(session, req.name):
        raise BizError(CODE_TAG_NAME_EXISTS)

    slug = req.slug.strip()
    if not slug:
        slug = generate_slug(req.name)
        if await repo.find_tag_by_slug(session, slug):
            slug = f"{slug}-{int(time.time())}"

    tag = Tag(name=req.name, slug=slug)
    await repo.create_tag(session, tag)
    await session.commit()

    logger.info("创建标签成功 id=%s name=%s", tag.id, tag.name)
    cache.fire_and_forget(cache.delete(cache_mod.KEY_TAG_LIST))
    return tag.id


async def update_tag(session: AsyncSession, tag_id: int, req: UpdateTagRequest) -> None:
    tag = await repo.find_tag_by_id(session, tag_id)
    if tag is None:
        raise BizError(CODE_TAG_NOT_FOUND)

    if req.has_field("name") and req.name:
        existing = await repo.find_tag_by_name(session, req.name)
        if existing is not None and existing.id != tag_id:
            raise BizError(CODE_TAG_NAME_EXISTS)
        tag.name = req.name
    if req.has_field("slug") and req.slug is not None:
        tag.slug = req.slug

    await session.commit()
    logger.info("更新标签成功 id=%s", tag_id)
    cache.fire_and_forget(cache.delete(cache_mod.KEY_TAG_LIST))


async def delete_tag(session: AsyncSession, tag_id: int) -> None:
    tag = await repo.find_tag_by_id(session, tag_id)
    if tag is None:
        raise BizError(CODE_TAG_NOT_FOUND)

    count = await repo.count_articles_with_tag(session, tag_id)
    if count > 0:
        raise BizError(CODE_TAG_HAS_ARTICLES)

    await repo.delete_tag(session, tag_id)
    await session.commit()
    logger.info("删除标签成功 id=%s", tag_id)
    cache.fire_and_forget(cache.delete(cache_mod.KEY_TAG_LIST))
