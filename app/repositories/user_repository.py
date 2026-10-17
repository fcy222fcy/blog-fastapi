"""用户数据访问。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def find_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def find_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def find_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def find_first(session: AsyncSession) -> User | None:
    """博客主人 = 表里 ID 最小的那条（与 Go 版 FindFirstAdmin 等价）。"""
    result = await session.execute(select(User).order_by(User.id.asc()).limit(1))
    return result.scalar_one_or_none()


async def create(session: AsyncSession, user: User) -> User:
    session.add(user)
    await session.flush()
    return user


async def save(session: AsyncSession, user: User) -> None:
    await session.flush()
