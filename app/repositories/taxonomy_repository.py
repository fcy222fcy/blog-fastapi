"""分类与标签数据访问。

两者的结构几乎一样，区别只在「文章数」的统计口径：
分类靠 `articles.category_id`，标签靠 `article_tags` 中间表。
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.taxonomy import ArticleTag, Category, Tag


# ------------------------------------------------------------------- category


async def list_categories(session: AsyncSession) -> list[Category]:
    result = await session.execute(select(Category).order_by(Category.sort_order.asc(), Category.id.asc()))
    return list(result.scalars().all())


async def find_category_by_id(session: AsyncSession, category_id: int) -> Category | None:
    result = await session.execute(select(Category).where(Category.id == category_id))
    return result.scalar_one_or_none()


async def find_category_by_name(session: AsyncSession, name: str) -> Category | None:
    result = await session.execute(select(Category).where(Category.name == name))
    return result.scalar_one_or_none()


async def find_category_by_slug(session: AsyncSession, slug: str) -> Category | None:
    result = await session.execute(select(Category).where(Category.slug == slug))
    return result.scalar_one_or_none()


async def count_articles_in_category(session: AsyncSession, category_id: int) -> int:
    stmt = select(func.count(Article.id)).where(Article.category_id == category_id)
    return int((await session.execute(stmt)).scalar() or 0)


async def create_category(session: AsyncSession, category: Category) -> Category:
    session.add(category)
    await session.flush()
    return category


async def delete_category(session: AsyncSession, category_id: int) -> None:
    await session.execute(delete(Category).where(Category.id == category_id))


# ------------------------------------------------------------------------ tag


async def list_tags(session: AsyncSession) -> list[Tag]:
    result = await session.execute(select(Tag).order_by(Tag.id.asc()))
    return list(result.scalars().all())


async def find_tag_by_id(session: AsyncSession, tag_id: int) -> Tag | None:
    result = await session.execute(select(Tag).where(Tag.id == tag_id))
    return result.scalar_one_or_none()


async def find_tag_by_name(session: AsyncSession, name: str) -> Tag | None:
    result = await session.execute(select(Tag).where(Tag.name == name))
    return result.scalar_one_or_none()


async def find_tag_by_slug(session: AsyncSession, slug: str) -> Tag | None:
    result = await session.execute(select(Tag).where(Tag.slug == slug))
    return result.scalar_one_or_none()


async def find_tags_by_ids(session: AsyncSession, ids: list[int]) -> list[Tag]:
    if not ids:
        return []
    result = await session.execute(select(Tag).where(Tag.id.in_(ids)).order_by(Tag.id.asc()))
    return list(result.scalars().all())


async def count_articles_with_tag(session: AsyncSession, tag_id: int) -> int:
    stmt = select(func.count(ArticleTag.article_id)).where(ArticleTag.tag_id == tag_id)
    return int((await session.execute(stmt)).scalar() or 0)


async def create_tag(session: AsyncSession, tag: Tag) -> Tag:
    session.add(tag)
    await session.flush()
    return tag


async def delete_tag(session: AsyncSession, tag_id: int) -> None:
    await session.execute(delete(ArticleTag).where(ArticleTag.tag_id == tag_id))
    await session.execute(delete(Tag).where(Tag.id == tag_id))
