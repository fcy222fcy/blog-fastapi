"""认证与用户业务逻辑。

登录有两套身份来源，顺序不能反：

1. **博主**：用户名/邮箱 + 明文密码匹配配置。命中后签发 `user_id = blogger_user_id`
   的 token，后台的 RequireBlogger 就是靠这个固定 ID 做鉴权的。
2. **普通用户**：按邮箱优先、用户名其次查库，bcrypt 校验。

注册时用户名可留空，由邮箱前缀自动生成并处理冲突（`foo` → `foo_1` → `foo_2`）。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import (
    CODE_ACCOUNT_DISABLED,
    CODE_INVALID_EMAIL,
    CODE_INVALID_PARAMS,
    CODE_PASSWORD_INCORRECT,
    CODE_USERNAME_TOO_SHORT,
    CODE_USER_ALREADY_EXISTS,
    CODE_USER_NOT_FOUND,
    BizError,
)
from app.core.security import create_token, hash_password, verify_password
from app.models.user import User
from app.repositories import user_repository as user_repo
from app.schemas.requests import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    UpdateUserRequest,
)

logger = logging.getLogger("blog.service.auth")


def is_blogger(user_id: int | None) -> bool:
    return bool(user_id) and user_id == settings.blogger_user_id


def _blogger_user_payload(user_id: int) -> dict:
    return {
        "id": user_id,
        "username": settings.blogger_username,
        "nickname": settings.blogger_nickname,
        "avatar": settings.blogger_avatar,
        "email": settings.blogger_email,
    }


async def _blogger_display(session: AsyncSession) -> dict:
    """博主的展示信息：DB 优先，缺失回退配置（与 /api/v1/user/info 同源）。"""
    payload = _blogger_user_payload(settings.blogger_user_id)
    db_user = await user_repo.find_by_id(session, settings.blogger_user_id)
    if db_user is not None:
        payload["nickname"] = db_user.nickname or payload["nickname"]
        payload["avatar"] = db_user.avatar or payload["avatar"]
        payload["email"] = db_user.email or payload["email"]
        payload["username"] = db_user.username or payload["username"]
    return payload


def _blogger_login_by_username(username: str | None, password: str) -> bool:
    return bool(username) and username.strip().lower() == settings.blogger_username.strip().lower() and (
        password.strip() == settings.blogger_password.strip()
    )


def _blogger_login_by_email(email: str | None, password: str) -> bool:
    return bool(email) and email.strip().lower() == settings.blogger_email.strip().lower() and (
        password.strip() == settings.blogger_password.strip()
    )


async def login(session: AsyncSession, req: LoginRequest) -> dict:
    if not req.validate_login():
        raise BizError(CODE_INVALID_PARAMS, "请输入用户名或邮箱")

    if _blogger_login_by_username(req.username, req.password) or _blogger_login_by_email(
        req.email, req.password
    ):
        token, expires_at = create_token(settings.blogger_user_id, settings.blogger_username)
        user = await _blogger_display(session)
        logger.info("博主登录成功 username=%s", settings.blogger_username)
        return {"token": token, "expires_at": expires_at, "user": user}

    user: User | None = None
    login_id = ""
    if req.email:
        login_id = req.email.strip()
        user = await user_repo.find_by_email(session, login_id)
    if user is None and req.username:
        login_id = req.username.strip()
        user = await user_repo.find_by_username(session, login_id)

    if user is None:
        logger.warning("用户不存在 login=%s", login_id)
        raise BizError(CODE_USER_NOT_FOUND, "账号或密码错误")

    if not verify_password(req.password, user.password):
        raise BizError(CODE_PASSWORD_INCORRECT, "账号或密码错误")

    if user.status != 1:
        raise BizError(CODE_ACCOUNT_DISABLED)

    token, expires_at = create_token(user.id, user.username)
    logger.info("用户登录成功 username=%s", user.username)
    return {
        "token": token,
        "expires_at": expires_at,
        "user": {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname or "",
            "avatar": user.avatar or "",
            "email": user.email or "",
        },
    }


async def get_profile(session: AsyncSession, user_id: int) -> dict:
    if is_blogger(user_id):
        payload = await _blogger_display(session)
        db_user = await user_repo.find_by_id(session, user_id)
        return {
            "id": user_id,
            "username": payload["username"],
            "nickname": payload["nickname"],
            "email": payload["email"],
            "avatar": payload["avatar"],
            "bio": (db_user.bio if db_user else "") or "",
            "social_links": [],
        }

    user = await user_repo.find_by_id(session, user_id)
    if user is None:
        raise BizError(CODE_USER_NOT_FOUND)
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname or "",
        "email": user.email or "",
        "avatar": user.avatar or "",
        "bio": user.bio or "",
        "social_links": [],
    }


async def change_password(session: AsyncSession, user_id: int, req: ChangePasswordRequest) -> None:
    if is_blogger(user_id):
        if req.old_password.strip() != settings.blogger_password.strip():
            raise BizError(CODE_PASSWORD_INCORRECT)
        # 与 Go 版一致：只改进程内配置。生产环境请通过 BLOGGER_PASSWORD 环境变量固化，
        # 否则重启后回到配置文件里的旧密码。
        object.__setattr__(settings, "blogger_password", req.new_password.strip())
        logger.warning(
            "博主密码已在运行期修改（仅内存生效），记得同步更新 BLOGGER_PASSWORD 环境变量"
        )
        return

    user = await user_repo.find_by_id(session, user_id)
    if user is None:
        raise BizError(CODE_USER_NOT_FOUND)
    if not verify_password(req.old_password, user.password):
        raise BizError(CODE_PASSWORD_INCORRECT)

    user.password = hash_password(req.new_password)
    await user_repo.save(session, user)
    await session.commit()
    logger.info("修改密码成功 user_id=%s", user_id)


def _sanitize_username(value: str) -> str:
    cleaned = "".join(c for c in value if c.isalnum() or c in ("_", "-"))
    return cleaned


async def _generate_username(session: AsyncSession, email: str) -> str:
    base = email.split("@", 1)[0] if "@" in email else email
    base = _sanitize_username(base) or "user"
    if len(base) < 3:
        base = f"{base}user"
    base = base[:50]

    candidate = base
    counter = 1
    while await user_repo.find_by_username(session, candidate):
        suffix = str(counter)
        max_base = 50 - len(suffix) - 1
        candidate = f"{base[:max_base]}_{suffix}"
        counter += 1
        if counter > 100:
            raise BizError(CODE_INVALID_PARAMS, "生成用户名失败，请稍后重试")
    return candidate


async def register(session: AsyncSession, req: RegisterRequest) -> None:
    email = (str(req.email) or "").strip()
    nickname = (req.nickname or "").strip()
    if not email:
        raise BizError(CODE_INVALID_EMAIL, "邮箱不能为空")
    if not nickname:
        raise BizError(CODE_INVALID_PARAMS, "昵称不能为空")

    if await user_repo.find_by_email(session, email):
        logger.warning("邮箱已存在 email=%s", email)
        raise BizError(CODE_USER_ALREADY_EXISTS, "该邮箱已被注册")

    if req.username and req.username.strip():
        username = req.username.strip()
        if len(username) < 3:
            raise BizError(CODE_USERNAME_TOO_SHORT)
        username = username[:50]
        if await user_repo.find_by_username(session, username):
            raise BizError(CODE_USER_ALREADY_EXISTS)
    else:
        username = await _generate_username(session, email)

    user = User(
        username=username,
        password=hash_password(req.password),
        nickname=nickname,
        email=email,
        status=1,
    )
    await user_repo.create(session, user)
    await session.commit()
    logger.info("用户注册成功 username=%s email=%s", username, email)


async def get_user_by_id(session: AsyncSession, user_id: int) -> User:
    user = await user_repo.find_by_id(session, user_id)
    if user is None and is_blogger(user_id):
        user = await ensure_blogger_user(session)
    if user is None:
        raise BizError(CODE_USER_NOT_FOUND)
    return user


async def ensure_blogger_user(session: AsyncSession) -> User:
    """博主在 users 表里没有记录时按配置补一条（幂等）。

    这条记录承担两个作用：主页 /user/info 有数据可读、评论里的昵称头像有源头。
    """
    existing = await user_repo.find_by_id(session, settings.blogger_user_id)
    if existing is not None:
        return existing

    user = User(
        id=settings.blogger_user_id,
        username=settings.blogger_username,
        password=hash_password(settings.blogger_password or "change-me"),
        nickname=settings.blogger_nickname,
        email=settings.blogger_email,
        avatar=settings.blogger_avatar,
        status=1,
    )
    await user_repo.create(session, user)
    await session.commit()
    logger.info("自动创建博主用户 id=%s username=%s", user.id, user.username)
    return user


async def update_user(session: AsyncSession, user_id: int, req: UpdateUserRequest) -> None:
    user = await user_repo.find_by_id(session, user_id)
    if user is None and is_blogger(user_id):
        user = await ensure_blogger_user(session)
    if user is None:
        raise BizError(CODE_USER_NOT_FOUND)

    if req.nickname:
        user.nickname = req.nickname
    if req.email:
        user.email = req.email
    if req.avatar:
        user.avatar = req.avatar
    if req.bio:
        user.bio = req.bio

    await user_repo.save(session, user)
    await session.commit()
    logger.info("更新用户信息成功 id=%s", user_id)


async def get_public_user_info(session: AsyncSession) -> dict:
    """公开的博主信息。查不到时给一份兜底文案，前端页面不会出现空白。"""
    user = await user_repo.find_first(session)
    if user is None:
        return {
            "nickname": "Fu Chengyan",
            "bio": "日常落灰的个人博客，擅长面向搜索引擎编程。分享 Golang 开发、AI 和 NAS 折腾经验",
            "avatar": "",
        }
    return {
        "nickname": user.nickname or "",
        "bio": user.bio or "",
        "avatar": user.avatar or "",
    }
