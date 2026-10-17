"""评论数据访问。

最复杂的一块是「根评论分页 + 楼中楼回复树」：

1. 先只统计根评论（`parent_id IS NULL`）作为分页基数——
   如果把回复也算进总数，翻页会出现「一页只有半条楼」的怪异现象。
2. 取全量根评论在内存里排序。为什么不在 SQL 里排？因为 `hot` 排序依赖
   「所有层级回复数」，SQL 里要递归 CTE，MySQL 5.7 又不支持。
3. 切片分页后，只为当前页的根评论重建回复树——回复属于根，跟着根走。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, CODE_COMMENT_ALREADY_LIKED, CODE_COMMENT_NOT_LIKED
from app.models.article import Article
from app.models.comment import Comment, CommentLikeLog, STATUS_APPROVED
from app.repositories.article_repository import escape_like

SORT_ASC = "asc"
SORT_DESC = "desc"
SORT_HOT = "hot"


async def find_by_id(session: AsyncSession, comment_id: int) -> Comment | None:
    result = await session.execute(select(Comment).where(Comment.id == comment_id))
    return result.scalar_one_or_none()


async def find_many(session: AsyncSession, ids: Sequence[int]) -> list[Comment]:
    if not ids:
        return []
    result = await session.execute(select(Comment).where(Comment.id.in_(ids)))
    return list(result.scalars().all())


async def create(session: AsyncSession, comment: Comment) -> Comment:
    session.add(comment)
    await session.flush()
    return comment


async def save(session: AsyncSession, comment: Comment) -> None:
    await session.flush()


async def count(session: AsyncSession, status: str = "") -> int:
    stmt = select(func.count(Comment.id))
    if status:
        stmt = stmt.where(Comment.status == status)
    return int((await session.execute(stmt)).scalar() or 0)


def _hot_score(comment: Comment, replies_map: dict[int, list[Comment]]) -> int:
    """热度 = 点赞数 × 2 + 所有层级回复数。与 Go 版 calcHotScore 一致。"""
    total = 0
    stack = list(replies_map.get(comment.id, []))
    while stack:
        node = stack.pop()
        total += 1
        stack.extend(replies_map.get(node.id, []))
    return comment.like_count * 2 + total


def _group_replies(all_comments: Sequence[Comment], root_ids: set[int]) -> dict[int, list[Comment]]:
    """按 parent_id 分组，只保留「祖先根在当前页」的回复。

    历史数据里可能出现 parent 已被删除的孤儿回复，这种情况直接丢弃，
    否则前端会渲染出没有归属的幽灵楼层。
    """
    by_id = {c.id: c for c in all_comments}
    grouped: dict[int, list[Comment]] = {}

    for comment in all_comments:
        if comment.parent_id is None:
            continue
        parent = by_id.get(comment.parent_id)
        if parent is None:
            continue
        if parent.id in root_ids:
            root_id = parent.id
        else:
            ancestor = parent
            guard = 0
            while ancestor.parent_id is not None and guard < 64:
                nxt = by_id.get(ancestor.parent_id)
                if nxt is None:
                    break
                ancestor = nxt
                guard += 1
            if ancestor.id not in root_ids:
                continue
            root_id = ancestor.id
        grouped.setdefault(root_id, []).append(comment)

    return grouped


async def list_by_article(
    session: AsyncSession, article_id: int, offset: int, limit: int, sort_by: str = SORT_DESC
) -> tuple[list[Comment], int, dict[int, list[Comment]]]:
    """返回 (当前页根评论, 根评论总数, 根ID → 回复列表)。"""
    root_where = (
        Comment.article_id == article_id,
        Comment.status == STATUS_APPROVED,
        Comment.parent_id.is_(None),
    )

    total = int((await session.execute(select(func.count(Comment.id)).where(*root_where))).scalar() or 0)

    roots = list(
        (
            await session.execute(select(Comment).where(*root_where).order_by(Comment.created_at.desc()))
        ).scalars()
    )
    all_comments = list(
        (
            await session.execute(
                select(Comment)
                .where(Comment.article_id == article_id, Comment.status == STATUS_APPROVED)
                .order_by(Comment.created_at.asc())
            )
        ).scalars()
    )

    # 用全量根评论算热度，保证 hot 排序在全量范围内正确
    all_root_ids = {c.id for c in roots}
    full_grouped = _group_replies(all_comments, all_root_ids)

    if sort_by == SORT_ASC:
        roots.sort(key=lambda c: c.created_at)
    elif sort_by == SORT_HOT:
        roots.sort(key=lambda c: (-_hot_score(c, full_grouped), -c.created_at.timestamp()))
    else:
        roots.sort(key=lambda c: c.created_at, reverse=True)

    start = min(offset, total)
    end = min(offset + limit, total)
    paged = roots[start:end]

    paged_ids = {c.id for c in paged}
    replies = _group_replies(all_comments, paged_ids)

    # 回复内部按时间升序（楼层内按对话顺序读才自然）
    for items in replies.values():
        items.sort(key=lambda c: c.created_at)

    return paged, total, replies


async def admin_list(
    session: AsyncSession, offset: int, limit: int, status: str = "", keyword: str = ""
) -> tuple[list[Comment], int]:
    conditions: list[Any] = []
    if status:
        conditions.append(Comment.status == status)

    stmt = select(Comment)
    count_stmt = select(func.count(func.distinct(Comment.id)))

    if keyword:
        pattern = f"%{escape_like(keyword)}%"
        stmt = stmt.outerjoin(Article, Article.id == Comment.article_id)
        count_stmt = count_stmt.outerjoin(Article, Article.id == Comment.article_id)
        like_cond = or_(
            Comment.nickname.like(pattern, escape="\\"),
            Comment.email.like(pattern, escape="\\"),
            Comment.content.like(pattern, escape="\\"),
            Article.title.like(pattern, escape="\\"),
        )
        conditions.append(like_cond)

    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

    total = int((await session.execute(count_stmt)).scalar() or 0)
    rows = list(
        (await session.execute(stmt.order_by(Comment.created_at.desc()).offset(offset).limit(limit))).scalars().unique()
    )
    return rows, total


async def reply_to_nicknames(session: AsyncSession, comments: Sequence[Comment]) -> dict[int, str]:
    """批量取「被回复人昵称」，一次查询解决，避免 N+1。"""
    ids = {c.reply_to_id or c.parent_id for c in comments if (c.reply_to_id or c.parent_id)}
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (
        await session.execute(select(Comment.id, Comment.nickname).where(Comment.id.in_(ids)))
    ).all()
    return {row[0]: (row[1] or "") for row in rows}


async def delete_comment(session: AsyncSession, comment_id: int) -> None:
    """硬删除，递归清理子评论与点赞记录。"""
    all_ids = [comment_id]
    current = [comment_id]
    guard = 0
    while current and guard < 64:
        children = list(
            (await session.execute(select(Comment.id).where(Comment.parent_id.in_(current)))).scalars()
        )
        if not children:
            break
        all_ids.extend(children)
        current = children
        guard += 1

    await session.execute(delete(CommentLikeLog).where(CommentLikeLog.comment_id.in_(all_ids)))
    await session.execute(delete(Comment).where(Comment.id.in_(all_ids)))


async def batch_delete(session: AsyncSession, ids: Sequence[int]) -> None:
    if not ids:
        return
    all_ids = list(ids)
    current = list(ids)
    guard = 0
    while current and guard < 64:
        children = list(
            (await session.execute(select(Comment.id).where(Comment.parent_id.in_(current)))).scalars()
        )
        if not children:
            break
        all_ids.extend(children)
        current = children
        guard += 1

    await session.execute(delete(CommentLikeLog).where(CommentLikeLog.comment_id.in_(all_ids)))
    await session.execute(delete(Comment).where(Comment.id.in_(all_ids)))


async def count_by_article(session: AsyncSession, article_id: int) -> int:
    stmt = select(func.count(Comment.id)).where(
        Comment.article_id == article_id, Comment.status == STATUS_APPROVED
    )
    return int((await session.execute(stmt)).scalar() or 0)


def _insert_ignore(session: AsyncSession, comment_id: int, visitor_ip: str) -> Any:
    """构造「冲突即忽略」的插入语句。MySQL 与 SQLite 语法不同，按方言分派。"""
    dialect = session.bind.dialect.name if session.bind else "sqlite"
    values = {"comment_id": comment_id, "visitor_ip": visitor_ip, "created_at": datetime.now()}
    if dialect == "mysql":
        return mysql_insert(CommentLikeLog).values(**values).prefix_with("IGNORE")
    return sqlite_insert(CommentLikeLog).values(**values).on_conflict_do_nothing(
        index_elements=["comment_id", "visitor_ip"]
    )


async def like_with_log(session: AsyncSession, comment_id: int, visitor_ip: str) -> None:
    """点赞：先插日志（唯一约束保证并发安全），再 +1。

    插入被忽略说明今天已经点过——直接抛业务错误，不重复计数。
    """
    result = await session.execute(_insert_ignore(session, comment_id, visitor_ip))
    if not result.rowcount:
        raise BizError(CODE_COMMENT_ALREADY_LIKED)
    await session.execute(
        update(Comment).where(Comment.id == comment_id).values(like_count=Comment.like_count + 1)
    )


async def unlike_with_log(session: AsyncSession, comment_id: int, visitor_ip: str) -> None:
    result = await session.execute(
        delete(CommentLikeLog).where(
            CommentLikeLog.comment_id == comment_id, CommentLikeLog.visitor_ip == visitor_ip
        )
    )
    if not result.rowcount:
        raise BizError(CODE_COMMENT_NOT_LIKED)
    await session.execute(
        update(Comment)
        .where(Comment.id == comment_id, Comment.like_count > 0)
        .values(like_count=Comment.like_count - 1)
    )
