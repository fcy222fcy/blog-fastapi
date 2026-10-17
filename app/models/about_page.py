"""关于页面。

Go 版把技能/项目/联系方式等结构体以 **JSON 字符串** 存进 TEXT 列，
不建子表。这里保持一致——存字符串，读取时原样返回，排序逻辑单独实现。
"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AboutPage(TimestampMixin, Base):
    __tablename__ = "about_pages"

    title: Mapped[str | None] = mapped_column(String(200))
    subtitle: Mapped[str | None] = mapped_column(String(500))
    bio: Mapped[str | None] = mapped_column(Text)
    skills: Mapped[str | None] = mapped_column(Text)
    about_me: Mapped[str | None] = mapped_column(Text)
    about_site: Mapped[str | None] = mapped_column(Text)
    projects: Mapped[str | None] = mapped_column(Text)
    contact_info: Mapped[str | None] = mapped_column(Text)
    site_history: Mapped[str | None] = mapped_column(Text)
