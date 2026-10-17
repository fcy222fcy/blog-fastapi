"""分类、标签与文章-标签关联。"""

from __future__ import annotations

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK, TimestampMixin


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        Index("idx_categories_name", "name", unique=True),
        Index("idx_categories_slug", "slug", unique=True),
    )

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    icon: Mapped[str | None] = mapped_column(String(10))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Category id={self.id} name={self.name!r}>"


class Tag(TimestampMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (
        Index("idx_tags_name", "name", unique=True),
        Index("idx_tags_slug", "slug", unique=True),
    )

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tag id={self.id} name={self.name!r}>"


class ArticleTag(Base):
    """文章-标签中间表。GORM 默认建 `article_id`/`tag_id` 两列复合主键。"""

    __tablename__ = "article_tags"

    article_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    tag_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
