"""应用配置。

复刻 Go 版 pkg/config 的层级与覆写顺序：
1. configs/config.yaml（若存在）
2. .env 文件
3. 真实环境变量（优先级最高）

环境变量名与 Go 版保持完全一致（DB_HOST / JWT_SECRET / BLOGGER_USER_ID ...），
这样原项目的 .env、docker-compose、部署脚本可以原样复用。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _load_dotenv(path: Path) -> None:
    """把 .env 读进 os.environ，但**不覆盖**已存在的真实环境变量。

    与 Go 版 loadDotEnv 的语义一致：环境变量优先于 .env 文件。
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml
    except ImportError:  # yaml 是可选依赖，缺失时退化为纯环境变量模式
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    return value if isinstance(value, dict) else {}


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


_load_dotenv(BASE_DIR / ".env")
_yaml_cfg = _load_yaml(Path(os.environ.get("CONFIG_FILE") or BASE_DIR / "configs" / "config.yaml"))

_server = _section(_yaml_cfg, "server")
_mysql = _section(_yaml_cfg, "mysql")
_redis = _section(_yaml_cfg, "redis")
_jwt = _section(_yaml_cfg, "jwt")
_log = _section(_yaml_cfg, "log")
_email = _section(_yaml_cfg, "email")
_blogger = _section(_yaml_cfg, "blogger")
_app = _section(_yaml_cfg, "app")


class Settings(BaseSettings):
    """全部配置项，字段名与 Go 版 Config 结构一一对应。"""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    # ---- server ----
    server_port: int = Field(default=int(_server.get("port", 9090)), alias="SERVER_PORT")
    # 逗号分隔的字符串，用 property 暴露成 list：
    # pydantic-settings 会把 list 类型的环境变量当 JSON 解析，而 CORS_ORIGINS
    # 的惯例写法是逗号分隔，直接在 source 层就会解析失败。
    cors_origins_raw: str = Field(default="", alias="CORS_ORIGINS")
    trusted_proxies_raw: str = Field(default="", alias="TRUSTED_PROXIES")

    # ---- mysql ----
    db_host: str = Field(default=str(_mysql.get("host", "127.0.0.1")), alias="DB_HOST")
    db_port: int = Field(default=int(_mysql.get("port", 3306)), alias="DB_PORT")
    db_user: str = Field(default=str(_mysql.get("username", "root")), alias="DB_USER")
    db_password: str = Field(default=str(_mysql.get("password", "")), alias="DB_PASSWORD")
    db_name: str = Field(default=str(_mysql.get("dbname", "blog")), alias="DB_NAME")
    # 允许直接用完整 DSN 覆盖（sqlite+aiosqlite:///./data/blog.db 亦可）
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    db_echo: bool = Field(default=False, alias="DB_ECHO")

    # ---- redis（缺省时全链路自动降级为无缓存）----
    redis_host: str = Field(default=str(_redis.get("host", "")), alias="REDIS_HOST")
    redis_port: int = Field(default=int(_redis.get("port", 6379)), alias="REDIS_PORT")
    redis_password: str = Field(default=str(_redis.get("password", "")), alias="REDIS_PASSWORD")
    redis_db: int = Field(default=int(_redis.get("db", 0)), alias="REDIS_DB")
    redis_enabled: bool = Field(default=True, alias="REDIS_ENABLED")

    # ---- jwt ----
    jwt_secret: str = Field(default=str(_jwt.get("secret", "change-me-in-env")), alias="JWT_SECRET")
    jwt_expire_hours: int = Field(default=int(_jwt.get("expire_hour", 168)), alias="JWT_EXPIRE_HOURS")

    # ---- log ----
    log_level: str = Field(default=str(_log.get("level", "info")), alias="LOG_LEVEL")
    log_filename: str = Field(default=str(_log.get("filename", "logs/app.log")), alias="LOG_FILENAME")

    # ---- email ----
    email_host: str = Field(default=str(_email.get("host", "")), alias="EMAIL_HOST")
    email_port: int = Field(default=int(_email.get("port", 465)), alias="EMAIL_PORT")
    email_user: str = Field(default=str(_email.get("username", "")), alias="EMAIL_USER")
    email_password: str = Field(default=str(_email.get("password", "")), alias="EMAIL_PASSWORD")
    email_from: str = Field(default=str(_email.get("from", "博客评论通知")), alias="EMAIL_FROM")
    email_from_email: str = Field(default=str(_email.get("from_email", "")), alias="EMAIL_FROM_EMAIL")

    # ---- blogger（博主身份唯一权威来源，前端不可伪造）----
    blogger_user_id: int = Field(default=int(_blogger.get("user_id", 1)), alias="BLOGGER_USER_ID")
    blogger_username: str = Field(default=str(_blogger.get("username", "admin")), alias="BLOGGER_USERNAME")
    blogger_password: str = Field(default=str(_blogger.get("password", "")), alias="BLOGGER_PASSWORD")
    blogger_nickname: str = Field(default=str(_blogger.get("nickname", "博主")), alias="BLOGGER_NICKNAME")
    blogger_email: str = Field(default=str(_blogger.get("email", "")), alias="BLOGGER_EMAIL")
    blogger_avatar: str = Field(default=str(_blogger.get("avatar", "/avatar.jpg")), alias="BLOGGER_AVATAR")

    # ---- app ----
    upload_dir: str = Field(default=str(_app.get("upload_dir", "uploads")), alias="UPLOAD_DIR")
    seed_data: bool = Field(default=bool(_app.get("seed_data", True)), alias="APP_SEED_DATA")

    # ---- 派生属性 ----
    @property
    def cors_origins(self) -> list[str]:
        return _csv(self.cors_origins_raw) or list(_server.get("cors_origins") or []) or [
            "http://localhost:3000",
            "http://localhost:9090",
            "http://localhost:5173",
            "http://localhost:5174",
        ]

    @property
    def trusted_proxies(self) -> list[str]:
        return _csv(self.trusted_proxies_raw) or list(_server.get("trusted_proxies") or []) or [
            "127.0.0.1",
            "::1",
        ]

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"mysql+aiomysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir)
        return p if p.is_absolute() else (BASE_DIR / p)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
