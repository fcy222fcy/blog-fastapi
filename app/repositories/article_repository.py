r"""文章数据访问。

对齐 Go 版 repository/article_repository.go 的查询语义：

- 前台列表：`is_top DESC, created_at DESC`，可按分类/标签/标题关键词过滤
- 后台列表：`created_at DESC`，可按状态/分类/标题过滤
- 搜索：标题/正文/摘要/分类名/标签名任一命中，按 relevance_score 降序
  （标题 10 > 摘要 5 > 标签名 3 > 其他 1），再按置顶与时间排序
- LIKE 里的 `%` `_` `\` 必须转义，否则用户输入 `%` 会退化成全表匹配
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import case, delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.models.article import Article, STATUS_PUBLISHED, STATUS_SCHEDULED
from app.models.comment import Comment, CommentLikeLog
from app.models.taxonomy import ArticleTag, Category, Tag

_ESCAPE = "\\"


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like(column: Any, keyword: str) -> Any:
    return column.like(f"%{escape_like(keyword)}%", escape=_ESCAPE)


async def find_by_id(session: AsyncSession, article_id: int) -> Article | None:
    result = await session.execute(select(Article).where(Article.id == article_id))
    return result.scalar_one_or_none()


async def find_by_slug(session: AsyncSession, slug: str) -> Article | None:
    """前台详情只认已发布文章——草稿和定时稿即使知道 slug 也看不到。"""
    result = await session.execute(
        select(Article).where(Article.slug == slug, Article.status == STATUS_PUBLISHED)
    )
    return result.scalar_one_or_none()


async def find_by_slug_any_status(session: AsyncSession, slug: str) -> Article | None:
    result = await session.execute(select(Article).where(Article.slug == slug))
    return result.scalar_one_or_none()


async def find_by_ids(session: AsyncSession, ids: Sequence[int]) -> list[Article]:
    if not ids:
        return []
    result = await session.execute(select(Article).where(Article.id.in_(ids)))
    return list(result.scalars().all())


async def create(session: AsyncSession, article: Article) -> Article:
    session.add(article)
    await session.flush()
    return article


async def save(session: AsyncSession, article: Article) -> Article:
    """更新标量字段。关联（category/tags）由 save_tags 单独处理。

    这里刻意用 `session.merge` 之外的方式：文章对象本身已经在会话里，
    直接 flush 即可；标签关联在 service 层用 delete+insert 重建，避免
    ORM 顺手把预加载的 Category 写回去导致 category_id 失效（Go 版踩过的坑）。
    """
    await session.flush()
    return article


async def list_published(
    session: AsyncSession,
    offset: int,
    limit: int,
    category_id: int = 0,
    tag_id: int = 0,
    keyword: str = "",
) -> tuple[list[Article], int]:
    conditions = [Article.status == STATUS_PUBLISHED]
    if category_id:
        conditions.append(Article.category_id == category_id)
    if keyword:
        conditions.append(_like(Article.title, keyword))

    stmt = select(Article).where(*conditions)
    if tag_id:
        stmt = stmt.join(ArticleTag, ArticleTag.article_id == Article.id).where(ArticleTag.tag_id == tag_id)

    count_stmt = select(func.count(func.distinct(Article.id))).where(*conditions)
    if tag_id:
        count_stmt = count_stmt.join(ArticleTag, ArticleTag.article_id == Article.id).where(
            ArticleTag.tag_id == tag_id
        )

    total = int((await session.execute(count_stmt)).scalar() or 0)
    stmt = stmt.order_by(Article.is_top.desc(), Article.created_at.desc()).offset(offset).limit(limit)
    rows = list((await session.execute(stmt)).scalars().unique().all())
    return rows, total


async def list_all(
    session: AsyncSession,
    offset: int,
    limit: int,
    status: str = "",
    keyword: str = "",
    category_id: int = 0,
) -> tuple[list[Article], int]:
    conditions: list[Any] = []
    if status:
        conditions.append(Article.status == status)
    if keyword:
        conditions.append(_like(Article.title, keyword))
    if category_id:
        conditions.append(Article.category_id == category_id)

    count_stmt = select(func.count(Article.id)).where(*conditions)
    total = int((await session.execute(count_stmt)).scalar() or 0)

    stmt = (
        select(Article)
        .where(*conditions)
        # 对齐 Go 的 Preload("Category").Preload("Tags")：后台列表项要带出
        # 分类名与标签，异步会话下必须显式预加载，否则触发懒加载报错
        .options(
            selectinload(Article.category),
            selectinload(Article.tags),
            # 对齐 Go 的 Omit("Content")：列表不读 longtext 正文，序列化时置空
            defer(Article.content),
        )
        .order_by(Article.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().unique().all())
    return rows, total


async def get_archives(session: AsyncSession) -> list[Article]:
    """归档只取 id/title/slug/created_at，不读 longtext 正文。"""
    stmt = (
        select(Article.id, Article.title, Article.slug, Article.created_at)
        .where(Article.status == STATUS_PUBLISHED)
        .order_by(Article.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        Article(id=row[0], title=row[1], slug=row[2], created_at=row[3], updated_at=row[3])
        for row in rows
    ]


async def get_recent(session: AsyncSession, limit: int) -> list[Article]:
    stmt = (
        select(Article)
        .where(Article.status == STATUS_PUBLISHED)
        .order_by(Article.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().unique().all())


async def search(session: AsyncSession, keyword: str, offset: int, limit: int) -> tuple[list[Article], int]:
    """多字段模糊搜索 + 相关性排序。

    用 text() 拼 SQL 是因为 relevance 的 CASE WHEN 需要复用同一批 LIKE 条件，
    在 ORM 表达式里重复构造可读性很差且容易漏参数。所有用户输入都走绑定参数，
    LIKE 通配符已转义。
    """
    words = [w for w in keyword.split() if w]
    if not words:
        return [], 0

    likes = [f"%{escape_like(w)}%" for w in words]

    # ESCAPE 子句的写法按方言区分：
    #   MySQL  字符串字面量里反斜杠本身是转义符，要写 '\\' 才表示一个反斜杠
    #   SQLite 没有这层转义，直接写 '\'
    # 写错的表现是 SQLite 报 "ESCAPE expression must be a single character"。
    dialect = session.bind.dialect.name if session.bind else "sqlite"
    escape_sql = "ESCAPE '\\\\'" if dialect == "mysql" else "ESCAPE '\\'"

    def _or_cond(template: str) -> str:
        return "(" + " OR ".join(template.format(idx=i) for i in range(len(words))) + ")"

    title_cond = _or_cond(f"a.title LIKE :kw{{idx}} {escape_sql}")
    content_cond = _or_cond(f"a.content LIKE :kw{{idx}} {escape_sql}")
    summary_cond = _or_cond(f"a.summary LIKE :kw{{idx}} {escape_sql}")
    category_cond = _or_cond(f"c.name LIKE :kw{{idx}} {escape_sql}")
    tag_cond = _or_cond(f"t.name LIKE :kw{{idx}} {escape_sql}")

    params: dict[str, Any] = {f"kw{i}": v for i, v in enumerate(likes)}
    params["published"] = STATUS_PUBLISHED
    params["offset"] = offset
    params["limit"] = limit

    where_sql = f"({title_cond} OR {content_cond} OR {summary_cond} OR {category_cond} OR {tag_cond})"
    relevance_sql = (
        f"CASE WHEN {title_cond} THEN 10 "
        f"WHEN {summary_cond} THEN 5 "
        f"WHEN {tag_cond} THEN 3 ELSE 1 END"
    )

    base_from = (
        "FROM articles a "
        "LEFT JOIN categories c ON c.id = a.category_id "
        "LEFT JOIN article_tags at2 ON at2.article_id = a.id "
        "LEFT JOIN tags t ON t.id = at2.tag_id "
        f"WHERE a.status = :published AND {where_sql}"
    )

    count_sql = text(f"SELECT COUNT(DISTINCT a.id) {base_from}")
    total = int((await session.execute(count_sql, params)).scalar() or 0)

    id_sql = text(
        f"SELECT a.id, {relevance_sql} AS relevance_score {base_from} "
        "GROUP BY a.id "
        "ORDER BY relevance_score DESC, a.is_top DESC, a.created_at DESC "
        "LIMIT :limit OFFSET :offset"
    )
    ordered_ids = [row[0] for row in (await session.execute(id_sql, params)).all()]
    if not ordered_ids:
        return [], total

    stmt = select(Article).where(Article.id.in_(ordered_ids))
    rows = list((await session.execute(stmt)).scalars().unique().all())
    by_id = {row.id: row for row in rows}
    return [by_id[i] for i in ordered_ids if i in by_id], total


async def count(session: AsyncSession, status: str = "") -> int:
    stmt = select(func.count(Article.id))
    if status:
        stmt = stmt.where(Article.status == status)
    return int((await session.execute(stmt)).scalar() or 0)


async def sum_view_count(session: AsyncSession) -> int:
    stmt = select(func.coalesce(func.sum(Article.view_count), 0))
    return int((await session.execute(stmt)).scalar() or 0)


async def increment_view_count(session: AsyncSession, article_id: int) -> None:
    await session.execute(
        update(Article)
        .where(Article.id == article_id)
        .values(view_count=Article.view_count + 1)
    )


async def update_comment_count(session: AsyncSession, article_id: int, delta: int) -> None:
    """评论数增减带下限保护，避免并发删除把计数打成负数。"""
    if delta == 0:
        return
    if delta > 0:
        await session.execute(
            update(Article)
            .where(Article.id == article_id)
            .values(comment_count=Article.comment_count + delta)
        )
        return

    amount = -delta
    await session.execute(
        update(Article)
        .where(Article.id == article_id)
        .values(
            comment_count=case(
                (Article.comment_count >= amount, Article.comment_count - amount),
                else_=Article.comment_count,
            )
        )
    )


async def replace_tags(session: AsyncSession, article_id: int, tag_ids: Sequence[int]) -> None:
    """重建文章-标签关联（先清后插），等价 GORM 的 Association.Replace。"""
    await session.execute(delete(ArticleTag).where(ArticleTag.article_id == article_id))
    for tag_id in dict.fromkeys(tag_ids):
        session.add(ArticleTag(article_id=article_id, tag_id=tag_id))
    await session.flush()


async def delete_article(session: AsyncSession, article_id: int) -> None:
    """硬删除并级联清理评论、评论点赞、标签关联（与 Go 版同事务语义）。"""
    comment_ids = list(
        (
            await session.execute(select(Comment.id).where(Comment.article_id == article_id))
        ).scalars()
    )
    if comment_ids:
        await session.execute(delete(CommentLikeLog).where(CommentLikeLog.comment_id.in_(comment_ids)))
    await session.execute(delete(Comment).where(Comment.article_id == article_id))
    await session.execute(delete(ArticleTag).where(ArticleTag.article_id == article_id))
    await session.execute(delete(Article).where(Article.id == article_id))


async def batch_delete(session: AsyncSession, ids: Sequence[int]) -> None:
    if not ids:
        return
    comment_ids = list(
        (await session.execute(select(Comment.id).where(Comment.article_id.in_(ids)))).scalars()
    )
    if comment_ids:
        await session.execute(delete(CommentLikeLog).where(CommentLikeLog.comment_id.in_(comment_ids)))
    await session.execute(delete(Comment).where(Comment.article_id.in_(ids)))
    await session.execute(delete(ArticleTag).where(ArticleTag.article_id.in_(ids)))
    await session.execute(delete(Article).where(Article.id.in_(ids)))


async def publish_due_scheduled(session: AsyncSession, now: datetime) -> list[Article]:
    """把到期的定时文章切为已发布，返回被切换的文章（用于缓存失效）。"""
    stmt = select(Article).where(
        Article.status == STATUS_SCHEDULED, Article.scheduled_at.is_not(None), Article.scheduled_at <= now
    )
    due = list((await session.execute(stmt)).scalars().all())
    for article in due:
        article.status = STATUS_PUBLISHED
        article.scheduled_at = None
    if due:
        await session.flush()
    return due
