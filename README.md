# blog-fastapi

基于 **FastAPI + SQLAlchemy 2.0** 的博客后端，接口契约与同款 **Go / Gin / GORM** 实现逐字段对齐。

配套的两套 Vue 3 前端（`blog-web` 前台、`blog-admin` 后台）**无需修改任何代码**即可接入；两套后端也可以共用同一个 MySQL 数据库，读写同一批表。

> 适用场景：想用 Python 生态维护一个已有 Go 博客后端，同时不重写前端；或者想参考一个「契约兼容重写」的完整案例。

---

## 特性

- **58 个端点**，覆盖文章、分类、标签、评论、每日一问、媒体、用户、审计、仪表盘、RSS / Sitemap
- **三层身份体系**：游客（可读可评论）→ 注册用户（JWT，仅个人资料）→ 博主（`/admin/*` 与 `/media/*` 全部权限）
- **JWT 与密码哈希双向互通**：HS256 + 相同 claims（含 `iss`），bcrypt `$2a$`；Go 侧签发的 token 在本服务可验，反之亦然
- **并发安全靠数据库约束**：点赞、浏览去重都用唯一索引 + `INSERT ... ON CONFLICT DO NOTHING` 实现，不做「先查后写」
- **Redis 可选**：未配置时自动降级为无缓存，功能不受影响
- **定时发布可恢复**：30 秒轮询 `status='scheduled' AND scheduled_at <= now`，进程重启不丢任务
- **SQLite 零依赖启动**：不装 MySQL / Redis 也能跑起完整功能，适合本地开发和演示

## 技术栈

| 层 | 选型 |
|---|---|
| Web 框架 | FastAPI |
| ORM | SQLAlchemy 2.0（async，显式 `select()`） |
| 数据校验 | Pydantic v2 |
| 数据库 | MySQL 8 / SQLite（开发用） |
| 缓存 | Redis（可选） |
| 认证 | PyJWT（HS256）+ bcrypt |
| 调度 | APScheduler |
| 配置 | pydantic-settings（YAML → `.env` → 环境变量三层覆写） |

---

## 快速开始

### 1. 本地运行（SQLite，零外部依赖）

```bash
git clone https://github.com/fcy222fcy/blog-fastapi.git
cd blog-fastapi

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，指定 SQLite：
#   DATABASE_URL=sqlite+aiosqlite:///./data/blog.db

python -m app.main
```

首次启动会自动建表并写入示例数据（3 个分类、4 个标签、3 篇文章、2 道每日一问、关于页）。

| 入口 | 地址 |
|---|---|
| API | http://localhost:9090/api/v1 |
| 交互式文档 | http://localhost:9090/api/docs |
| 健康检查 | http://localhost:9090/api/v1/health |

### 2. 连接 MySQL

把 `DB_*` 指向已有数据库即可。表结构由同一套 GORM 约定生成，**不需要迁移**：

```ini
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=yourpassword
DB_NAME=blog
```

### 3. Docker Compose

```bash
cp .env.example .env    # 至少修改 JWT_SECRET 与 BLOGGER_PASSWORD
docker compose up -d
```

编排拓扑：MySQL + Redis + backend + Nginx 网关。

### 4. 接入前端

把前端 `vite.config.js` 中的代理指向本服务，或由 Nginx 反代 `/api`，**API 路径无需任何改动**：

```js
// vite.config.js
server: {
  proxy: {
    '/api': { target: 'http://localhost:9090', changeOrigin: true }
  }
}
```

---

## 配置

全部配置项见 [`.env.example`](.env.example)，以下为需要关注的几项：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SERVER_PORT` | `9090` | 服务端口 |
| `JWT_SECRET` | — | **生产必须修改**；同时用作访客指纹的 HMAC 密钥 |
| `JWT_EXPIRE_HOURS` | `168` | token 有效期 |
| `BLOGGER_USER_ID` | `1` | 博主身份的唯一依据，后台鉴权与它比对 |
| `BLOGGER_PASSWORD` | — | 博主明文密码，不走 `users` 表 |
| `DATABASE_URL` | — | 配置后覆盖 `DB_*`，用于 SQLite 等场景 |
| `CORS_ORIGINS` | — | 逗号分隔的允许来源 |
| `UPLOAD_DIR` | `uploads` | 媒体文件根目录 |

> `BLOGGER_USER_ID` 若为 `0`，所有后台接口一律拒绝访问 —— 未登录请求的 user_id 同样是 0，放行等于把后台完全开放。

---

## 接口概览

按权限分为四组，完整清单（含请求/响应字段）见 **[docs/API.md](docs/API.md)**。

| 权限 | 端点 |
|---|---|
| 公开 | `GET /articles` `GET /articles/{slug}` `GET /articles/search` `GET /articles/archives` `GET /categories` `GET /tags` `GET /comments/article/{id}` `GET /daily-questions/*` `GET /about` `GET /feed.xml` `GET /sitemap.xml` `POST /views` `POST /auth/login` `POST /auth/register` `GET /user/info` |
| 游客亦可写 | `POST /comments` `POST /comments/{id}/like` `DELETE /comments/{id}/like` `POST /daily-questions/{id}/like` |
| 需登录 | `GET /user/profile` `PUT /user/profile` `PUT /auth/password` |
| 博主 | `/admin/articles/*` `/admin/categories/*` `/admin/tags/*` `/admin/comments/*` `/admin/daily-questions/*` `/admin/dashboard/*` `/admin/audit-logs` `/admin/about` `/media/*` |

响应统一为：

```json
{ "code": 0, "message": "success", "data": {} }
```

分页响应的 `data` 为 `{ list, total, page, size, total_page }`（媒体列表沿用 `{ list, total, page, page_size, category }`，与前端保持一致）。

---

## 契约兼容性

这一节是这个项目最需要看的部分。重写时最容易出错的地方都在这里，每一条都对应原实现里的具体行为，改错会直接让前端静默失效。

### 错误码与 HTTP 状态码

响应体里的 `code` 表示业务错误，HTTP 状态码由 `code` 区间推导：

| code 区间 | 含义 | HTTP |
|---|---|---|
| `0` | 成功 | 200 |
| 1000–1999 | 认证 / 用户 | 401 |
| 2000–2999 | 参数 | 400 |
| 3000–3999 | 资源不存在 | 404 |
| 4000–4999 | 业务规则 | 400 |

FastAPI 默认的 `422 + {"detail": [...]}` 会让前端统一拦截器识别不到，因此注册了 `RequestValidationError` 处理器，折回 `{code: 2001, message: "参数错误"}`。

### 时间格式

所有时间字段输出带 `+08:00` 的 RFC3339（`2026-10-17T10:04:26+08:00`）。Pydantic 默认输出不带时区的 naive ISO 字符串，前端 `new Date()` 会按浏览器本地时区解析，在非东八区环境产生 8 小时偏移。这里通过自定义 `DateTimeStr` 类型统一序列化。

### 后台列表返回实体形状

`GET /admin/articles` 返回的列表项是**完整实体**，而非前台的展示型列表项：

- 含 `status`、`is_top`、`scheduled_at`、`seo_*`、`category_id`、`updated_at`
- `content` 恒为 `""`（列表查询刻意不读 longtext 正文）
- `tags` 无标签时为 `null`

管理后台依赖 `status` 渲染状态徽标与切换菜单、依赖 `is_top` 渲染置顶标记。若复用前台的序列化器，这两处会静默失效（徽标空白、无法切换）。因此后台与前台使用两套独立的序列化逻辑。

### 保留的既有行为

以下行为看起来反常，但被前端依赖或与既有数据相关，予以保留：

| 行为 | 说明 |
|---|---|
| 改标题会重算 slug | 未显式提供 `slug` 时按新标题生成，旧 URL 直接 404（已发出的外链会失效） |
| 纯中文标题的 slug | 生成的 slug 为空，回落为 `post-<Unix 秒>` |
| 评论的 `article` 字段恒存在 | 值为 `{id, title, slug}`，即使文章已不可见也输出零值对象而非 `null` |
| 博主改密码只改进程内存 | 博主账号来自配置而非数据库，重启后回滚；需同步修改 `BLOGGER_PASSWORD` |
| 媒体列表分页字段 | 使用 `page_size` 而非 `size` |

---

## 测试

`tests/contract_check.py` 是契约验收脚本，不是单元测试：每一条断言都对应参考实现的一个具体行为（字段集合、状态码、错误码、去重语义）。字段集合用 `==` 比较，多一个字段也视为不兼容。

```bash
# 终端 1
python -m app.main

# 终端 2
python -m tests.contract_check
# 通过 116/116
```

脚本具备幂等性：测试数据在结尾自行清理，注册账号与访客 ID 带运行时间戳，因此可以在同一份数据库上连续重跑。

| 分组 | 覆盖内容 |
|---|---|
| 公开接口 | 列表字段集合、分页信封、时区格式、详情 SEO 字段、归档分组、搜索相关性、分类 / 标签计数、每日一问前后导航、关于页、RSS / Sitemap |
| 鉴权 | 游客 401、密码错误 1003、`expires_at` 绝对值、普通用户访问后台 403、签名被篡改 401 |
| 文章 | 后台列表实体形状、置顶排序、草稿前台不可见、部分更新不清空 `is_top` / `scheduled_at`、slug 生成规则、无发布时间切定时发布 → 2001 |
| 评论 | 楼中楼结构、分页基数只计根评论、`reply_to` 昵称、QQ 邮箱头像、UA 解析、点赞 4006 / 4007、评论数同步 |
| 浏览 | 首次计入、同日同访客 `counted:false` 且计数不虚增 |
| 媒体 | 上传、静态访问、列表、扩展名白名单、伪装图片被文件头嗅探拦截、删除后 404、路径穿越拦截 |
| 用户 | 资料读写、旧密码校验、改密后新旧密码生效性 |
| 审计 | 请求体落库、敏感字段脱敏为 `***` |
| 定时 | 未到期不出现 → 改为过期后被轮询自动发布 |

---

## 项目结构

```
app/
├── main.py                 应用装配：异常处理、CORS、静态文件、生命周期
├── middleware.py            请求日志、后台写操作审计
├── scheduler.py             定时发布轮询
├── core/
│   ├── config.py            三层配置覆写
│   ├── errors.py            错误码与状态码映射
│   ├── response.py          统一响应信封、分页容器
│   ├── security.py          JWT、bcrypt
│   ├── deps.py              current_user / optional_user / require_blogger
│   ├── cache.py             Redis 封装（失败降级）
│   ├── text.py              slug、阅读时长、Markdown 剥离、搜索片段
│   ├── ua.py                User-Agent 解析
│   ├── avatar.py            QQ 头像 → Gravatar 兜底
│   ├── visitor.py           访客 HMAC 指纹
│   └── http.py              真实客户端 IP
├── db/                      引擎与会话、声明基类、种子数据
├── models/                  14 张表的 ORM 定义
├── schemas/                 请求 / 响应模型
├── repositories/            SQL 查询
├── services/                业务规则、缓存、事务
└── api/v1/                  路由（按模块拆分）
```

数据访问遵循 `Controller → Service → Repository` 分层，与参考实现保持同构，便于逐文件对照。

---

## 已知限制

- **无内置限流**：登录与评论的频控依赖 Nginx 层（`limit_req`），与参考实现一致
- **slug 变更无重定向**：改标题导致旧 URL 直接 404，未做 301 保留
- **浏览记录只增不删**：`content_view_events` 缺少归档策略，长期运行需要定期清理
- **博主密码为明文配置**：便于与既有部署保持一致，生产建议改为哈希
- **契约脚本面向 SQLite**：在 MySQL 上运行需要独立 schema，避免污染业务数据
