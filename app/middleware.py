"""请求日志与审计中间件。

FastAPI 的中间件是「洋葱」模型：审计需要在 `call_next` **之后**才能拿到
状态码和响应内容，因此写成纯 ASGI 中间件而不是 `@app.middleware("http")`
里的顺序敏感代码。

审计只记三件事：
1. 方法属于写操作（POST/PUT/DELETE）
2. 路径落在 `/admin/` 下
3. 响应状态是 2xx

并且请求体里的敏感字段（password / token / secret…）在落库前替换成 `***`。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.http import client_ip

logger = logging.getLogger("blog.middleware")

SENSITIVE_KEYS = {
    "password",
    "old_password",
    "new_password",
    "token",
    "authorization",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
}

_TARGET_RE = re.compile(r"/admin/(\w[\w-]*)/?")

_TARGET_TYPE_MAP = {
    "articles": "article",
    "categories": "category",
    "tags": "tag",
    "comments": "comment",
    "daily-questions": "daily_question",
    "about": "about_page",
    "dashboard": "dashboard",
}

_ACTION_MAP = {"POST": "create", "PUT": "update", "DELETE": "delete"}


def sanitize_body(raw: bytes) -> str:
    """脱敏请求体，防止明文密码/令牌落库。"""
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return raw.decode("utf-8", errors="replace")[:500]
    if not isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False)[:500]
    for key in list(payload.keys()):
        if str(key).lower().strip() in SENSITIVE_KEYS:
            payload[key] = "***"
    return json.dumps(payload, ensure_ascii=False)[:500]


def extract_title(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("title", "name", "nickname"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value[:200]
    return ""


def _target_type(path: str) -> str:
    match = _TARGET_RE.search(path)
    if not match:
        return "unknown"
    module = match.group(1)
    return _TARGET_TYPE_MAP.get(module, module)


def _target_id(path: str) -> int:
    """路径最后一段若是纯数字就当作 target_id。"""
    segment = path.rstrip("/").rsplit("/", 1)[-1]
    return int(segment) if segment.isdigit() else 0


class RequestLogMiddleware(BaseHTTPMiddleware):
    """记录每条请求的方法、路径、状态码与耗时（对应 Go 版 Logger 中间件）。"""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            logger.error("%s %s 500 %.1fms", request.method, request.url.path, elapsed)
            raise
        elapsed = (time.perf_counter() - started) * 1000
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            level,
            "%s %s %s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )
        return response


class AuditMiddleware(BaseHTTPMiddleware):
    """自动记录后台写操作。

    只读请求、非 admin 路径、失败请求都不记——审计表要的是「谁成功改了什么」，
    混进大量 404 会让它失去检索价值。
    """

    _MAX_BODY = 1024 * 1024  # 超过 1MB 的请求体不做审计（附件上传等）

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        action = _ACTION_MAP.get(request.method, "")
        path = request.url.path
        if not action or "/admin/" not in path:
            return await call_next(request)

        body = b""
        content_length = request.headers.get("content-length")
        if request.method in ("POST", "PUT") and content_length and int(content_length) <= self._MAX_BODY:
            body = await request.body()
            # 读完 body 后要把它塞回去，否则下游拿不到请求体。
            # Starlette 没有公开 setter，这里直接赋 _body（社区通行做法）。
            request._body = body

        response = await call_next(request)

        if 200 <= response.status_code < 300:
            from app.core.security import decode_token
            from app.services import audit_service

            token = (request.headers.get("authorization") or "").split(" ", 1)
            operator_id, operator_name = 0, ""
            if len(token) == 2 and token[0] == "Bearer":
                claims = decode_token(token[1].strip()) or {}
                operator_id = int(claims.get("user_id") or 0)
                operator_name = str(claims.get("username") or "")

            await audit_service.write_audit_log(
                operator_id=operator_id,
                operator_name=operator_name,
                action=action,
                target_type=_target_type(path),
                target_id=_target_id(path),
                target_title=extract_title(body),
                detail=sanitize_body(body),
                ip=client_ip(request),
                user_agent=(request.headers.get("user-agent") or "")[:500],
            )

        return response
