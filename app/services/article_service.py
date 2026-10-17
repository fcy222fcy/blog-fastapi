"""文章业务逻辑。

与 Go 版 article_service.go 对齐的行为要点：

- **缓存**：前台列表 5 分钟、详情 10 分钟、归档 10 分钟。任何写操作都要
  「精确失效」——改 slug 时新旧两个详情 key 都要清，列表分页用 pattern 清。
- **slug**：自定义优先；标题变更且未显式给 slug 时按新标题重算（与 Go 一致，
  这意味着改标题会换 URL，旧地址由缓存失效兜底但已发出的外链会失效）。
- **状态机**：切到 `scheduled` 必须已有 `scheduled_at`；从 `scheduled` 切走
  要清空 `scheduled_at`，否则后台会残留一个永远不会触发的定时时间。
- **搜索**：相关性排序 + 关键词上下文片段（Summary 已命中时不再截断正文）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache as cache_mod
from app.core.cache import (
    TTL_ARCHIVE,
    TTL_ARTICLE_DETAIL,
    TTL_ARTICLE_LIST,
    article_detail_key,
    article_list_key,
    cache,
)
from app.core.errors import (
    CODE_ARTICLE_NOT_FOUND,
    CODE_INVALID_PARAMS,
    BizError,
)
from app.core.response import normalize_page
from app.core.text import (
    build_search_snippet,
    calculate_reading_time,
    generate_article_slug,
)
from app.models.article import STATUS_DRAFT, STATUS_PUBLISHED, STATUS_SCHEDULED, VALID_STATUSES, Article
from app.repositories import article_repository as repo
from app.repositories import taxonomy_repository as taxonomy_repo
from app.schemas.requests import CreateArticleRequest, UpdateArticleRequest
from app.schemas.common import format_datetime
from app.schemas.responses import (
    AdminArticleDetailResponse,
    ArchiveArticleResponse,
    ArchiveGroupResponse,
    ArticleDetailResponse,
    ArticleListItemResponse,
    SearchArticleResponse,
)

logger = logging.getLogger("blog.service.article")


def _category_payload(article: Article) -> dict:
    category = article.category
    if category is None or not category.id:
        return {"id": 0, "name": "", "slug": "", "description": "", "icon": "", "sort_order": 0, "article_count": 0}
    return {
        "id": category.id,
        "name": category.name,
        "slug": category.slug,
        "description": category.description or "",
        "icon": category.icon or "",
        "sort_order": category.sort_order or 0,
        "article_count": 0,
    }


def _tags_payload(article: Article) -> list[dict]:
    return [
        {
            "id": tag.id,
            "name": tag.name,
            "slug": tag.slug,
            "article_count": 0,
            "created_at": tag.created_at,
        }
        for tag in (article.tags or [])
    ]


def to_admin_entity(article: Article) -> dict:
    """后台列表项：直接按数据库实体的形状输出。

    Go 版 `GetAdminArticleList` 返回的是 `[]*entity.Article`（仓库层只
    `Omit("Content")` 裁掉了正文的读取，结构体字段仍在，所以 JSON 里
    `content` 是空字符串）。前端 `blog-admin/src/views/article/List.vue`
    依赖 `status` 渲状态徽标、`is_top` 渲置顶标记，所以这里不能再套前台的
    `ArticleListResponse`，必须保留实体字段。
    """
    category = article.category
    cat = {
        "id": category.id if category else 0,
        "created_at": format_datetime(category.created_at) if category and category.created_at else None,
        "updated_at": format_datetime(category.updated_at) if category and category.updated_at else None,
        "name": category.name if category else "",
        "slug": category.slug if category else "",
        "description": (category.description or "") if category else "",
        "icon": (category.icon or "") if category else "",
        "sort_order": (category.sort_order or 0) if category else 0,
    }
    tags = [
        {
            "id": tag.id,
            "created_at": format_datetime(tag.created_at) if tag.created_at else None,
            "updated_at": format_datetime(tag.updated_at) if tag.updated_at else None,
            "name": tag.name,
            "slug": tag.slug,
        }
        for tag in (article.tags or [])
    ]
    return {
        "id": article.id,
        "created_at": format_datetime(article.created_at) if article.created_at else None,
        "updated_at": format_datetime(article.updated_at) if article.updated_at else None,
        "title": article.title,
        "slug": article.slug,
        # 仓库层按 Go 的 Omit("Content") 不读正文，字段仍在，值为空串
        "content": "",
        "summary": article.summary or "",
        "cover": article.cover or "",
        "category_id": article.category_id or 0,
        "category": cat,
        # Go 的 Tags 是 nil slice 时序列化成 null，这里保持一致
        "tags": tags or None,
        "view_count": article.view_count or 0,
        "comment_count": article.comment_count or 0,
        "status": article.status,
        "is_top": bool(article.is_top),
        "reading_time": article.reading_time or 0,
        "scheduled_at": format_datetime(article.scheduled_at) if article.scheduled_at else None,
        "seo_title": article.seo_title or "",
        "seo_description": article.seo_description or "",
        "seo_keywords": article.seo_keywords or "",
    }


def to_list_item(article: Article) -> dict:
    return ArticleListItemResponse(
        id=article.id,
        title=article.title,
        slug=article.slug,
        summary=article.summary or "",
        cover=article.cover or "",
        category=_category_payload(article),
        tags=_tags_payload(article),
        view_count=article.view_count or 0,
        comment_count=article.comment_count or 0,
        reading_time=article.reading_time or 0,
        created_at=article.created_at,
    ).model_dump()


def _to_detail(article: Article) -> dict:
    return ArticleDetailResponse(
        id=article.id,
        title=article.title,
        slug=article.slug,
        content=article.content or "",
        summary=article.summary or "",
        cover=article.cover or "",
        category=_category_payload(article),
        tags=_tags_payload(article),
        view_count=article.view_count or 0,
        comment_count=article.comment_count or 0,
        status=article.status,
        is_top=bool(article.is_top),
        reading_time=article.reading_time or 0,
        seo_title=article.seo_title or "",
        seo_description=article.seo_description or "",
        seo_keywords=article.seo_keywords or "",
        created_at=article.created_at,
        updated_at=article.updated_at,
    ).model_dump()


async def list_articles(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 10,
    category_id: int = 0,
    tag_id: int = 0,
    keyword: str = "",
) -> dict:
    page, page_size = normalize_page(page, page_size)

    key = article_list_key(page, page_size, category_id, tag_id, keyword)
    cached = await cache.get_json(key)
    if cached is not None:
        return cached

    rows, total = await repo.list_published(
        session, (page - 1) * page_size, page_size, category_id, tag_id, keyword
    )
    payload = {
        "list": [to_list_item(a) for a in rows],
        "total": total,
        "page": page,
        "size": page_size,
        "total_page": (total + page_size - 1) // page_size if page_size else 0,
    }
    cache.fire_and_forget(cache.set_json(key, payload, TTL_ARTICLE_LIST))
    return payload


async def get_article_detail(session: AsyncSession, slug: str) -> dict:
    key = article_detail_key(slug)
    cached = await cache.get_json(key)
    if cached is not None:
        return cached

    article = await repo.find_by_slug(session, slug)
    if article is None:
        raise BizError(CODE_ARTICLE_NOT_FOUND)

    payload = _to_detail(article)
    cache.fire_and_forget(cache.set_json(key, payload, TTL_ARTICLE_DETAIL))
    return payload


async def get_archives(session: AsyncSession) -> list[dict]:
    cached = await cache.get_json(cache_mod.KEY_ARTICLE_ARCHIVES)
    if cached is not None:
        return cached

    articles = await repo.get_archives(session)
    grouped: dict[int, list[dict]] = {}
    for article in articles:
        grouped.setdefault(article.created_at.year, []).append(
            ArchiveArticleResponse(
                id=article.id,
                title=article.title,
                slug=article.slug,
                created_at=article.created_at,
            ).model_dump()
        )

    result = [
        ArchiveGroupResponse(year=year, articles=items).model_dump()
        for year, items in sorted(grouped.items(), key=lambda kv: kv[0], reverse=True)
    ]
    cache.fire_and_forget(cache.set_json(cache_mod.KEY_ARTICLE_ARCHIVES, result, TTL_ARCHIVE))
    return result


async def admin_list_articles(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 10,
    status: str = "",
    keyword: str = "",
    category_id: int = 0,
) -> dict:
    page, page_size = normalize_page(page, page_size)
    if status and status not in VALID_STATUSES:
        raise BizError(CODE_INVALID_PARAMS, "无效的文章状态")

    rows, total = await repo.list_all(
        session, (page - 1) * page_size, page_size, status, keyword, category_id
    )
    return {
        "list": [to_admin_entity(a) for a in rows],
        "total": total,
        "page": page,
        "size": page_size,
        "total_page": (total + page_size - 1) // page_size if page_size else 0,
    }


async def get_admin_detail(session: AsyncSession, article_id: int) -> dict:
    article = await repo.find_by_id(session, article_id)
    if article is None:
        raise BizError(CODE_ARTICLE_NOT_FOUND)

    return AdminArticleDetailResponse(
        id=article.id,
        title=article.title,
        slug=article.slug,
        content=article.content or "",
        summary=article.summary or "",
        cover=article.cover or "",
        status=article.status,
        is_top=bool(article.is_top),
        category_id=article.category_id or 0,
        tag_ids=[t.id for t in (article.tags or [])],
        scheduled_at=article.scheduled_at,
        seo_title=article.seo_title or "",
        seo_description=article.seo_description or "",
        seo_keywords=article.seo_keywords or "",
    ).model_dump(exclude_none=False)


async def create_article(session: AsyncSession, req: CreateArticleRequest) -> int:
    tags = await taxonomy_repo.find_tags_by_ids(session, req.tag_ids)
    slug = req.slug.strip() or generate_article_slug(req.title)

    article = Article(
        title=req.title,
        slug=slug,
        content=req.content,
        summary=req.summary or "",
        cover=req.cover or "",
        category_id=req.category_id,
        status=req.status or STATUS_DRAFT,
        is_top=bool(req.is_top),
        reading_time=calculate_reading_time(req.content),
        scheduled_at=req.scheduled_at,
        seo_title=req.seo_title or "",
        seo_description=req.seo_description or "",
        seo_keywords=req.seo_keywords or "",
    )
    if req.created_at is not None:
        # 迁移历史文章时保留原始发布时间
        article.created_at = req.created_at
        article.updated_at = req.created_at

    article.tags = tags
    await repo.create(session, article)
    await session.commit()

    logger.info("文章创建成功 id=%s title=%s slug=%s tags=%s", article.id, article.title, article.slug, len(tags))
    cache.fire_and_forget(cache_mod.invalidate_article_list_cache())
    return article.id


async def update_article(session: AsyncSession, article_id: int, req: UpdateArticleRequest) -> None:
    article = await repo.find_by_id(session, article_id)
    if article is None:
        raise BizError(CODE_ARTICLE_NOT_FOUND)

    old_slug = article.slug

    if req.has_field("title") and req.title:
        article.title = req.title
    if req.has_field("content") and req.content is not None and req.content != "":
        article.content = req.content
        article.reading_time = calculate_reading_time(req.content)
    if req.has_field("summary"):
        article.summary = req.summary or ""
    if req.has_field("cover"):
        article.cover = req.cover or ""
    if req.has_field("category_id") and req.category_id:
        article.category_id = req.category_id
    if req.has_field("status") and req.status:
        article.status = req.status
    if req.has_field("is_top") and req.is_top is not None:
        # 未提交时不改动，避免被零值静默取消置顶
        article.is_top = req.is_top

    if req.has_field("slug") and req.slug:
        article.slug = req.slug
    elif req.has_field("title") and req.title:
        article.slug = generate_article_slug(req.title)

    if req.has_field("scheduled_at"):
        # 显式传 null 表示清空定时时间
        article.scheduled_at = req.scheduled_at

    if req.has_field("seo_title"):
        article.seo_title = req.seo_title or ""
    if req.has_field("seo_description"):
        article.seo_description = req.seo_description or ""
    if req.has_field("seo_keywords"):
        article.seo_keywords = req.seo_keywords or ""

    if req.has_field("tag_ids"):
        tag_ids = req.tag_ids or []
        tags = await taxonomy_repo.find_tags_by_ids(session, tag_ids)
        await repo.replace_tags(session, article_id, [t.id for t in tags])
        article.tags = tags

    await repo.save(session, article)
    await session.commit()

    logger.info("文章更新成功 id=%s slug=%s", article_id, article.slug)
    cache.fire_and_forget(cache_mod.invalidate_article_cache(old_slug, article.slug))


async def update_article_status(session: AsyncSession, article_id: int, status: str) -> None:
    article = await repo.find_by_id(session, article_id)
    if article is None:
        raise BizError(CODE_ARTICLE_NOT_FOUND)
    if article.status == status:
        return

    if status == STATUS_SCHEDULED and article.scheduled_at is None:
        raise BizError(CODE_INVALID_PARAMS, "请先在编辑页设置发布时间，再切换为定时发布")

    if article.status == STATUS_SCHEDULED and status != STATUS_SCHEDULED:
        article.scheduled_at = None

    article.status = status
    await repo.save(session, article)
    await session.commit()

    logger.info("文章状态切换成功 id=%s status=%s", article_id, status)
    cache.fire_and_forget(cache_mod.invalidate_article_cache(article.slug))


async def delete_article(session: AsyncSession, article_id: int) -> None:
    article = await repo.find_by_id(session, article_id)
    if article is None:
        raise BizError(CODE_ARTICLE_NOT_FOUND)

    slug = article.slug
    await repo.delete_article(session, article_id)
    await session.commit()

    logger.info("文章删除成功 id=%s", article_id)
    cache.fire_and_forget(cache_mod.invalidate_article_cache(slug))


async def batch_delete_articles(session: AsyncSession, ids: Sequence[int]) -> None:
    if not ids:
        return
    await repo.batch_delete(session, ids)
    await session.commit()

    logger.info("批量删除文章成功 ids=%s", list(ids))
    cache.fire_and_forget(cache_mod.invalidate_article_list_cache())


async def search_articles(session: AsyncSession, keyword: str, page: int = 1, page_size: int = 10) -> dict:
    page, page_size = normalize_page(page, page_size)

    rows, total = await repo.search(session, keyword, (page - 1) * page_size, page_size)
    items = []
    for article in rows:
        payload = to_list_item(article)
        payload["search_snippet"] = build_search_snippet(
            article.content, article.summary, keyword, radius=45
        )
        items.append(SearchArticleResponse(**payload).dump())

    return {
        "list": items,
        "total": total,
        "page": page,
        "size": page_size,
        "total_page": (total + page_size - 1) // page_size if page_size else 0,
    }


async def publish_due_articles(session: AsyncSession) -> int:
    """定时发布轮询（由后台任务调用）。"""
    published = await repo.publish_due_scheduled(session, datetime.now())
    if published:
        await session.commit()
        cache.fire_and_forget(cache_mod.invalidate_article_list_cache())
        for article in published:
            cache.fire_and_forget(cache_mod.invalidate_article_cache(article.slug))
        logger.info("定时发布完成，共 %s 篇", len(published))
    return len(published)


__all__ = [
    "list_articles",
    "get_article_detail",
    "get_archives",
    "admin_list_articles",
    "get_admin_detail",
    "create_article",
    "update_article",
    "update_article_status",
    "delete_article",
    "batch_delete_articles",
    "search_articles",
    "publish_due_articles",
    "STATUS_PUBLISHED",
]
