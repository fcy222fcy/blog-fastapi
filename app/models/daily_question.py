"""每日一问与点赞记录。

`status` 是三态整数（0 禁用 / 1 已发布 / 2 定时），`date` 唯一。
对外查询一律附加 `date <= 今天`，未来排期不会提前泄露。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK, TimestampMixin

STATUS_DISABLED = 0
STATUS_PUBLISHED = 1
STATUS_SCHEDULED = 2
VALID_STATUSES = (STATUS_DISABLED, STATUS_PUBLISHED, STATUS_SCHEDULED)

# GORM 里这三列是 int64，对应 MySQL BIGINT
CounterType = BigInteger().with_variant(Integer, "sqlite")


class DailyQuestion(TimestampMixin, Base):
    __tablename__ = "daily_questions"
    __table_args__ = (Index("idx_daily_questions_date", "date", unique=True),)

    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    like_count: Mapped[int] = mapped_column(CounterType, default=0)
    comment_count: Mapped[int] = mapped_column(CounterType, default=0)
    view_count: Mapped[int] = mapped_column(CounterType, default=0)
    status: Mapped[int] = mapped_column(Integer, default=STATUS_PUBLISHED, server_default="1")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DailyQuestion id={self.id} date={self.date}>"


class DailyQuestionLikeLog(Base):
    __tablename__ = "daily_question_like_logs"
    __table_args__ = (Index("idx_question_ip", "question_id", "visitor_ip", unique=True),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    visitor_ip: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
