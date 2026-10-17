"""审计日志业务逻辑。

设计原则与 Go 版一致：**审计写入永远不能拖垮业务**。
中间件在请求成功后把日志丢进后台任务，即使写库失败也只落一行 warn。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import normalize_page
from app.db.session import session_scope
from app.models.audit import AuditLog
from app.repositories import misc_repository as repo

logger = logging.getLogger("blog.service.audit")


async def write_audit_log(
    *,
    operator_id: int,
    operator_name: str,
    action: str,
    target_type: str,
    target_id: int,
    target_title: str,
    detail: str,
    ip: str,
    user_agent: str,
) -> None:
    """独立开启会话写审计，避免与请求事务耦合（请求可能已提交或回滚）。"""
    try:
        async with session_scope() as session:
            await repo.create_audit_log(
                session,
                AuditLog(
                    operator_id=operator_id,
                    operator_name=operator_name,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    target_title=target_title,
                    detail=detail,
                    ip=ip,
                    user_agent=user_agent,
                ),
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("创建审计日志失败: %s", exc)


async def list_audit_logs(
    session: AsyncSession, page: int = 1, page_size: int = 20, action: str = "", target_type: str = ""
) -> dict:
    page, page_size = normalize_page(page, page_size, default_size=20)
    rows, total = await repo.list_audit_logs(
        session, (page - 1) * page_size, page_size, action, target_type
    )

    items = [
        {
            "id": row.id,
            "operator_id": row.operator_id or 0,
            "operator_name": row.operator_name or "",
            "action": row.action,
            "target_type": row.target_type or "",
            "target_id": row.target_id or 0,
            "target_title": row.target_title or "",
            "detail": row.detail or "",
            "ip": row.ip or "",
            "created_at": row.created_at,
        }
        for row in rows
    ]

    return {
        "list": items,
        "total": total,
        "page": page,
        "size": page_size,
        "total_page": (total + page_size - 1) // page_size if page_size else 0,
    }
