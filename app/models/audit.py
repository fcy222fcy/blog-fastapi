"""审计日志、媒体文件、访问日志、内容浏览事件。

`content_view_events` 是浏览量去重的核心表：`(content_type, content_id,
visitor_key, view_date)` 四列联合唯一，插入冲突即代表「今天已经算过一次」，
不需要先查后写，也就不会有并发下的重复计数。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK, TimestampMixin

CONTENT_TYPE_ARTICLE = "article"
CONTENT_TYPE_DAILY_QUESTION = "daily_question"
SUPPORTED_CONTENT_TYPES = (CONTENT_TYPE_ARTICLE, CONTENT_TYPE_DAILY_QUESTION)

_UInt = BigInteger().with_variant(Integer, "sqlite")


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_operator_id", "operator_id"),
        Index("idx_audit_logs_action", "action"),
        Index("idx_audit_logs_target_type", "target_type"),
        Index("idx_audit_logs_target_id", "target_id"),
    )

    operator_id: Mapped[int] = mapped_column(_UInt, default=0)
    operator_name: Mapped[str | None] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[int] = mapped_column(_UInt, default=0)
    target_title: Mapped[str | None] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(String(500))


class Media(TimestampMixin, Base):
    __tablename__ = "media"

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    type: Mapped[str | None] = mapped_column(String(20))


class VisitLog(Base):
    __tablename__ = "visit_logs"
    __table_args__ = (Index("idx_visit_logs_article_id", "article_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(_UInt, default=0)
    ip: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    referer: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class ContentViewEvent(Base):
    __tablename__ = "content_view_events"
    __table_args__ = (
        Index("idx_content_view", "content_type", "content_id", "visitor_key", "view_date", unique=True),
        Index("idx_content_view_date", "content_type", "view_date"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content_id: Mapped[int] = mapped_column(_UInt, nullable=False)
    visitor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    view_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
