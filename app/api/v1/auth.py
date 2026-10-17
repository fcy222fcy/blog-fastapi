"""认证路由（/api/v1/auth）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, current_user, get_session
from app.core.response import success
from app.schemas.requests import ChangePasswordRequest, LoginRequest, RegisterRequest
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)) -> dict:
    return success(await auth_service.login(session, payload))


@router.post("/register")
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_session)) -> dict:
    await auth_service.register(session, payload)
    return success(None)


@router.put("/password")
async def change_password(
    payload: ChangePasswordRequest,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await auth_service.change_password(session, user.user_id, payload)
    return success(None)
