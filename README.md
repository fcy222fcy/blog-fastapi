# Gin Blog → FastAPI

把 `E:/goCode/goFile/gin博客` 这套 **Go + Gin + GORM** 博客后端，用 **Python + FastAPI + SQLAlchemy 2.0** 重写了一遍。

目标不是"写个像博客的 demo"，而是**接口契约逐字段兼容**：两个 Vue 前端（`blog-web` / `blog-admin`）一行不用改，直接指向新后端就能跑；两个实现还能共用一个 MySQL 库，读写同一批表。

---

## 一、原项目分析

### 1.1 规模与结构

| 维度 | 数据 |
|---|---|
| 后端代码 | 11,785 行 Go（不含测试），另有 ~1,600 行测试 |
| 模块 | 11 个业务模块 + 4 个中间件 + 12 个工具包 |
| 数据表 | 14 张 |
| HTTP 端点 | 41 个（公开 18 / 登录 5 / 博主专属 18） |
| 前端 | 2 套 Vue 3（前台 TailwindCSS、后台 Element Plus），82 个源文件 |

分层是标准的 `Controller → Service → Repository`：

```
internal/
├── api/v1/<module>/controller.go   # 参数绑定、错误转 HTTP 响应
├── api/v1/<module>/routes.go       # 路由 + 权限分层
├── service/<module>_service.go     # 业务规则、缓存、事务编排
├── repository/<module>_repository.go  # GORM 查询
└── model/{entity,dto}              # 表结构 / 请求响应体
pkg/                                # jwt / bcrypt / config / logger / redis /
                                    # response / errors / gravatar / ua / slug / visitor
```

### 1.2 数据模型

14 张表，其中 3 张是"计数/去重"专用表，也是设计上最有意思的地方：

| 表 | 作用 | 关键约束 |
|---|---|---|
| `articles` | 文章，`status` 三态 draft/published/scheduled | `slug` 唯一 |
| `categories` / `tags` | 分类、标签 | `name`、`slug` 各唯一 |
| `article_tags` | 多对多中间表 | 复合主键 |
| `comments` | 评论，`parent_id` 定楼层、`reply_to_id` 定"@谁" | `article_id` 索引 |
| `comment_like_logs` | 评论点赞去重 | **`(comment_id, visitor_ip)` 唯一** |
| `daily_questions` | 每日一问，`status` 0/1/2 | `date` 唯一 |
| `daily_question_like_logs` | 点赞去重 | **`(question_id, visitor_ip)` 唯一** |
| `content_view_events` | 浏览量按天去重 | **`(type,id,visitor_key,date)` 四列唯一** |
| `audit_logs` | 后台写操作审计 | 三段索引 |
| `users` / `media` / `about_pages` / `visit_logs` | 用户、媒体、关于页、访问日志 | — |

三条"唯一索引当并发控制"的设计值得抄：

1. **点赞防刷**：`INSERT ... ON CONFLICT DO NOTHING`，`RowsAffected == 0` 就返回"已点赞"。不用先查后写，天然抗并发。
2. **浏览去重**：插入成功才 `view_count + 1`。访客身份不落原始值，先 `HMAC-SHA256(JWT_SECRET, "anonymous:<uuid>" | "ip:<ip>")` 得到 64 位指纹再存。
3. **评论数一致性**：只统计 `approved`，状态变更时按 `delta` 增量更新，减操作带 `CASE WHEN count >= n` 下限保护。

### 1.3 三层身份体系

这是整个项目最容易被做错的地方——**三套身份，权限强度递增**：

```
游客 ──────────► OptionalAuth  ─► 能读评论、能发评论（昵称内联存储）
注册用户 ──────► Auth(JWT)     ─► 能改自己的资料/密码，**不能进后台**
博主 ──────────► RequireBlogger ─► 全部 admin 接口
```

`RequireBlogger` 的实现细节是：比对 `token.user_id == config.blogger.user_id`（配置里固定为 1）。**博主不是数据库里的某个角色，而是一个写死的 ID**。这样做的好处是博主身份无法通过改库提权；代价是改博主 ID 要改配置。

而且博主登录走的是**明文密码比对配置**，不经过 bcrypt —— 因为博主账号可能压根不在 `users` 表里。

> 这里有个坑必须复刻：`blogger_user_id` 未配置（=0）时，`RequireBlogger` **必须拒绝一切请求**。因为未登录请求的 `user_id` 也是 0，一旦放行就等于把后台开放给所有人。

### 1.4 几个实现得比较讲究的点

**评论楼中楼分页**：先只数根评论（`parent_id IS NULL`）作为分页基数，把**全量**根评论取到内存排序（因为 `hot` 排序依赖所有层级回复数，SQL 里要递归 CTE 且 MySQL 5.7 不支持），切片后再只为当前页的根评论重建回复树。如果直接用 SQL `LIMIT/OFFSET` 全表分页，会出现"一页只有半条楼"。

**搜索相关性**：标题命中 10 分 > 摘要 5 分 > 标签名 3 分 > 兜底 1 分，再按 `is_top DESC, created_at DESC` 排。同时从正文抽取关键词前后 45 字作为 `search_snippet`，如果摘要本身已命中就不截断正文。

**缓存失效粒度**：列表分页用 `article:list:*` 通配清，详情用精确 key（改 slug 时旧、新两个 key 都要清），分类/标签计数跟着文章变更一起失效。分类列表还有一个细节——**任意一次计数查询失败就跳过写缓存**，否则一个错误的 0 会被固化 30 分钟。

**定时发布**：用 cron 轮询 DB 而不是内存定时器。进程重启后内存任务全丢，而轮询只依赖 `status='scheduled' AND scheduled_at <= now`，天然可恢复。

---

## 二、重写方案

### 2.1 技术选型映射

| Go 生态 | FastAPI 生态 | 说明 |
|---|---|---|
| Gin | FastAPI | 路由 + 依赖注入 |
| GORM | SQLAlchemy 2.0（async） | 显式 `select()` 表达式，不用隐式懒加载 |
| go-playground/validator | Pydantic v2 | 校验失败 → 统一信封 |
| golang-jwt/v5 | PyJWT | **HS256 + 同样 claims，token 双向互通** |
| x/crypto/bcrypt | bcrypt | `$2a$` 哈希互相可验 |
| Viper + .env | pydantic-settings + 手写 .env 解析 | 环境变量名完全沿用 |
| Zap | logging + RotatingFileHandler | logger 命名沿用 `blog.*` |
| go-redis/v9 | redis.asyncio | 失败自动降级为无缓存 |
| robfig/cron | APScheduler | 30 秒轮询到期文章 |
| GORM AutoMigrate | `Base.metadata.create_all` | 只补缺表，不改已有列 |

**为什么用 async SQLAlchemy**：博客是 IO 密集（DB + Redis + SMTP），async 能让单进程撑住更多并发；同时 `select()` 显式风格比 ORM 隐式懒加载更容易复刻 GORM 的查询语义——GORM 的 `Preload` 对应这里的 `lazy="selectin"`，都是"显式声明要预加载什么"。

### 2.2 分层映射

保持同构，以便逐文件对照 review：

```
app/
├── api/v1/<module>.py        ←  internal/api/v1/<module>/{controller,routes}.go
├── services/<module>_service.py  ←  internal/service/<module>_service.go
├── repositories/<module>_repository.py ← internal/repository/*.go
├── models/                   ←  internal/model/entity/*.go
├── schemas/                  ←  internal/model/dto/*
└── core/                     ←  pkg/*
```

### 2.3 契约兼容：四个不能想当然的地方

**① 错误信封与状态码**

Go 版所有响应都是 `{code, message, data}`，HTTP 状态码按错误码区间推导：

| code 区间 | HTTP |
|---|---|
| 1000–1999（认证） | 401 |
| 2000–2999（参数） | 400 |
| 3000–3999（资源） | 404 |
| 4000–4999（业务） | 400 |

FastAPI 默认 422 + `{"detail": [...]}`，直接暴露给前端会让统一拦截器识别不到。所以加了 `RequestValidationError` 处理器折回 `{code: 2001, message: "参数错误"}`。

**② 时间格式**

Go 的 `time.Time` 序列化成 `2026-10-17T10:04:26+08:00`。Pydantic 默认输出 naive ISO（没有时区），前端 `new Date()` 会按本地时间解析——在非东八区浏览器里就差 8 小时。这里自定义了 `DateTimeStr` 类型，统一输出带 `+08:00` 的 RFC3339。

**③ 分页字段名**

Go 的 `PageResponse` 是 `{list, total, page, size, total_page}`。媒体列表页更特殊，用的是 `{list, total, page, page_size, category}` —— 两套字段名并存，照抄，不"统一"。

**④ 后台文章列表返回的是"实体"，不是前台列表项**

这一条在写完对照时才发现的：`GetAdminArticleList` 直接把 `[]*entity.Article` 塞进 `PageResponse`，仓库层只 `Omit("Content")`（不读 longtext，但结构体字段还在，所以 JSON 里 `content` 是 `""`）。

也就是说后台列表项带着 `status` / `is_top` / `scheduled_at` / `seo_*` / `category_id` / `updated_at` 等一整套实体字段，而前台列表项只有 11 个展示字段。一开始我复用前台序列化器，结果 `blog-admin/src/views/article/List.vue` 拿不到 `article.status`（状态徽标变空白、点不了切换）和 `article.is_top`（置顶标记永不显示）。现在改成独立的 `to_admin_entity()`，并给查询加了 `selectinload(category, tags)` + `defer(content)`。

### 2.4 刻意保留的"怪"行为

重写时遇到几处看起来像 bug 但被前端依赖的行为，我都保留了，并写进注释：

- **改标题会换 slug**：`UpdateArticle` 里标题变了且没显式给 slug，就按新标题重算。旧 URL 会 404（缓存失效只能清缓存，清不了已发出的外链）。
- **评论的 `article` 字段永远存在**：Go 里是值类型 struct，`omitempty` 对它无效，所以即使是空对象也会输出 `{id:0,title:"",slug:""}`。改成 `null` 会让前端 `comment.article.title` 抛异常。
- **博主改密码只改进程内存**：Go 版也是这样，重启回滚。已在代码里加了 warning 日志提示同步环境变量。

### 2.5 已知差异

| 项 | Go 版 | 本实现 | 影响 |
|---|---|---|---|
| 邮件发送 | 同步 goroutine | `asyncio.to_thread` | 行为一致，都不阻塞主流程 |
| 审计日志 | `go func()` 异步 | `await` 同请求内写 | 略增加响应耗时（约 1ms），换来"请求结束即落库"，不会因进程退出丢日志 |
| 登录限流 | 无 | 无 | 保持一致；生产建议在 Nginx 层加 `limit_req` |
| 媒体列表 `modified` | RFC3339 | 同样格式 | — |

### 2.6 契约验证结果

`tests/contract_check.py` 不是单元测试，而是「照着 Go 版行为逐条对账」的验收脚本：每一条断言都对应原项目里一个具体实现细节（字段集、状态码、错误码、去重语义），断言字段集合用的是 `==` 而不是 `⊇`——多一个字段也算不兼容。

```bash
./.venv/Scripts/python.exe -m app.main          # 另开一个终端
./.venv/Scripts/python.exe -m tests.contract_check
# 通过 116/116
```

脚本用过即清（文章/分类/标签/每日一问都在结尾删掉），注册账号与访客 ID 带时间戳，所以同一份库上可以连续重跑，实测连跑两次都是 116/116。

覆盖范围：

| 组 | 验证点 |
|---|---|
| 公开接口 | 列表字段集与 `ArticleListResponse` 完全一致、分页信封、RFC3339 时区、详情 SEO 字段、归档分组、搜索相关性、分类/标签计数、每日一问前后导航、关于页、RSS/Sitemap |
| 鉴权 | 游客 401、错误密码 1003、`expires_at` 是绝对时间戳、博主 `user_id` 恒为配置值、**普通用户 403**（Auth 只验签名，RequireBlogger 才验身份）、**签名篡改 401** |
| 文章 | 后台列表实体形状（`status`/`is_top`/`content` 为空串）、置顶 `is_top DESC` 排序、草稿前台 404、部分更新不清空 `is_top`/`scheduled_at`、纯中文标题回落 `post-<unix>`、英文标题重算 slug、无时间切 scheduled → 2001 |
| 评论 | 楼中楼、分页基数只数根评论、`reply_to` 带昵称、QQ 邮箱走 qlogo 头像、UA 解析出 Windows/Chrome、点赞 4006/4007、评论数同步 |
| 浏览 | 首次计入、同日同访客 `counted:false` 且不虚增 |
| 媒体 | 上传、静态服务、列表、扩展名白名单、**改后缀伪装图片被文件头嗅探拦下**、删除后 404、路径穿越被拒 |
| 用户 | 资料读写、旧密码错误 401/1003、改密后新旧密码生效性 |
| 审计 | 请求体落库、敏感字段脱敏成 `***`、非敏感字段保留 |
| 定时 | 未来时间点不进前台 → 改成过去 → 30 秒轮询自动上线 |

顺带修正的 Go 版小问题：`CODE_MESSAGES` 表里漏了 4001–4005，导致重名分类/标签直接回「未知错误」。本实现补了文案（见 `app/core/errors.py` 注释）。

---

## 三、快速开始

### 3.1 本地零依赖（SQLite）

```bash
cp .env.example .env
# 编辑 .env，把 DATABASE_URL 指向 SQLite：
#   DATABASE_URL=sqlite+aiosqlite:///./data/blog.db

python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
python -m app.main
```

启动后：

| 入口 | 地址 |
|---|---|
| API | http://localhost:9090/api/v1 |
| Swagger | http://localhost:9090/api/docs |
| 健康检查 | http://localhost:9090/api/v1/health |

首次启动会自动建表并灌入示例数据（3 分类 / 4 标签 / 3 文章 / 2 道每日一问 / 关于页）。

### 3.2 接已有 Go 版数据库（MySQL）

表结构由同一套 GORM 约定生成，**不需要迁移**：把 `DB_*` 指向 Go 版用的库即可。

```bash
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=yourpassword
DB_NAME=blog
```

> ⚠️ 两个实现同时写同一个库时，`updated_at` 由各自 ORM 维护，语义一致（本地时间 naive DATETIME）。

### 3.3 Docker

```bash
cp .env.example .env   # 至少改 JWT_SECRET 与 BLOGGER_PASSWORD
docker compose up -d
```

拓扑与 Go 版一致：MySQL + Redis + backend + Nginx 网关。

### 3.4 接前端

前端 `vite.config.js` 里的 proxy 指向 `http://localhost:9090` 即可，**API 路径不需要任何改动**：

```
/api/v1/articles            /api/v1/admin/articles
/api/v1/categories          /api/v1/admin/categories
/api/v1/comments            /api/v1/admin/comments
/api/v1/daily-questions     /api/v1/admin/daily-questions
/api/v1/views               /api/v1/admin/dashboard/stats
/api/v1/feed.xml            /api/v1/sitemap.xml
```

完整端点清单见 [docs/API.md](docs/API.md)。

---

## 四、目录结构

```
app/
├── main.py                # 应用装配、异常处理、CORS、静态文件
├── middleware.py          # 请求日志 + 审计中间件
├── scheduler.py           # 定时发布轮询
├── core/
│   ├── config.py          # 配置（yaml → .env → 环境变量三层覆写）
│   ├── errors.py          # 36 个错误码 + 区间→HTTP 映射
│   ├── response.py        # 统一信封 + 分页容器
│   ├── security.py        # JWT（与 Go 互通）+ bcrypt
│   ├── deps.py            # current_user / optional_user / require_blogger
│   ├── cache.py           # Redis 封装（失败降级）
│   ├── text.py            # slug / 阅读时长 / Markdown 剥离 / 搜索片段
│   ├── ua.py              # UA 解析（复刻 465 行 Go 实现的优先级顺序）
│   ├── avatar.py          # QQ 头像 → Gravatar 三级兜底
│   ├── visitor.py         # 访客 HMAC 指纹
│   └── http.py            # 真实客户端 IP
├── db/
│   ├── base.py            # 声明基类（BIGINT 在 SQLite 降级为 INTEGER）
│   ├── session.py         # 引擎/会话（MySQL 与 SQLite 双支持）
│   └── seed.py            # 首次启动种子数据
├── models/                # 14 张表的 ORM 定义
├── schemas/               # 请求/响应 Pydantic 模型
├── repositories/          # SQL 查询
├── services/              # 业务规则
└── api/v1/                # 路由
```

---

## 五、待办

- [ ] 登录/评论限流（当前依赖 Nginx 层）
- [ ] `content_view_events` 历史数据归档（只增不删，长期会膨胀）
- [ ] 文章 slug 变更时保留旧 slug 的 301 跳转（现在旧链接直接 404）
- [ ] 把 `blogger.password` 从明文配置改成 bcrypt 哈希
- [ ] 契约脚本目前只跑 SQLite；接 MySQL 跑 CI 需要独立 schema 或事务回滚兜底（脚本已支持在同库上重复运行）
