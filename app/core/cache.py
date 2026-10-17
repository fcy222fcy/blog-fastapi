"""Redis 缓存封装（失败自动降级）。

Go 版的约定是「Redis 不可用时全链路静默降级」，缓存读写失败绝不能影响业务。
这里用同样的策略：任何 Redis 异常都记日志后返回 None / 忽略，并且删除缓存
走 `go` 式异步（`asyncio.create_task`），避免拖慢写接口的响应。

缓存 key 与 TTL 也与 Go 版保持一致，两个实现共用一个 Redis 时不会互相读到脏数据。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger("blog.cache")

# 与 Go 版一致的 TTL（秒）
TTL_ARTICLE_LIST = 5 * 60
TTL_ARTICLE_DETAIL = 10 * 60
TTL_ARCHIVE = 10 * 60
TTL_CATEGORY_LIST = 30 * 60
TTL_TAG_LIST = 30 * 60

KEY_ARTICLE_ARCHIVES = "article:archives"
KEY_CATEGORY_LIST = "category:list"
KEY_TAG_LIST = "tag:list"


def article_list_key(page: int, size: int, category: int, tag: int, keyword: str) -> str:
    return f"article:list:{page}:{size}:{category}:{tag}:{keyword}"


def article_detail_key(slug: str) -> str:
    return f"article:detail:{slug}"


class Cache:
    """异步 Redis 客户端薄封装。未配置或初始化失败时 `enabled` 为 False。"""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def connect(self) -> None:
        if not settings.redis_enabled or not settings.redis_host:
            logger.info("Redis 未配置，缓存能力已关闭（自动降级）")
            return
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            self._client = client
            self._enabled = True
            logger.info("Redis 已连接: %s:%s/%s", settings.redis_host, settings.redis_port, settings.redis_db)
        except Exception as exc:  # noqa: BLE001 - 任何异常都降级
            logger.warning("Redis 连接失败，缓存能力已关闭: %s", exc)
            self._client = None
            self._enabled = False

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                pass
        self._client = None
        self._enabled = False

    async def get_json(self, key: str) -> Any | None:
        if not self._enabled or self._client is None:
            return None
        try:
            raw = await self._client.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取缓存失败 key=%s: %s", key, exc)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        if not self._enabled or self._client is None:
            return
        try:
            await self._client.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("写入缓存失败 key=%s: %s", key, exc)

    async def delete(self, *keys: str) -> None:
        keys = tuple(k for k in keys if k)
        if not keys or not self._enabled or self._client is None:
            return
        try:
            await self._client.delete(*keys)
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除缓存失败 keys=%s: %s", keys, exc)

    async def delete_by_pattern(self, pattern: str) -> None:
        if not self._enabled or self._client is None:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = await self._client.scan(cursor=cursor, match=pattern, count=200)
                if keys:
                    await self._client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning("按模式删除缓存失败 pattern=%s: %s", pattern, exc)

    def fire_and_forget(self, coro: Any) -> None:
        """后台执行缓存维护动作，不阻塞请求，也不让异常冒泡到业务。"""
        if not self._enabled:
            try:
                coro.close()
            except Exception:  # noqa: BLE001
                pass
            return

        async def _runner() -> None:
            try:
                await coro
            except Exception as exc:  # noqa: BLE001
                logger.debug("后台缓存任务失败: %s", exc)

        try:
            asyncio.get_running_loop().create_task(_runner())
        except RuntimeError:
            try:
                coro.close()
            except Exception:  # noqa: BLE001
                pass


cache = Cache()


async def invalidate_article_cache(*slugs: str) -> None:
    """文章变更后的缓存失效：详情（新旧 slug）+ 归档 + 分类/标签计数 + 全部列表分页。"""
    keys = [KEY_CATEGORY_LIST, KEY_TAG_LIST, KEY_ARTICLE_ARCHIVES]
    seen: set[str] = set()
    for slug in slugs:
        if not slug or slug in seen:
            continue
        seen.add(slug)
        keys.append(article_detail_key(slug))
    await cache.delete(*keys)
    await cache.delete_by_pattern("article:list:*")


async def invalidate_article_list_cache() -> None:
    await cache.delete(KEY_CATEGORY_LIST, KEY_TAG_LIST, KEY_ARTICLE_ARCHIVES)
    await cache.delete_by_pattern("article:list:*")
