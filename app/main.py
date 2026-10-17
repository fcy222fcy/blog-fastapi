"""FastAPI 应用入口。

启动顺序对齐 Go 版 app.Run()：
加载配置 → 初始化日志 → 建表 → 连接 Redis → 灌种子数据 → 启动定时任务 → 起服务

两处关键约定：
1. **所有错误都返回 `{code, message, data}` 信封**，包括 422 校验错误——
   否则前端统一拦截器会把校验失败当成网络异常吞掉，用户看不到提示。
2. **CORS 只放行白名单来源并允许凭证**，不用 `*`。带 Authorization 的请求
   在 `*` 下会被浏览器直接拒绝，这个坑在联调时非常难发现。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import api_router
from app.core.cache import cache
from app.core.config import settings
from app.core.errors import (
    CODE_BAD_REQUEST,
    CODE_INTERNAL_SERVER,
    CODE_INVALID_PARAMS,
    CODE_NOT_FOUND,
    BizError,
)
from app.core.logging import setup_logging
from app.core.response import envelope
from app.db.session import create_all, dispose
from app.middleware import AuditMiddleware, RequestLogMiddleware

setup_logging()
logger = logging.getLogger("blog.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("服务启动中，数据库=%s", "SQLite" if settings.is_sqlite else "MySQL")
    await create_all()
    await cache.connect()

    if settings.seed_data:
        from app.db.seed import seed_if_empty

        inserted = await seed_if_empty()
        if inserted:
            logger.info("已灌入初始数据（仅首次启动）")

    scheduler = None
    try:
        from app.scheduler import start_scheduler

        scheduler = start_scheduler()
    except Exception as exc:  # noqa: BLE001 - 定时任务起不来不该阻止服务
        logger.warning("定时任务启动失败: %s", exc)

    logger.info("服务已就绪，监听 :%s", settings.server_port)
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await cache.close()
        await dispose()
        logger.info("服务已关闭")


app = FastAPI(
    title="Gin Blog → FastAPI",
    description="用 FastAPI 重写的博客后端，接口契约与 Go/Gin 版逐字段兼容",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Visitor-ID"],
    max_age=86400,
)
app.add_middleware(AuditMiddleware)
app.add_middleware(RequestLogMiddleware)


# ------------------------------------------------------------ 异常处理


@app.exception_handler(BizError)
async def handle_biz_error(request: Request, exc: BizError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=envelope(exc.code, exc.message))


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """把 pydantic 的校验错误折成统一信封。

    与 Go 版一样只回「参数错误」，不把内部字段路径暴露给前端；
    详细原因写日志，排查时看得到。
    """
    logger.warning("参数校验失败 %s %s: %s", request.method, request.url.path, exc.errors()[:3])
    return JSONResponse(status_code=400, content=envelope(CODE_INVALID_PARAMS, "参数错误"))


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = CODE_NOT_FOUND if exc.status_code == 404 else CODE_BAD_REQUEST
    if exc.status_code >= 500:
        code = CODE_INTERNAL_SERVER
    message = {404: "资源不存在", 405: "请求方法不允许"}.get(exc.status_code, str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content=envelope(code, message))


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500, content=envelope(CODE_INTERNAL_SERVER, "服务器内部错误")
    )


# ---------------------------------------------------------------- 路由


@app.get("/api/v1/health", tags=["health"])
async def health() -> dict:
    return {
        "code": 0,
        "message": "success",
        "data": {"status": "ok", "database": "sqlite" if settings.is_sqlite else "mysql"},
    }


app.include_router(api_router)

# 上传文件静态服务，与 Go 版 `r.engine.Static("/uploads", ...)` 对应
settings.upload_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(settings.upload_path)), name="uploads")


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.server_port,
        reload=False,
        log_config=None,
    )


if __name__ == "__main__":
    run()
