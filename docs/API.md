# API 参考

所有接口前缀为 `/api/v1`，响应统一使用如下信封：

```json
{ "code": 0, "message": "success", "data": {} }
```

`code` 为 0 表示成功，非 0 时 HTTP 状态码由 `code` 区间推导（见文末错误码表）。

**鉴权**：需要登录的接口在请求头携带 `Authorization: Bearer <token>`，token 由 `POST /auth/login` 获取。

**分页**：请求参数 `page`（默认 1）、`page_size`（默认 10，上限 100）；响应 `data` 为 `{ list, total, page, size, total_page }`。媒体列表例外，使用 `{ list, total, page, page_size, category }`。

**时间**：所有时间字段为带 `+08:00` 的 RFC3339 字符串。

---

## 认证 `/auth`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/auth/login` | 公开 | 登录，`username` 或 `email` + `password`；返回 `token`、`expires_at`（Unix 秒）、`user` |
| POST | `/auth/register` | 公开 | 注册，需 `nickname`、`email`、`password`；成功返回 `data: null`，需再调用登录 |
| PUT | `/auth/password` | 登录 | 修改密码，需 `old_password`、`new_password` |

## 文章 `/articles`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/articles` | 公开 | 列表。参数：`page`、`page_size`、`category_id`、`tag`、`keyword`；排序 `is_top DESC, created_at DESC` |
| GET | `/articles/search` | 公开 | 搜索。参数：`keyword`、`page`、`page_size`；按相关性排序并返回 `search_snippet` |
| GET | `/articles/archives` | 公开 | 归档，按年月分组 |
| GET | `/articles/{slug}` | 公开 | 详情，仅返回已发布文章 |
| GET | `/admin/articles` | 博主 | 后台列表。参数：`page`、`page_size`、`status`、`keyword`、`category_id`；**返回实体形状**（含 `status`、`is_top`，`content` 为空串） |
| GET | `/admin/articles/{id}` | 博主 | 后台详情，含 `tag_ids`，不含 `reading_time` |
| POST | `/admin/articles` | 博主 | 创建，返回 `{ "id": n }` |
| PUT | `/admin/articles/{id}` | 博主 | 部分更新，未提交的字段保持不变 |
| PUT | `/admin/articles/{id}/status` | 博主 | 切换状态；切为 `scheduled` 若无 `scheduled_at` 返回 2001 |
| DELETE | `/admin/articles/{id}` | 博主 | 删除 |
| POST | `/admin/articles/batch-delete` | 博主 | 批量删除，参数 `{ "ids": [1,2] }` |

文章状态 `status` 取值：`draft`、`published`、`scheduled`。

## 分类与标签

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/categories` | 公开 | 分类列表，含 `article_count` |
| GET | `/categories/{id}` | 公开 | 分类详情 |
| GET | `/tags` | 公开 | 标签列表 |
| POST | `/admin/categories` | 博主 | 创建；重名返回 4001 |
| PUT | `/admin/categories/{id}` | 博主 | 更新 |
| DELETE | `/admin/categories/{id}` | 博主 | 删除；分类下有文章返回 4002 |
| POST | `/admin/tags` | 博主 | 创建；重名返回 4003 |
| PUT | `/admin/tags/{id}` | 博主 | 更新 |
| DELETE | `/admin/tags/{id}` | 博主 | 删除；标签下有文章返回 4004 |

## 评论 `/comments`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/comments/article/{articleId}` | 公开 | 文章评论树。路径参数可为文章 ID 或 slug；参数 `page`、`page_size`、`sort_by`（`desc` 默认 / `asc` / `hot`）。分页基数为**根评论数**，回复不计入 |
| POST | `/comments` | 游客亦可 | 发表评论。`article_id`、`content`、`nickname` 必填；回复传 `parent_id` 与 `reply_to_id` |
| POST | `/comments/{id}/like` | 游客亦可 | 点赞，按客户端 IP 去重；重复点赞返回 4006 |
| DELETE | `/comments/{id}/like` | 游客亦可 | 取消点赞；未点赞返回 4007 |
| GET | `/admin/comments` | 博主 | 后台列表，支持 `status`、`keyword`、`page` |
| PUT | `/admin/comments/{id}/status` | 博主 | 审核状态切换（`approved` / `pending` / `rejected`） |
| DELETE | `/admin/comments/{id}` | 博主 | 删除 |
| POST | `/admin/comments/batch-delete` | 博主 | 批量删除 |

评论对象包含 `os`、`os_version`、`browser`、`browser_version`，由 `User-Agent` 解析；识别不出时字段不返回。请求若显式携带这些字段，则以请求为准。

## 每日一问 `/daily-questions`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/daily-questions/latest` | 公开 | 最新一期 |
| GET | `/daily-questions/all` | 公开 | 全部已发布 |
| GET | `/daily-questions/date/{date}` | 公开 | 按日期取（`YYYY-MM-DD`） |
| GET | `/daily-questions/previous/{date}` | 公开 | 上一期 |
| GET | `/daily-questions/next/{date}` | 公开 | 下一期 |
| POST | `/daily-questions/{id}/like` | 游客亦可 | 点赞，返回最新 `like_count` |
| GET | `/admin/daily-questions` | 博主 | 后台列表，支持 `status`、`keyword`、`date` |
| POST | `/admin/daily-questions` | 博主 | 创建；日期重复返回 4005 |
| PUT | `/admin/daily-questions/{id}` | 博主 | 更新 |
| PUT | `/admin/daily-questions/{id}/status` | 博主 | 状态切换（`0` 禁用 / `1` 发布 / `2` 定时） |
| DELETE | `/admin/daily-questions/{id}` | 博主 | 删除 |

## 媒体 `/media`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/media/upload` | 博主 | 表单上传，字段 `file`、`category`；限制 5MB，扩展名白名单，非 PDF 会校验文件头 |
| GET | `/media` | 博主 | 文件列表，参数 `category`、`page`、`page_size`、`keyword` |
| DELETE | `/media/{filename}` | 博主 | 删除；`category` 可放在查询参数或路径中 |
| GET | `/uploads/{category}/{filename}` | 公开 | 静态文件访问（不在 `/api/v1` 下） |

`category` 取值：`avatar`、`article`、`daily`、`entertainment`、`link`、`common`。非法值统一归为 `common`。

## 用户 `/user`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/user/info` | 公开 | 博主公开信息 |
| GET | `/user/profile` | 登录 | 当前用户资料 |
| PUT | `/user/profile` | 登录 | 更新资料，字段均可选 |

## 内容视图

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/views` | 公开 | 记录浏览。请求体 `content_type`（`article` / `daily_question`）、`content_id`；可选请求头 `X-Visitor-ID`。同一访客同一天只计一次，返回 `{ counted, view_count }` |

## 站点与其他

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/about` | 公开 | 关于页内容 |
| PUT | `/admin/about` | 博主 | 更新关于页 |
| GET | `/admin/dashboard/stats` | 博主 | 仪表盘统计 |
| GET | `/admin/dashboard/recent-articles` | 博主 | 最近文章 |
| GET | `/admin/audit-logs` | 博主 | 审计日志，参数 `page`、`page_size`、`action`、`target_type` |
| GET | `/feed.xml` | 公开 | RSS |
| GET | `/rss` | 公开 | 同上 |
| GET | `/sitemap.xml` | 公开 | Sitemap |
| GET | `/health` | 公开 | 健康检查，返回 `{ status, database }` |

---

## 错误码

| code | HTTP | 含义 |
|---|---|---|
| 0 | 200 | 成功 |
| 400 | 400 | 请求错误 |
| 401 | 401 | 未授权 |
| 403 | 403 | 禁止访问 |
| 404 | 404 | 资源不存在 |
| 500 | 500 | 服务器内部错误 |
| 1001 | 401 | 用户不存在 |
| 1002 | 400 | 用户已存在 |
| 1003 | 401 | 密码错误 |
| 1004 | 401 | Token 已过期 |
| 1005 | 401 | Token 无效 |
| 1006 | 403 | 账号已禁用 |
| 2001 | 400 | 参数错误 |
| 2002 | 400 | 缺少必填参数 |
| 2003 | 400 | 邮箱格式错误 |
| 2004 | 400 | 手机号格式错误 |
| 2005 | 400 | 密码长度不足 |
| 2006 | 400 | 用户名长度不足 |
| 3001 | 404 | 文章不存在 |
| 3002 | 404 | 分类不存在 |
| 3003 | 404 | 标签不存在 |
| 3004 | 404 | 评论不存在 |
| 3006 | 404 | 每日一问不存在 |
| 3007 | 404 | 媒体文件不存在 |
| 3008 | 404 | 页面不存在 |
| 3009 | 404 | 记录不存在 |
| 4001 | 400 | 分类名称已存在 |
| 4002 | 400 | 分类下仍有文章 |
| 4003 | 400 | 标签名称已存在 |
| 4004 | 400 | 标签下仍有文章 |
| 4005 | 400 | 该日期已存在问题 |
| 4006 | 400 | 已点赞 |
| 4007 | 400 | 尚未点赞 |
| 4008 | 400 | 已点赞（通用） |

> `3005` 为保留空缺，与参考实现保持一致。
