"""SQLAlchemy 声明基类与通用列类型。

表结构必须与 Go/GORM 产出的库**完全兼容**（同一套库能被两个实现同时读写），
所以列名、类型、索引名都按 GORM 的默认约定来：

- 主键 `id`，无符号自增 BIGINT
- `created_at` / `updated_at` DATETIME
- 布尔用 TINYINT(1)，因为 GORM 的 `bool` 在 MySQL 上落成 tinyint(1)

SQLite 分支用 `with_variant` 降级：BIGINT 换成 INTEGER（SQLite 只有
`INTEGER PRIMARY KEY` 才自增），长文本用 TEXT。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 显式命名约定，保证 create_all 生成的索引名与 GORM 的命名风格一致，
# 迁移已有库时不会因为索引重名冲突而失败。
NAMING_CONVENTION = {
    "ix": "idx_%(column_0_label)s",
    "uq": "uk_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """统一取本地时区 naive 时间。

    GORM 写入的是本地时间（DSN 里 loc=Local），为了让两个实现看到同一套时间，
    这里也用本地时间而不是 UTC。
    """
    return datetime.now()


BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """对应 Go 版 entity.BaseEntity。"""

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


__all__ = ["Base", "BigIntPK", "TimestampMixin", "utcnow", "timezone"]
