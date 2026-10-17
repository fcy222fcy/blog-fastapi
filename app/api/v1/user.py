"""用户路由（/api/v1/user）。

`/info` 是公开接口（前台首页展示博主信息），`/profile` 需要登录。
注意这两个返回的数据源刻意保持同源（用户表优先、配置兜底），否则同一个博主
在评论区与关于页会显示成两个人。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, current_user, get_session
from app.core.response import success
from app.schemas.requests import UpdateUserRequest
from app.services import auth_service

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/info")
async def public_info(session: AsyncSession = Depends(get_session)) -> dict:
    return success(await auth_service.get_public_user_info(session))


@router.get("/profile")
async def get_profile(
    user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> dict:
    return success(await auth_service.get_profile(session, user.user_id))


@router.put("/profile")
async def update_profile(
    payload: UpdateUserRequest,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await auth_service.update_user(session, user.user_id, payload)
    return success(None)
