"""FastAPI 依赖：会话、鉴权、博主校验。

Go 版把这三件事拆成 `Auth` / `OptionalAuth` / `RequireBlogger` 三个中间件，
挂载顺序是 Auth 再 RequireBlogger。这里用 FastAPI 的依赖链表达同一套语义：

- `current_user`   → 必须有合法 Bearer token，否则 401
- `optional_user`  → 有 token 就解析，没有或无效都放行（评论列表/发评论用）
- `require_blogger`→ 在 `current_user` 之上再校验 user_id 是否等于配置的博主 ID

**RequireBlogger 绝不能省**：任何前台注册用户拿到合法 token 都能通过 Auth，
少了这一层就等于把后台开放给所有注册用户。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import (
    CODE_FORBIDDEN,
    CODE_UNAUTHORIZED,
    BizError,
)
from app.core.security import decode_token
from app.db.session import get_session


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    username: str

    @property
    def is_blogger(self) -> bool:
        return bool(settings.blogger_user_id) and self.user_id == settings.blogger_user_id


def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        return None
    return parts[1].strip() or None


async def current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization:
        raise BizError(CODE_UNAUTHORIZED, "缺少认证信息", status=401)

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        raise BizError(CODE_UNAUTHORIZED, "认证格式错误", status=401)

    claims = decode_token(parts[1].strip())
    if claims is None:
        raise BizError(CODE_UNAUTHORIZED, "Token 无效或已过期", status=401)

    return CurrentUser(user_id=int(claims.get("user_id") or 0), username=str(claims.get("username") or ""))


async def optional_user(authorization: str | None = Header(default=None)) -> CurrentUser | None:
    """可选认证：任何异常都按游客处理，不阻断请求。"""
    token = _parse_bearer(authorization)
    if not token:
        return None
    claims = decode_token(token)
    if claims is None:
        return None
    return CurrentUser(user_id=int(claims.get("user_id") or 0), username=str(claims.get("username") or ""))


async def require_blogger(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not settings.blogger_user_id:
        # 未配置博主 ID 时必须拒绝：游客的 user_id 也是 0，放行等于全员后台
        raise BizError(CODE_FORBIDDEN, "博主账号未配置", status=403)
    if user.user_id != settings.blogger_user_id:
        raise BizError(CODE_FORBIDDEN, "无权访问", status=403)
    return user


__all__ = [
    "CurrentUser",
    "current_user",
    "optional_user",
    "require_blogger",
    "get_session",
    "AsyncSession",
]
