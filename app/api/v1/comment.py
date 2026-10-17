"""评论路由（/api/v1/comments 与 /api/v1/admin/comments）。

公开的三条路由挂 `optional_user`：登录了能拿到 user_id（用于博主标识），
没登录也照常读评论、发评论（游客评论是本站的默认形态）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_session, optional_user, require_blogger
from app.core.response import success
from app.schemas.requests import (
    BatchIdsRequest,
    CreateCommentRequest,
    UpdateCommentStatusRequest,
)
from app.services import comment_service

router = APIRouter(tags=["comment"])


def _client_ip(request: Request) -> str:
    """取真实客户端 IP。

    生产环境前面有 Nginx，`request.client.host` 会变成 127.0.0.1。
    这里优先读 X-Real-IP / X-Forwarded-For 的第一段（与 Go 版 TrustedProxies
    生效后的效果等价），都没有才用直连 IP。
    """
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.get("/comments/article/{article_param}")
async def list_comments(
    article_param: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    sort_by: str = "desc",
    session: AsyncSession = Depends(get_session),
    _: CurrentUser | None = Depends(optional_user),
) -> dict:
    data = await comment_service.get_comments_by_article(
        session, article_param, page, page_size, sort_by
    )
    return success(data)


@router.post("/comments")
async def create_comment(
    payload: CreateCommentRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser | None = Depends(optional_user),
) -> dict:
    comment_id = await comment_service.create_comment(
        session,
        payload,
        user_id=user.user_id if user else 0,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    return success({"id": comment_id})


@router.post("/comments/{comment_id}/like")
async def like_comment(
    comment_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    await comment_service.like_comment(session, comment_id, _client_ip(request))
    return success(None)


@router.delete("/comments/{comment_id}/like")
async def unlike_comment(
    comment_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    await comment_service.unlike_comment(session, comment_id, _client_ip(request))
    return success(None)


admin_router = APIRouter(
    prefix="/admin/comments", tags=["admin:comment"], dependencies=[Depends(require_blogger)]
)


@admin_router.get("")
async def admin_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: str = "",
    keyword: str = "",
    session: AsyncSession = Depends(get_session),
) -> dict:
    return success(
        await comment_service.admin_list_comments(session, page, page_size, status, keyword)
    )


@admin_router.put("/{comment_id}/status")
async def update_status(
    comment_id: int,
    payload: UpdateCommentStatusRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await comment_service.update_comment_status(session, comment_id, payload)
    return success(None)


@admin_router.delete("/{comment_id}")
async def delete_comment(comment_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    await comment_service.delete_comment(session, comment_id)
    return success(None)


@admin_router.post("/batch-delete")
async def batch_delete(payload: BatchIdsRequest, session: AsyncSession = Depends(get_session)) -> dict:
    await comment_service.batch_delete_comments(session, payload.ids)
    return success(None)
