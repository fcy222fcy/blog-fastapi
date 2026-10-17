"""审计日志与关于页面数据访问。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.about_page import AboutPage
from app.models.audit import AuditLog


async def create_audit_log(session: AsyncSession, log: AuditLog) -> None:
    session.add(log)
    await session.flush()


async def list_audit_logs(
    session: AsyncSession, offset: int, limit: int, action: str = "", target_type: str = ""
) -> tuple[list[AuditLog], int]:
    conditions: list[Any] = []
    if action:
        conditions.append(AuditLog.action == action)
    if target_type:
        conditions.append(AuditLog.target_type == target_type)

    total = int((await session.execute(select(func.count(AuditLog.id)).where(*conditions))).scalar() or 0)
    stmt = (
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total


async def get_about_page(session: AsyncSession) -> AboutPage | None:
    stmt = select(AboutPage).order_by(AboutPage.id.asc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def save_about_page(session: AsyncSession, page: AboutPage) -> AboutPage:
    session.add(page)
    await session.flush()
    return page
