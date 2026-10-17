"""评论与点赞记录。

评论表同时容纳三种身份：游客（内联 nickname/email/avatar）、登录用户（user_id）、
博主（user_id == 配置里的 blogger_user_id）。`parent_id` 决定楼层，`reply_to_id`
决定「回复 @某人」的指向——两者可以不同，楼中楼就是靠这个区分出来的。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigIntPK, TimestampMixin

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
VALID_STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"
    __table_args__ = (
        Index("idx_comments_article_id", "article_id"),
        Index("idx_comments_user_id", "user_id"),
        Index("idx_comments_parent_id", "parent_id"),
        Index("idx_comments_reply_to_id", "reply_to_id"),
        Index("idx_comments_status", "status"),
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)

    user_id: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(200))
    avatar: Mapped[str | None] = mapped_column(String(500))

    article_id: Mapped[int] = mapped_column(BigIntPK, default=0)
    parent_id: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)
    reply_to_id: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)

    like_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING, server_default="pending")
    ip: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(String(500))

    os: Mapped[str | None] = mapped_column(String(50))
    os_version: Mapped[str | None] = mapped_column(String(50))
    browser: Mapped[str | None] = mapped_column(String(50))
    browser_version: Mapped[str | None] = mapped_column(String(50))

    article: Mapped["Article"] = relationship(  # noqa: F821
        "Article",
        lazy="selectin",
        viewonly=True,
        primaryjoin="Comment.article_id == Article.id",
        foreign_keys="Comment.article_id",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Comment id={self.id} article={self.article_id} parent={self.parent_id}>"


class CommentLikeLog(Base):
    """评论点赞去重表。`(comment_id, visitor_ip)` 唯一，重复点赞靠唯一约束兜底。"""

    __tablename__ = "comment_like_logs"
    __table_args__ = (Index("idx_comment_ip", "comment_id", "visitor_ip", unique=True),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    comment_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    visitor_ip: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
