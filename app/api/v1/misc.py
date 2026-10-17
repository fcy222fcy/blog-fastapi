"""浏览量上报、审计日志、关于页面、仪表盘、RSS/Sitemap。

这些端点体量都小，但各自有一个容易出错的点，单独注释标出。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_session, require_blogger
from app.core.errors import CODE_INVALID_PARAMS, BizError
from app.core.response import success
from app.models.article import STATUS_PUBLISHED, STATUS_SCHEDULED
from app.models.audit import CONTENT_TYPE_ARTICLE
from app.repositories import article_repository as article_repo
from app.repositories import comment_repository as comment_repo
from app.schemas.requests import RecordViewRequest, UpdateAboutPageRequest
from app.services import audit_service, content_view_service
from app.services import article_service

router = APIRouter(tags=["misc"])


# ------------------------------------------------------------- content view


@router.post("/views")
async def record_view(
    payload: RecordViewRequest,
    request: Request,
    x_visitor_id: str | None = Header(default=None, alias="X-Visitor-ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """按天去重地记一次浏览。

    访客身份优先用前端生成的匿名 UUID，没有才退化为 IP，
    最终只把 HMAC 指纹写库（不存原始值）。
    """
    from app.core.http import client_ip

    data = await content_view_service.record_view(
        session,
        payload.content_type,
        payload.content_id,
        x_visitor_id,
        client_ip(request),
    )
    return success(data)


# --------------------------------------------------------------- about page


@router.get("/about")
async def get_about(session: AsyncSession = Depends(get_session)) -> dict:
    return success(await content_view_service.get_about_page(session))


@router.put("/admin/about", dependencies=[Depends(require_blogger)])
async def update_about(payload: UpdateAboutPageRequest, session: AsyncSession = Depends(get_session)) -> dict:
    await content_view_service.update_about_page(session, payload)
    return success(None)


# -------------------------------------------------------------- audit logs


@router.get("/admin/audit-logs", dependencies=[Depends(require_blogger)])
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str = "",
    target_type: str = "",
    session: AsyncSession = Depends(get_session),
) -> dict:
    return success(
        await audit_service.list_audit_logs(session, page, page_size, action, target_type)
    )


# ---------------------------------------------------------------- dashboard


@router.get("/admin/dashboard/stats", dependencies=[Depends(require_blogger)])
async def dashboard_stats(session: AsyncSession = Depends(get_session)) -> dict:
    article_count = await article_repo.count(session)
    published = await article_repo.count(session, STATUS_PUBLISHED)
    scheduled = await article_repo.count(session, STATUS_SCHEDULED)
    total_views = await article_repo.sum_view_count(session)
    today_views = await content_view_service.count_today(session, CONTENT_TYPE_ARTICLE)
    comment_count = await comment_repo.count(session)
    pending = await comment_repo.count(session, "pending")

    return success(
        {
            "article_count": article_count,
            "published_count": published,
            "draft_count": max(article_count - published - scheduled, 0),
            "scheduled_count": scheduled,
            "total_views": total_views,
            "today_views": today_views,
            "comment_count": comment_count,
            "pending_count": pending,
        }
    )


@router.get("/admin/dashboard/recent-articles", dependencies=[Depends(require_blogger)])
async def recent_articles(
    limit: int = Query(5, ge=1, le=20), session: AsyncSession = Depends(get_session)
) -> dict:
    rows = await article_repo.get_recent(session, limit)
    return success(
        [
            {
                "id": a.id,
                "title": a.title,
                "summary": a.summary or "",
                "cover": a.cover or "",
                "view_count": a.view_count or 0,
                "created_at": a.created_at.strftime("%Y-%m-%d"),
            }
            for a in rows
        ]
    )


# ------------------------------------------------------------- rss/sitemap


def _site_url(request: Request) -> str:
    host = request.headers.get("host", "")
    if not host:
        return "https://myblog.com"
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    return f"{scheme}://{host}"


def _rfc1123(dt: datetime) -> str:
    """RFC1123 with numeric zone，RSS 的 pubDate 要求这个格式。"""
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0800")


@router.get("/feed.xml")
@router.get("/rss")
async def rss_feed(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    articles, _ = await article_repo.list_published(session, 0, 20, 0, 0, "")
    site = _site_url(request)

    items = []
    for article in articles:
        link = f"{site}/post/{article.slug}"
        items.append(
            "<item>"
            f"<title><![CDATA[{article.title}]]></title>"
            f"<link>{link}</link>"
            f'<guid isPermaLink="true">{link}</guid>'
            f"<description><![CDATA[{article.summary or ''}]]></description>"
            f"<pubDate>{_rfc1123(article.created_at)}</pubDate>"
            "</item>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
        "<channel>"
        "<title>我的博客</title>"
        f"<link>{site}</link>"
        "<description>分享技术、生活与思考</description>"
        "<language>zh-CN</language>"
        f"<lastBuildDate>{_rfc1123(datetime.now())}</lastBuildDate>"
        f'<atom:link href="{site}/api/v1/feed.xml" rel="self" type="application/rss+xml"/>'
        + "".join(items)
        + "</channel></rss>"
    )
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@router.get("/sitemap.xml")
async def sitemap(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    articles, _ = await article_repo.list_published(session, 0, 1000, 0, 0, "")
    site = _site_url(request)
    today = datetime.now().strftime("%Y-%m-%d")

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"<url><loc>{site}/</loc><lastmod>{today}</lastmod>"
        "<changefreq>daily</changefreq><priority>1.0</priority></url>",
    ]
    for article in articles:
        lastmod = (article.updated_at or article.created_at).strftime("%Y-%m-%d")
        parts.append(
            f"<url><loc>{site}/post/{article.slug}</loc><lastmod>{lastmod}</lastmod>"
            "<changefreq>weekly</changefreq><priority>0.8</priority></url>"
        )
    parts.append("</urlset>")

    return Response(content="".join(parts), media_type="application/xml; charset=utf-8")
