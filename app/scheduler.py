"""定时任务。

唯一职责：把到期的 `scheduled` 文章切成 `published`。

为什么用轮询而不是「按 scheduled_at 注册一次性任务」？因为进程重启后
内存里的任务会全部丢失，而轮询只依赖数据库里的状态，天然可恢复。
Go 版用 robfig/cron 也是同样的取舍。
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db.session import session_scope
from app.services import article_service

logger = logging.getLogger("blog.scheduler")

_scheduler: AsyncIOScheduler | None = None


async def publish_scheduled_articles() -> None:
    try:
        async with session_scope() as session:
            await article_service.publish_due_articles(session)
    except Exception as exc:  # noqa: BLE001 - 单次失败不终止调度
        logger.error("定时发布任务执行失败: %s", exc)


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        publish_scheduled_articles,
        trigger=IntervalTrigger(seconds=30),
        id="publish_scheduled_articles",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("定时任务已启动：每 30 秒检查一次到期文章")
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
