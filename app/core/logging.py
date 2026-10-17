"""日志配置。

对标 Go 版 Zap：控制台彩色 + 文件按大小轮转，格式包含时间/级别/logger/消息。
Python 侧不需要复刻 Zap 的字段化能力，但保留同样的 logger 命名习惯
（`blog.service`、`blog.api` …），便于两边日志放在一起看。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from app.core.config import BASE_DIR, settings

_CONFIGURED = False

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

_CONSOLE_FORMAT = "%(asctime)s %(levelname)-5s %(name)-22s %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-5s %(name)-22s [%(filename)s:%(lineno)d] %(message)s"


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = _LEVELS.get((settings.log_level or "info").lower(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(console)

    if settings.log_filename:
        log_path = Path(settings.log_filename)
        if not log_path.is_absolute():
            log_path = BASE_DIR / log_path
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=100 * 1024 * 1024,
                backupCount=7,
                encoding="utf-8",
            )
            file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
            root.addHandler(file_handler)
        except OSError as exc:
            root.warning("日志文件不可写，已退化为仅控制台输出: %s", exc)

    # 第三方库降噪
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING if not settings.db_echo else logging.INFO)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"blog.{name}")
