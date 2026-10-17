"""评论业务逻辑。

三条硬规则，任何一条放宽都会出问题：

1. **博主身份以服务端配置为准**。登录态 user_id 等于 `blogger_user_id` 时，
   昵称/邮箱/头像一律用服务端数据覆盖前端传值，否则任何人都能 cosplay 博主。
2. **评论数只统计 approved**。新建评论默认 approved（本站不做先审后发），
   但后台把状态改成 rejected 时要同步 -1，且带下限保护。
3. **点赞按 IP 去重**，靠 `comment_like_logs` 的唯一索引，不靠先查后写。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.avatar import avatar_url_by_email
from app.core.config import settings
from app.core.errors import (
    CODE_ARTICLE_NOT_FOUND,
    CODE_COMMENT_NOT_FOUND,
    CODE_INVALID_PARAMS,
    BizError,
)
from app.core.response import normalize_page
from app.core.ua import UNKNOWN, parse as parse_ua
from app.models.comment import Comment, STATUS_APPROVED
from app.repositories import article_repository as article_repo
from app.repositories import comment_repository as repo
from app.repositories import user_repository as user_repo
from app.schemas.requests import CreateCommentRequest, UpdateCommentStatusRequest
from app.schemas.responses import CommentResponse
from app.services import email_service

logger = logging.getLogger("blog.service.comment")


def _is_blogger(user_id: int | None) -> bool:
    return bool(user_id) and user_id == settings.blogger_user_id


def _client_info(comment: Comment) -> tuple[str, str, str, str]:
    """客户端信息：优先读库里已存的列，历史空数据才回退到解析 UA。"""
    stored_os = comment.os or ""
    stored_browser = comment.browser or ""
    if (stored_os and stored_os != UNKNOWN) or (stored_browser and stored_browser != UNKNOWN):
        return (
            stored_os if stored_os != UNKNOWN else "",
            comment.os_version or "" if stored_os != UNKNOWN else "",
            stored_browser if stored_browser != UNKNOWN else "",
            comment.browser_version or "" if stored_browser != UNKNOWN else "",
        )

    if (comment.user_agent or "").strip():
        info = parse_ua(comment.user_agent)
        return (
            "" if info.os == UNKNOWN else info.os,
            "" if info.os == UNKNOWN else info.os_version,
            "" if info.browser == UNKNOWN else info.browser,
            "" if info.browser == UNKNOWN else info.browser_version,
        )
    return "", "", "", ""


def to_response(
    comment: Comment,
    replies: list[Comment] | None = None,
    reply_to_names: dict[int, str] | None = None,
    with_article: bool = False,
) -> dict:
    os_name, os_version, browser, browser_version = _client_info(comment)

    avatar = comment.avatar or ""
    if not avatar and (comment.email or ""):
        avatar = avatar_url_by_email(comment.email, 80)

    reply_to = ""
    if reply_to_names:
        target = comment.reply_to_id or comment.parent_id
        if target:
            reply_to = reply_to_names.get(target, "")

    payload = {
        "id": comment.id,
        "content": comment.content,
        "nickname": comment.nickname or "",
        "email": comment.email or "",
        "website": comment.website or "",
        "avatar": avatar,
        "status": comment.status,
        "is_admin": _is_blogger(comment.user_id),
        "reply_to": reply_to,
        "like_count": comment.like_count or 0,
        "os": os_name,
        "os_version": os_version,
        "browser": browser,
        "browser_version": browser_version,
        "article": {"id": 0, "title": "", "slug": ""},
        "parent_id": comment.parent_id,
        "created_at": comment.created_at,
    }

    article = getattr(comment, "article", None)
    if with_article and article is not None and article.id:
        payload["article"] = {"id": article.id, "title": article.title, "slug": article.slug}

    if replies:
        payload["replies"] = [
            to_response(child, reply_to_names=reply_to_names) for child in replies
        ]

    return CommentResponse(**payload).dump()


async def get_comments_by_article(
    session: AsyncSession,
    article_param: str,
    page: int = 1,
    page_size: int = 10,
    sort_by: str = "desc",
) -> dict:
    page, page_size = normalize_page(page, page_size)

    if article_param.isdigit():
        article_id = int(article_param)
    else:
        article = await article_repo.find_by_slug(session, article_param)
        if article is None:
            raise BizError(CODE_ARTICLE_NOT_FOUND)
        article_id = article.id

    normalized_sort = (sort_by or "").strip().lower()
    if normalized_sort not in ("asc", "desc", "hot"):
        normalized_sort = "desc"

    roots, total, replies_map = await repo.list_by_article(
        session, article_id, (page - 1) * page_size, page_size, normalized_sort
    )

    # 一次性取「被回复人昵称」，避免逐条查询
    all_in_page: list[Comment] = list(roots)
    for items in replies_map.values():
        all_in_page.extend(items)
    names = await repo.reply_to_nicknames(session, all_in_page)

    items = [to_response(root, replies_map.get(root.id), names) for root in roots]

    return {
        "list": items,
        "total": total,
        "page": page,
        "size": page_size,
        "total_page": (total + page_size - 1) // page_size if page_size else 0,
    }


async def create_comment(
    session: AsyncSession,
    req: CreateCommentRequest,
    user_id: int,
    ip: str,
    user_agent: str,
) -> int:
    if not (req.content or "").strip():
        raise BizError(CODE_INVALID_PARAMS, "评论内容不能为空")
    if not (req.nickname or "").strip():
        raise BizError(CODE_INVALID_PARAMS, "昵称不能为空")

    if req.article_slug:
        article = await article_repo.find_by_slug(session, req.article_slug)
    elif req.article_id:
        article = await article_repo.find_by_id(session, req.article_id)
    else:
        article = None
    if article is None:
        raise BizError(CODE_ARTICLE_NOT_FOUND)

    comment = Comment(
        content=req.content,
        nickname=req.nickname,
        email=req.email or "",
        website=req.website or "",
        article_id=article.id,
        parent_id=req.parent_id,
        reply_to_id=req.reply_to_id,
        status=STATUS_APPROVED,
        ip=ip,
        user_agent=(user_agent or "")[:500],
    )

    ua_info = parse_ua(user_agent)
    if (req.os or "").strip() and req.os != UNKNOWN:
        comment.os = req.os.strip()
        comment.os_version = (req.os_version or "").strip()
    elif ua_info.os != UNKNOWN:
        comment.os = ua_info.os
        comment.os_version = ua_info.os_version

    if (req.browser or "").strip() and req.browser != UNKNOWN:
        comment.browser = req.browser.strip()
        comment.browser_version = (req.browser_version or "").strip()
    elif ua_info.browser != UNKNOWN:
        comment.browser = ua_info.browser
        comment.browser_version = ua_info.browser_version

    if user_id:
        if _is_blogger(user_id):
            # 博主：强制覆盖前端传值，展示信息优先取用户表，其次回退配置
            nickname = settings.blogger_nickname
            email = settings.blogger_email
            avatar = settings.blogger_avatar
            db_user = await user_repo.find_by_id(session, user_id)
            if db_user is not None:
                nickname = db_user.nickname or nickname
                email = db_user.email or email
                avatar = db_user.avatar or avatar
            comment.user_id = user_id
            comment.nickname = nickname
            comment.email = email
            comment.avatar = avatar
        else:
            db_user = await user_repo.find_by_id(session, user_id)
            if db_user is not None:
                comment.user_id = user_id
                comment.nickname = comment.nickname or db_user.nickname or ""
                comment.email = comment.email or db_user.email or ""
                comment.avatar = comment.avatar or db_user.avatar or ""

    if not comment.avatar and comment.email:
        comment.avatar = avatar_url_by_email(comment.email, 80)

    await repo.create(session, comment)
    await article_repo.update_comment_count(session, article.id, 1)
    await session.commit()

    logger.info("评论创建成功 id=%s article=%s nickname=%s", comment.id, article.id, comment.nickname)

    # 邮件通知在后台发，失败只记日志，绝不影响评论落库
    try:
        asyncio.get_running_loop().create_task(
            email_service.notify_new_comment(
                comment=comment,
                article_title=article.title,
                article_slug=article.slug,
                target_email=await _resolve_reply_target_email(session, comment),
            )
        )
    except RuntimeError:
        pass

    return comment.id


async def _resolve_reply_target_email(session: AsyncSession, comment: Comment) -> str | None:
    """回复评论时通知被回复者（优先 reply_to_id，无则父评论）。"""
    target_id = comment.reply_to_id or comment.parent_id
    if not target_id:
        return None
    target = await repo.find_by_id(session, target_id)
    if target is None or not target.email or target.email == comment.email:
        return None
    return target.email


async def admin_list_comments(
    session: AsyncSession, page: int = 1, page_size: int = 10, status: str = "", keyword: str = ""
) -> dict:
    page, page_size = normalize_page(page, page_size)
    if status and status not in ("pending", "approved", "rejected"):
        raise BizError(CODE_INVALID_PARAMS, "无效的评论状态")

    rows, total = await repo.admin_list(session, (page - 1) * page_size, page_size, status, keyword)
    names = await repo.reply_to_nicknames(session, rows)
    items = [to_response(row, reply_to_names=names, with_article=True) for row in rows]

    return {
        "list": items,
        "total": total,
        "page": page,
        "size": page_size,
        "total_page": (total + page_size - 1) // page_size if page_size else 0,
    }


async def update_comment_status(
    session: AsyncSession, comment_id: int, req: UpdateCommentStatusRequest
) -> None:
    comment = await repo.find_by_id(session, comment_id)
    if comment is None:
        raise BizError(CODE_COMMENT_NOT_FOUND)

    old_status = comment.status
    comment.status = req.status
    await repo.save(session, comment)

    if old_status != req.status:
        if req.status == STATUS_APPROVED and old_status != STATUS_APPROVED:
            await article_repo.update_comment_count(session, comment.article_id, 1)
        elif old_status == STATUS_APPROVED and req.status != STATUS_APPROVED:
            await article_repo.update_comment_count(session, comment.article_id, -1)

    await session.commit()


async def delete_comment(session: AsyncSession, comment_id: int) -> None:
    comment = await repo.find_by_id(session, comment_id)
    if comment is None:
        raise BizError(CODE_COMMENT_NOT_FOUND)

    article_id = comment.article_id
    counted = comment.status == STATUS_APPROVED

    await repo.delete_comment(session, comment_id)
    if counted:
        await article_repo.update_comment_count(session, article_id, -1)
    await session.commit()


async def batch_delete_comments(session: AsyncSession, ids: Sequence[int]) -> None:
    if not ids:
        return

    comments = await repo.find_many(session, ids)
    delta_by_article: dict[int, int] = {}
    for comment in comments:
        if comment.status == STATUS_APPROVED:
            delta_by_article[comment.article_id] = delta_by_article.get(comment.article_id, 0) + 1

    await repo.batch_delete(session, ids)
    for article_id, delta in delta_by_article.items():
        await article_repo.update_comment_count(session, article_id, -delta)
    await session.commit()


async def like_comment(session: AsyncSession, comment_id: int, visitor_ip: str) -> None:
    comment = await repo.find_by_id(session, comment_id)
    if comment is None:
        raise BizError(CODE_COMMENT_NOT_FOUND)
    await repo.like_with_log(session, comment_id, visitor_ip)
    await session.commit()


async def unlike_comment(session: AsyncSession, comment_id: int, visitor_ip: str) -> None:
    comment = await repo.find_by_id(session, comment_id)
    if comment is None:
        raise BizError(CODE_COMMENT_NOT_FOUND)
    await repo.unlike_with_log(session, comment_id, visitor_ip)
    await session.commit()
