"""初始数据。

只在「库里一篇文章都没有」时执行一次，逻辑与 Go 版的 `SeedIfEmpty` 等价。
目的不是造演示站，而是让第一次 `docker-compose up` 之后后台能登录、
前台不是白板——否则要手工建分类、标签、博主账号才能发第一篇文章。

博主账号额外带一个「身份」用途：评论区要判断 `is_admin`，需要 users 表里
真有这条记录（配置里的 blogger_user_id 是 1）。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_password
from app.core.text import calculate_reading_time, generate_article_slug
from app.db.session import session_scope
from app.models.about_page import AboutPage
from app.models.article import STATUS_PUBLISHED, Article
from app.models.daily_question import STATUS_PUBLISHED as DQ_PUBLISHED, DailyQuestion
from app.models.taxonomy import Category, Tag
from app.models.user import User

logger = logging.getLogger("blog.seed")


def _sample_article_body() -> str:
    return """## 为什么重写

Go 版本跑得挺好，但想验证一件事：同样的接口契约，换一套技术栈能不能做到
**前端一行不改**。结论是可以，前提是把三个细节抠死——错误码、时间格式、
分页字段名。

## 三个必须对齐的细节

| 细节 | Go 版 | 踩坑点 |
|---|---|---|
| 统一信封 | `{code, message, data}` | 校验失败也要走信封，否则前端拦截器识别不到 |
| 时间格式 | RFC3339 +08:00 | 用 naive ISO 会让前端少 8 小时 |
| 分页字段 | `total_page` / `size` | 改成 `pageSize` 前端直接读不到 |

## 分层

Controller（路由）→ Service（业务）→ Repository（SQL），
和 Go 版同构。这样两个实现可以逐文件对照，review 成本最低。
"""


async def seed_if_empty() -> bool:
    async with session_scope() as session:
        count = int((await session.execute(select(func.count(Article.id)))).scalar() or 0)
        if count > 0:
            return False

        # ---- 博主账号 ----
        blogger = await session.get(User, settings.blogger_user_id)
        if blogger is None:
            session.add(
                User(
                    id=settings.blogger_user_id,
                    username=settings.blogger_username,
                    password=hash_password(settings.blogger_password or "admin123456"),
                    nickname=settings.blogger_nickname or "博主",
                    email=settings.blogger_email or "blogger@example.com",
                    avatar=settings.blogger_avatar or "",
                    bio="日常落灰的个人博客，擅长面向搜索引擎编程。",
                    status=1,
                )
            )
            await session.flush()

        # ---- 分类 ----
        categories = [
            Category(name="后端开发", slug="backend", description="Go / 数据库 / 架构", icon="⚙️", sort_order=1),
            Category(name="前端工程", slug="frontend", description="Vue / 构建 / 交互", icon="🎨", sort_order=2),
            Category(name="折腾记录", slug="notes", description="部署、运维与踩坑", icon="🔧", sort_order=3),
        ]
        session.add_all(categories)
        await session.flush()

        # ---- 标签 ----
        tags = [
            Tag(name="Go", slug="go"),
            Tag(name="FastAPI", slug="fastapi"),
            Tag(name="Docker", slug="docker"),
            Tag(name="SQLAlchemy", slug="sqlalchemy"),
        ]
        session.add_all(tags)
        await session.flush()

        # ---- 示例文章 ----
        body = _sample_article_body()
        now = datetime.now()
        articles = [
            Article(
                title="用 FastAPI 重写 Gin 博客后端",
                slug=generate_article_slug("用 FastAPI 重写 Gin 博客后端"),
                content=body,
                summary="保持接口契约不变，用 FastAPI + SQLAlchemy 2.0 重写 Gin 版本的后端，前端零改动接入。",
                category_id=categories[0].id,
                tags=[tags[0], tags[1], tags[3]],
                status=STATUS_PUBLISHED,
                is_top=True,
                reading_time=calculate_reading_time(body),
                created_at=now,
                updated_at=now,
            ),
            Article(
                title="分层架构里最容易塌的那一层",
                slug=generate_article_slug("分层架构里最容易塌的那一层"),
                content=(
                    "Controller → Service → Repository 三层里，最先腐化的从来不是 Controller，"
                    "而是 Service。\n\n"
                    "因为「业务逻辑」这个词没有边界：一旦允许 Service 直接写 SQL，"
                    "Repository 就会退化成一张表一个空壳。\n\n"
                    "判断标准很简单——把 Repository 换成内存实现，Service 还能跑吗？"
                ),
                summary="Controller、Service、Repository 三层中，Service 最先腐化。给出一个可操作的判断标准。",
                category_id=categories[0].id,
                tags=[tags[0]],
                status=STATUS_PUBLISHED,
                reading_time=2,
                created_at=now - timedelta(days=3),
                updated_at=now - timedelta(days=3),
            ),
            Article(
                title="Docker Compose 部署的三个隐式依赖",
                slug=generate_article_slug("Docker Compose 部署的三个隐式依赖"),
                content=(
                    "写 compose 文件时最容易忽略的不是端口映射，而是：\n\n"
                    "1. 服务启动顺序不等于依赖就绪（`depends_on` 只看容器状态，不看进程可用）\n"
                    "2. 数据卷权限（容器内 UID 与宿主机不一致，写日志直接 Permission denied）\n"
                    "3. 时区（镜像默认 UTC，日志时间差 8 小时，排查时非常误导）"
                ),
                summary="depends_on 不等依赖就绪、卷权限、时区——部署时最常被忽略的三个隐式依赖。",
                category_id=categories[2].id,
                tags=[tags[2]],
                status=STATUS_PUBLISHED,
                reading_time=2,
                created_at=now - timedelta(days=7),
                updated_at=now - timedelta(days=7),
            ),
        ]
        session.add_all(articles)

        # ---- 每日一问 ----
        today = date.today()
        session.add_all(
            [
                DailyQuestion(
                    question="为什么数据库唯一索引比「先查再写」更可靠？",
                    answer="因为唯一索引把判重交给了存储引擎的原子操作。应用层先 SELECT 再 INSERT "
                    "在并发下存在检查与写入之间的窗口，两个请求都可能查到「不存在」然后双双写入。",
                    date=(today - timedelta(days=1)).isoformat(),
                    status=DQ_PUBLISHED,
                ),
                DailyQuestion(
                    question="接口返回 `{code,message,data}` 信封有什么代价？",
                    answer="代价是不能直接复用 HTTP 状态码语义，需要额外维护一套 code ↔ status 的映射表；"
                    "好处是前端只需一处拦截器就能处理所有业务错误。",
                    date=today.isoformat(),
                    status=DQ_PUBLISHED,
                ),
            ]
        )

        # ---- 关于页面 ----
        session.add(
            AboutPage(
                title="关于我",
                subtitle="Go 后端 / 正在补 AI 的那一半",
                bio="日常落灰的个人博客，擅长面向搜索引擎编程。",
                skills='["Go","Python","FastAPI","PostgreSQL","Docker"]',
                about_me='[{"label":"职业","value":"后端开发","icon":"💼"},{"label":"方向","value":"后端 + AI","icon":"🎯"}]',
                about_site='[{"label":"重写自","value":"Go + Gin","icon":"⚙️"},{"label":"当前实现","value":"Python + FastAPI","icon":"🐍"}]',
                projects='[{"name":"GitHub","description":"各种编程项目","url":"https://github.com/fcy222fcy","icon":"⌘"}]',
                contact_info='[{"label":"GitHub","value":"fcy222fcy","icon":"🐙","url":"https://github.com/fcy222fcy"}]',
                site_history='[]',
            )
        )

        logger.info("初始数据已准备：%s 个分类、%s 个标签、%s 篇文章", len(categories), len(tags), len(articles))
        return True
