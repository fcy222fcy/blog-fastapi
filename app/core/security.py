"""JWT 与密码。

与 Go 版保持互操作：
- token 算法 HS256，claims 含 user_id / username / exp / iat / iss="blog"，
  因此 Go 服务签出的 token 在 Python 侧也能验，反之亦然。
- 密码用 bcrypt。Go 的 x/crypto/bcrypt 产出 $2a$ 前缀，Python bcrypt 库可直接校验。
"""

from __future__ import annotations

import time
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"
ISSUER = "blog"

# bcrypt 只处理前 72 字节，超长密码先截断，避免不同库抛错行为不一致
_BCRYPT_MAX_BYTES = 72


def _prepare(password: str) -> bytes:
    raw = password.encode("utf-8")
    return raw[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_prepare(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(user_id: int, username: str) -> tuple[str, int]:
    """生成 token，返回 (token, 过期时间戳秒)。

    过期时间戳与 Go 版一致，为绝对 Unix 秒，前端用它判断是否需要刷新。
    """
    now = int(time.time())
    expires_at = now + settings.jwt_expire_hours * 3600
    payload: dict[str, Any] = {
        "user_id": user_id,
        "username": username,
        "exp": expires_at,
        "iat": now,
        "iss": ISSUER,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
    return token, expires_at


def decode_token(token: str) -> dict[str, Any] | None:
    """解析 token；失败返回 None（含过期、签名错误、算法不符）。"""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "iat"]},
        )
    except jwt.PyJWTError:
        return None
