"""文章实体。

对应 GORM `articles` 表。`status` 三态（draft/published/scheduled）与 Go 版常量一致。
`tags` 多对多走 `article_tags` 中间表，中间表没有额外列、也没有联合主键以外的约束。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigIntPK, TimestampMixin

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_SCHEDULED = "scheduled"
VALID_STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED, STATUS_SCHEDULED)

LongText = Text().with_variant(LONGTEXT(), "mysql")


class Article(TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        Index("idx_articles_slug", "slug", unique=True),
        Index("idx_articles_status", "status"),
        Index("idx_articles_category_id", "category_id"),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str | None] = mapped_column(LongText)
    summary: Mapped[str | None] = mapped_column(Text)
    cover: Mapped[str | None] = mapped_column(String(500))
    category_id: Mapped[int] = mapped_column(BigIntPK, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PUBLISHED, server_default=text("'published'"))
    is_top: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    reading_time: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seo_title: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))
    seo_description: Mapped[str] = mapped_column(String(500), default="", server_default=text("''"))
    seo_keywords: Mapped[str] = mapped_column(String(300), default="", server_default=text("''"))

    category: Mapped["Category"] = relationship(  # noqa: F821
        "Category",
        lazy="selectin",
        primaryjoin="Article.category_id == Category.id",
        foreign_keys="Article.category_id",
    )
    # 中间表故意不带外键约束（GORM 也不建），所以必须显式写出 join 条件
    tags: Mapped[list["Tag"]] = relationship(  # noqa: F821
        "Tag",
        secondary="article_tags",
        primaryjoin="Article.id == article_tags.c.article_id",
        secondaryjoin="Tag.id == article_tags.c.tag_id",
        lazy="selectin",
        order_by="Tag.id",
    )

    @property
    def tag_ids(self) -> list[int]:
        return [t.id for t in self.tags]

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Article id={self.id} slug={self.slug!r}>"
