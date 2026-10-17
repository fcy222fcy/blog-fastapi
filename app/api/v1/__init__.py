"""API v1 路由聚合。

挂载顺序与 Go 版 routes.go 一致，便于对照排查：
auth → user → article → category/tag → comment → daily-question →
content-view → media → audit → feed/sitemap。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    article,
    auth,
    comment,
    daily_question,
    media,
    misc,
    taxonomy,
    user,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(user.router)
api_router.include_router(article.router)
api_router.include_router(article.admin_router)
api_router.include_router(taxonomy.router)
api_router.include_router(taxonomy.admin_router)
api_router.include_router(comment.router)
api_router.include_router(comment.admin_router)
api_router.include_router(daily_question.router)
api_router.include_router(daily_question.admin_router)
api_router.include_router(media.router)
api_router.include_router(misc.router)
