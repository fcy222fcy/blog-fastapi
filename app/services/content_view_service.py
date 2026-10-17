"""浏览量统计与关于页面业务逻辑。"""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    CODE_INVALID_PARAMS,
    CODE_NOT_FOUND,
    UnsupportedContentType,
    ViewTargetNotFound,
    BizError,
)
from app.core.visitor import VisitorIdentityError, derive_key
from app.core.config import settings
from app.models.about_page import AboutPage
from app.models.audit import CONTENT_TYPE_ARTICLE
from app.repositories import content_view_repository as view_repo
from app.repositories import misc_repository as misc_repo

logger = logging.getLogger("blog.service.content_view")

try:
    SHANGHAI = zoneinfo.ZoneInfo("Asia/Shanghai")
except zoneinfo.ZoneInfoNotFoundError:  # pragma: no cover - Windows 无 tzdata 时兜底
    from datetime import timedelta, timezone

    SHANGHAI = timezone(timedelta(hours=8))


def shanghai_today() -> "datetime.date":
    return datetime.now(SHANGHAI).date()


async def record_view(
    session: AsyncSession,
    content_type: str,
    content_id: int,
    anonymous_id: str | None,
    client_ip: str | None,
) -> dict:
    try:
        visitor_key = derive_key(settings.jwt_secret, anonymous_id, client_ip)
    except VisitorIdentityError:
        raise BizError(CODE_INVALID_PARAMS, "无法识别访客") from None

    try:
        counted, view_count = await view_repo.record_view(
            session, content_type, content_id, visitor_key, shanghai_today()
        )
    except UnsupportedContentType:
        raise BizError(CODE_INVALID_PARAMS) from None
    except ViewTargetNotFound:
        raise BizError(CODE_NOT_FOUND, "内容不存在") from None

    await session.commit()
    return {"counted": counted, "view_count": view_count}


async def count_today(session: AsyncSession, content_type: str = CONTENT_TYPE_ARTICLE) -> int:
    return await view_repo.count_by_date(session, content_type, shanghai_today())


# ------------------------------------------------------------------ about page

_DEFAULT_ABOUT = {
    "title": "关于我",
    "subtitle": "Go 开发者 / 独立游戏开发者",
    "bio": "来自中国的程序员，擅长游戏和后端开发，喜欢玩游戏和骑自行车。",
    "skills": '["Golang","Erlang","Unity","Docker"]',
    "about_me": (
        '[{"label":"职业","value":"Go 开发者","icon":"💼"},'
        '{"label":"爱好","value":"游戏 / 骑行","icon":"🎮"},'
        '{"label":"技术栈","value":"Go / Erlang / Unity","icon":"🛠"},'
        '{"label":"邮箱","value":"3181088318@qq.com","icon":"✉️"}]'
    ),
    "about_site": (
        '[{"label":"框架","value":"Go + Gin","icon":"⚙️"},'
        '{"label":"前端","value":"Vue 3","icon":"🎨"},'
        '{"label":"部署","value":"Docker","icon":"☁️"}]'
    ),
    "projects": (
        '[{"name":"GitHub","description":"我的 GitHub 主页，包含各种编程项目。",'
        '"url":"https://github.com/fcy222fcy","icon":"⌘"},'
        '{"name":"DesktopSnap","description":"Windows 桌面图标保存和恢复工具。",'
        '"url":"https://desktopsnap.fcyan.xyz/","icon":"🖥"}]'
    ),
    "contact_info": (
        '[{"label":"GitHub","value":"fcy222fcy","icon":"🐙","url":"https://github.com/fcy222fcy"}]'
    ),
    "site_history": "[]",
}


def _sort_site_history(raw: str | None) -> str:
    """建站历程按日期升序（最早在前）。解析失败时原样返回，不吞用户内容。"""
    import json

    if not raw:
        return "[]"
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(items, list):
        return raw
    try:
        items.sort(key=lambda item: str(item.get("date", "")))
    except AttributeError:
        return raw
    return json.dumps(items, ensure_ascii=False)


async def get_about_page(session: AsyncSession) -> dict:
    page = await misc_repo.get_about_page(session)
    if page is None:
        return {"id": 0, **_DEFAULT_ABOUT}

    return {
        "id": page.id,
        "title": page.title or "",
        "subtitle": page.subtitle or "",
        "bio": page.bio or "",
        "skills": page.skills or "",
        "about_me": page.about_me or "",
        "about_site": page.about_site or "",
        "projects": page.projects or "",
        "contact_info": page.contact_info or "",
        "site_history": _sort_site_history(page.site_history),
    }


async def update_about_page(session: AsyncSession, req) -> None:
    page = await misc_repo.get_about_page(session)
    if page is None:
        page = AboutPage()

    page.title = req.title
    page.subtitle = req.subtitle
    page.bio = req.bio
    page.skills = req.skills
    page.about_me = req.about_me
    page.about_site = req.about_site
    page.projects = req.projects
    page.contact_info = req.contact_info
    page.site_history = _sort_site_history(req.site_history)

    await misc_repo.save_about_page(session, page)
    await session.commit()
    logger.info("关于页面已更新")
