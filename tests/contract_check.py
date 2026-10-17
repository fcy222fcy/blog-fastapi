"""接口契约验证脚本。

这不是单元测试，而是「照着 Go 版的行为逐条对账」的验收脚本：
每个断言都对应原项目里一个具体实现细节（字段名、状态码、错误码、去重语义）。

运行：python -m tests.contract_check
需要服务已在 127.0.0.1:9090 启动，且使用 SQLite（会写测试数据）。
"""

from __future__ import annotations

import sys
import time
import uuid
from datetime import datetime, timedelta

import httpx

BASE = "http://127.0.0.1:9090/api/v1"
ORIGIN = "http://127.0.0.1:9090"
client = httpx.Client(trust_env=False, base_url=BASE, timeout=10.0)

# 1x1 透明 PNG，用来验证上传 / 静态服务 / 删除整条链路
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f"  ->  {detail}" if detail else ""))


def get(path: str, **kwargs):
    return client.get(path, **kwargs)


def main() -> int:
    # ---------------------------------------------------------------- 公开接口
    r = get("/articles", params={"page": 1, "page_size": 2})
    body = r.json()
    check(r.status_code == 200 and body["code"] == 0, "文章列表 200/信封")
    data = body["data"]
    check(
        set(data.keys()) == {"list", "total", "page", "size", "total_page"},
        "分页字段为 list/total/page/size/total_page",
        str(sorted(data.keys())),
    )
    check(data["total"] >= 3 and len(data["list"]) == 2, "分页数量正确", f"total={data['total']}")

    first = data["list"][0]
    # 注意：列表项刻意不含 is_top/status（与 Go 版 ArticleListResponse 一致），
    # 但排序仍按 is_top DESC, created_at DESC 生效。
    check(
        set(first.keys())
        == {"id", "title", "slug", "summary", "cover", "category", "tags", "view_count",
            "comment_count", "reading_time", "created_at"},
        "列表项字段与 Go 版 ArticleListResponse 完全一致",
        str(sorted(first.keys())),
    )
    created_at = first["created_at"]
    check("+08:00" in created_at, "时间是带 +08:00 的 RFC3339", created_at)
    check(isinstance(first["category"], dict) and "article_count" in first["category"], "分类子对象结构")

    slug = first["slug"]
    r = get(f"/articles/{slug}")
    detail = r.json()["data"]
    check(r.status_code == 200 and "content" in detail and "seo_title" in detail, "文章详情含正文与 SEO 字段")

    r = get("/articles/not-exist-slug-xyz")
    body = r.json()
    check(r.status_code == 404 and body["code"] == 3001, "文章不存在 -> 404 / code 3001", str(body))

    r = get("/articles/archives")
    archives = r.json()["data"]
    check(isinstance(archives, list) and "year" in archives[0] and "articles" in archives[0], "归档按年份分组")

    r = get("/articles/search", params={"keyword": "FastAPI"})
    search = r.json()["data"]
    check(search["total"] >= 1, "搜索命中", f"total={search['total']}")
    hit = search["list"][0]
    check("search_snippet" not in hit or isinstance(hit["search_snippet"], str), "搜索片段为字符串")

    r = get("/categories")
    cats = r.json()["data"]
    check(len(cats) >= 3 and "article_count" in cats[0], "分类列表含文章数")

    r = get("/tags")
    tags = r.json()["data"]
    check(len(tags) >= 4 and "created_at" in tags[0], "标签列表含创建时间")
    tag_id = tags[0]["id"]

    r = get("/articles", params={"tag": tag_id})
    check(r.json()["data"]["total"] >= 1, "按标签过滤")

    # 每日一问
    r = get("/daily-questions/latest")
    latest = r.json()["data"]
    today = latest["date"]
    check(r.status_code == 200 and latest["status"] == 1, "最新每日一问")

    r = get("/daily-questions/all")
    check(len(r.json()["data"]) >= 2, "已发布每日一问列表")

    r = get(f"/daily-questions/date/{today}")
    check(r.status_code == 200, "按日期取题")

    r = get(f"/daily-questions/previous/{today}")
    check(r.status_code == 200, "前一天题目可导航")

    r = get("/daily-questions/next/2020-01-01")
    check(r.status_code == 200, "后一天题目可导航")

    # 关于页 / 用户信息 / 订阅
    r = get("/about")
    about = r.json()["data"]
    check("skills" in about and "site_history" in about, "关于页字段")

    r = get("/user/info")
    check("nickname" in r.json()["data"], "公开博主信息")

    r = get("/feed.xml")
    check(r.status_code == 200 and b"<rss" in r.content, "RSS 可访问")

    r = get("/sitemap.xml")
    check(r.status_code == 200 and b"<urlset" in r.content, "Sitemap 可访问")

    # ---------------------------------------------------------------- 鉴权
    r = get("/admin/dashboard/stats")
    check(r.status_code == 401, "无 token 访问后台 -> 401", str(r.status_code))

    r = client.post("/auth/login", json={"username": "admin", "password": "wrong-password"})
    check(r.status_code == 401 and r.json()["code"] == 1003, "错误密码 -> 401/1003", r.text[:120])

    r = client.post("/auth/login", json={"username": "admin", "password": "admin123456"})
    login = r.json()
    check(r.status_code == 200 and login["code"] == 0, "博主登录成功")
    token = login["data"]["token"]
    expires_at = login["data"]["expires_at"]
    check(isinstance(expires_at, int) and expires_at > 0, "返回绝对过期时间戳", str(expires_at))
    check(login["data"]["user"]["id"] == 1, "博主 user_id 恒为配置值")

    headers = {"Authorization": f"Bearer {token}"}

    r = get("/admin/dashboard/stats", headers=headers)
    stats = r.json()["data"]
    check(r.status_code == 200, "带 token 访问后台")
    check(
        set(stats.keys())
        == {"article_count", "published_count", "draft_count", "scheduled_count",
            "total_views", "today_views", "comment_count", "pending_count"},
        "仪表盘字段与 Go 版一致",
        str(sorted(stats.keys())),
    )

    r = get("/admin/dashboard/recent-articles", headers=headers)
    check(r.status_code == 200 and isinstance(r.json()["data"], list), "最近文章")

    # 后台列表返回的是实体形状（Go: []*entity.Article，仓库层只 Omit("Content")），
    # 不是前台的 ArticleListResponse —— 前端靠 status / is_top 渲徽标，缺了就点不了
    r = get("/admin/articles", headers=headers, params={"page": 1, "page_size": 3})
    item = r.json()["data"]["list"][0]
    expected_keys = {
        "id", "created_at", "updated_at", "title", "slug", "content", "summary", "cover",
        "category_id", "category", "tags", "view_count", "comment_count", "status",
        "is_top", "reading_time", "scheduled_at",
        "seo_title", "seo_description", "seo_keywords",
    }
    check(set(item.keys()) == expected_keys, "后台列表项字段与实体一致", str(sorted(item.keys())))
    check(item["content"] == "", "后台列表不取正文（对齐 Omit Content）")
    check(item["status"] in {"published", "draft", "scheduled"}, "后台列表带 status", item["status"])
    check(isinstance(item["is_top"], bool), "后台列表带 is_top", str(item["is_top"]))
    check(item["category"]["name"] != "", "后台列表预加载分类", item["category"]["name"])

    # ------------------------------------------------------------ admin CRUD
    r = client.post(
        "/admin/categories", headers=headers, json={"name": "契约测试分类", "slug": "", "icon": "🧪"}
    )
    cat_body = r.json()
    check(r.status_code == 200 and cat_body["data"]["id"] > 0, "创建分类")
    category_id = cat_body["data"]["id"]

    r = client.post("/admin/categories", headers=headers, json={"name": "契约测试分类"})
    check(r.status_code == 400 and r.json()["code"] == 4001, "重名分类 -> 400/4001", r.text[:100])

    r = client.post("/admin/tags", headers=headers, json={"name": "契约测试标签", "slug": ""})
    tag_new_id = r.json()["data"]["id"]
    check(tag_new_id > 0, "创建标签")

    article_payload = {
        "title": "契约测试文章",
        "content": "正文内容，用于验证阅读时长与搜索片段。" * 20,
        "summary": "摘要",
        "category_id": category_id,
        "tag_ids": [tag_new_id],
        "status": "published",
        "is_top": False,
    }
    r = client.post("/admin/articles", headers=headers, json=article_payload)
    article_id = r.json()["data"]["id"]
    check(article_id > 0, "创建文章", str(r.text[:120]))

    r = get(f"/admin/articles/{article_id}", headers=headers)
    admin_detail = r.json()["data"]
    check(admin_detail["tag_ids"] == [tag_new_id], "后台详情返回 tag_ids")
    new_slug = admin_detail["slug"]
    # 后台详情刻意不含 reading_time（与 Go 版 AdminArticleDetailResponse 一致），
    # 该字段只在列表与前台详情里出现
    check("reading_time" not in admin_detail, "后台详情字段与 Go 版一致")

    r = get(f"/articles/{new_slug}")
    check(r.json()["data"]["reading_time"] > 0, "创建时计算阅读时长",
          str(r.json()["data"]["reading_time"]))

    # 纯中文标题走 generateSlug 的空兜底：post-<unix 秒>
    check(new_slug.startswith("post-") and new_slug[5:].isdigit(),
          "纯中文标题回落 post-<时间戳>", new_slug)

    # 部分更新语义：只传 title，不应把 is_top/scheduled_at 清空
    r = client.put(f"/admin/articles/{article_id}", headers=headers, json={"title": "契约测试文章（改名）"})
    check(r.status_code == 200, "部分更新成功")
    r = get(f"/admin/articles/{article_id}", headers=headers)
    after = r.json()["data"]
    # 中文标题仍走兜底。这里不断言「slug 与旧值不同」：Go 的兜底是 int 秒级时间戳，
    # 创建与改标题落在同一秒时会得到相同值，那是 Go 的原生行为，不是缺陷。
    check(after["slug"].startswith("post-") and after["slug"][5:].isdigit(),
          "改中文标题后仍走兜底", after["slug"])

    # 换成 ASCII 标题才能真正验证「标题变更重算 slug」（Go: generateSlug(title)）
    r = client.put(f"/admin/articles/{article_id}", headers=headers,
                   json={"title": "Contract Renamed Title"})
    check(r.status_code == 200, "改英文标题成功")
    r = get(f"/admin/articles/{article_id}", headers=headers)
    after = r.json()["data"]
    check(after["slug"] == "contract-renamed-title",
          "改标题后 slug 按标题重算（与 Go 版一致）", after["slug"])

    # 状态机：切 scheduled 但没时间 -> 400
    r = client.put(f"/admin/articles/{article_id}/status", headers=headers, json={"status": "scheduled"})
    check(r.status_code == 400 and r.json()["code"] == 2001, "无发布时间切定时 -> 400/2001", r.text[:120])

    # 搜索命中新文章
    r = get("/articles/search", params={"keyword": "契约测试"})
    check(r.json()["data"]["total"] >= 1, "中文关键词搜索命中")

    # ---------------------------------------------------------------- 评论
    # 评论落库会解析 UA 记下 os/browser（omitempty，识别不出就不返回），
    # 所以这里必须显式给一个真实浏览器 UA，否则 python-httpx 会被判为未知。
    chrome_ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    r = client.post(
        "/comments",
        headers={"User-Agent": chrome_ua},
        json={
            "article_id": article_id,
            "content": "这是一条契约测试评论",
            "nickname": "测试访客",
            "email": "12345678@qq.com",
        },
    )
    comment_id = r.json()["data"]["id"]
    check(comment_id > 0, "创建评论")

    # 楼中楼
    r = client.post(
        "/comments",
        json={
            "article_id": article_id,
            "content": "这是一条回复",
            "nickname": "另一个访客",
            "parent_id": comment_id,
            "reply_to_id": comment_id,
        },
    )
    reply_id = r.json()["data"]["id"]
    check(reply_id > 0, "创建楼中楼回复")

    r = get(f"/comments/article/{article_id}")
    comments = r.json()["data"]
    check(comments["total"] == 1, "分页基数是根评论数（回复不计入）", f"total={comments['total']}")
    root = comments["list"][0]
    check(len(root.get("replies", [])) == 1, "回复挂在根评论下")
    check(root["replies"][0].get("reply_to") == "测试访客", "回复带 @被回复人", str(root["replies"][0].get("reply_to")))
    check(root["avatar"].startswith("https://q1.qlogo.cn"), "QQ 邮箱走 QQ 头像", root["avatar"][:48])
    check(root.get("browser") == "Chrome", "评论记录浏览器", str(root.get("browser")))
    check(root.get("os") == "Windows", "评论记录操作系统", str(root.get("os")))

    # 按 slug 查评论
    r = get(f"/comments/article/{after['slug']}")
    check(r.status_code == 200, "评论接口支持 slug")

    # 点赞去重
    r = client.post(f"/comments/{comment_id}/like")
    check(r.status_code == 200, "首次点赞成功")
    r = client.post(f"/comments/{comment_id}/like")
    check(r.status_code == 400 and r.json()["code"] == 4006, "重复点赞 -> 400/4006", r.text[:100])
    r = client.delete(f"/comments/{comment_id}/like")
    check(r.status_code == 200, "取消点赞")
    r = client.delete(f"/comments/{comment_id}/like")
    check(r.status_code == 400 and r.json()["code"] == 4007, "重复取消 -> 400/4007", r.text[:100])

    # 评论数同步
    r = get(f"/articles/{after['slug']}")
    check(r.json()["data"]["comment_count"] >= 2, "评论数已同步到文章", str(r.json()["data"]["comment_count"]))

    # 后台评论列表
    r = get("/admin/comments", headers=headers)
    check(r.status_code == 200 and r.json()["data"]["total"] >= 2, "后台评论列表")

    # ------------------------------------------------------------ 浏览量去重
    # 去重键是 (content_type, content_id, 访客指纹, 日期)。脚本会在结尾删文章，
    # 而自增主键会被复用，所以固定 visitor id 在「不清库重跑」时会撞上一次的记录。
    # 每次运行换一个 visitor，才是真实场景下的行为。
    visitor_id = str(uuid.uuid4())
    r = client.post(
        "/views", json={"content_type": "article", "content_id": article_id},
        headers={"X-Visitor-ID": visitor_id},
    )
    first_view = r.json()["data"]
    check(first_view["counted"] is True, "首次浏览计入")

    r = client.post(
        "/views", json={"content_type": "article", "content_id": article_id},
        headers={"X-Visitor-ID": visitor_id},
    )
    second_view = r.json()["data"]
    check(second_view["counted"] is False, "同一天同一访客不再计入")
    check(second_view["view_count"] == first_view["view_count"], "浏览量未虚增",
          f"{first_view['view_count']} -> {second_view['view_count']}")

    r = client.post("/views", json={"content_type": "unknown", "content_id": 1})
    check(r.status_code == 400, "非法 content_type -> 400")

    # ---------------------------------------------------------------- 校验
    r = client.post("/admin/articles", headers=headers, json={})
    check(r.status_code == 400 and r.json()["code"] == 2001, "缺必填参数 -> 400/2001 统一信封", r.text[:100])
    check(set(r.json().keys()) == {"code", "message", "data"}, "校验错误也是统一信封")

    # ---------------------------------------------------------------- 审计
    r = get("/admin/audit-logs", headers=headers)
    logs = r.json()["data"]
    check(logs["total"] >= 1, "审计日志已记录后台写操作", f"total={logs['total']}")
    actions = {item["action"] for item in logs["list"]}
    check("create" in actions, "记录了 create 动作")
    detail_blob = " ".join(item["detail"] for item in logs["list"])
    check("契约测试文章" in detail_blob, "审计详情捕获了请求体")

    # 脱敏是纯函数逻辑，直接单元级断言（真实路由里 /auth/password 不在 /admin/ 下，
    # 不会被审计中间件捕获，所以走不了 HTTP）
    from app.middleware import sanitize_body

    masked = sanitize_body(
        b'{"old_password":"hunter2","new_password":"hunter3","nickname":"keep-me"}'
    )
    check("hunter2" not in masked and "***" in masked, "敏感字段被脱敏成 ***", masked)
    check("keep-me" in masked, "非敏感字段保留原文")

    # ------------------------------------------------------------ 权限分层
    # 注册不签发 token（Go 版 response.Success(ctx, nil)），需再登录。
    # 账号名带上运行时间戳，脚本才能在同一份库上重复跑（重复邮箱会 400）。
    reader_name = f"reader{int(time.time())}"
    reader_pass = "reader123"
    r = client.post("/auth/register", json={
        "username": reader_name, "password": reader_pass,
        "nickname": "读者", "email": f"{reader_name}@example.com",
    })
    check(r.status_code == 200 and r.json()["data"] is None, "注册普通用户返回 data=null", r.text[:100])

    r = client.post("/auth/login", json={"username": reader_name, "password": reader_pass})
    reader_login = r.json()["data"]
    check(reader_login["user"]["id"] != 1, "注册用户不是博主", f"user_id={reader_login['user']['id']}")
    reader_headers = {"Authorization": f"Bearer {reader_login['token']}"}

    # Auth 只验签名，RequireBlogger 才验身份：合法 token 也必须 403
    r = get("/admin/dashboard/stats", headers=reader_headers)
    check(r.status_code == 403 and r.json()["code"] == 403, "普通用户进后台 -> 403", r.text[:80])
    r = client.post("/admin/articles", headers=reader_headers, json={"title": "x", "content": "y"})
    check(r.status_code == 403, "普通用户写后台 -> 403")

    # 篡改签名必须被拒（HS256 校验，不是解 payload 就放行）
    token = headers["Authorization"].split(" ", 1)[1]
    tampered = {"Authorization": f"Bearer {token[:-3]}abc"}
    r = get("/admin/dashboard/stats", headers=tampered)
    check(r.status_code == 401, "签名被篡改的 token -> 401", r.text[:80])

    # ------------------------------------------------------- 置顶 / 草稿可见性
    r = client.post("/admin/articles", headers=headers, json={
        "title": "Top Pinned Post", "content": "置顶文章正文", "summary": "置顶",
        "category_id": category_id, "status": "published", "is_top": True,
    })
    top_id = r.json()["data"]["id"]
    check(top_id > 0, "创建置顶文章")

    r = client.post("/admin/articles", headers=headers, json={
        "title": "Draft Only Post", "content": "草稿正文", "summary": "草稿",
        "category_id": category_id, "status": "draft",
    })
    draft_id = r.json()["data"]["id"]
    check(draft_id > 0, "创建草稿")

    r = get("/articles", params={"page": 1, "page_size": 5})
    first = r.json()["data"]["list"][0]
    check(first["id"] == top_id, "列表按 is_top DESC 排序", f"first={first['title']}")

    r = get("/admin/articles", headers=headers, params={"page": 1, "page_size": 20, "status": "draft"})
    draft_ids = [it["id"] for it in r.json()["data"]["list"]]
    check(draft_id in draft_ids and r.json()["data"]["list"][0]["status"] == "draft",
          "后台按 status=draft 过滤", f"drafts={draft_ids}")

    r = get(f"/admin/articles/{draft_id}", headers=headers)
    draft_slug = r.json()["data"]["slug"]
    r = get(f"/articles/{draft_slug}")
    check(r.status_code == 404, "草稿在前台不可见", str(r.status_code))

    # ----------------------------------------------------------- 每日一问 CRUD
    r = client.post("/admin/daily-questions", headers=headers, json={
        "question": "契约测试问题？", "answer": "契约测试答案。", "date": "2026-01-02", "status": 1,
    })
    check(r.status_code == 200 and r.json()["data"]["id"] > 0, "创建每日一问", r.text[:100])
    qid = r.json()["data"]["id"]

    r = client.post("/admin/daily-questions", headers=headers, json={
        "question": "同日重复？", "answer": "答案。", "date": "2026-01-02", "status": 1,
    })
    check(r.status_code == 400 and r.json()["code"] == 4005, "同日重复 -> 400/4005", r.text[:100])

    r = client.put(f"/admin/daily-questions/{qid}", headers=headers, json={"question": "改过的问题？"})
    check(r.status_code == 200, "更新每日一问（部分字段）")
    r = get("/daily-questions/date/2026-01-02")
    check(r.json()["data"]["question"] == "改过的问题？", "更新后按日期可读到新内容")

    r = client.put(f"/admin/daily-questions/{qid}/status", headers=headers, json={"status": 0})
    check(r.status_code == 200, "切换每日一问状态")
    r = get("/daily-questions/date/2026-01-02")
    check(r.status_code == 404, "禁用后按日期查不到", str(r.status_code))

    r = client.delete(f"/admin/daily-questions/{qid}", headers=headers)
    check(r.status_code == 200, "删除每日一问")

    # ------------------------------------------------------------- 关于页更新
    r = client.put("/admin/about", headers=headers, json={
        "title": "关于我", "subtitle": "契约测试副标题", "bio": "简介",
        "skills": "Go,Python", "about_me": "关于正文", "about_site": "关于本站",
        "projects": "项目", "contact_info": "mail@example.com", "site_history": "历史",
    })
    check(r.status_code == 200, "更新关于页", r.text[:100])
    r = get("/about")
    about = r.json()["data"]
    check(about["subtitle"] == "契约测试副标题", "关于页改动已生效", str(about.get("subtitle")))

    # ------------------------------------------------------------- 用户中心
    r = get("/user/profile", headers=reader_headers)
    profile = r.json()["data"]
    check(profile["username"] == reader_name, "登录后可读自己的资料", profile.get("username"))

    r = client.put("/user/profile", headers=reader_headers,
                   json={"nickname": "改过的昵称", "bio": "契约测试简介"})
    check(r.status_code == 200, "更新资料", r.text[:100])
    r = get("/user/profile", headers=reader_headers)
    check(r.json()["data"]["nickname"] == "改过的昵称", "资料改动已生效")

    r = client.put("/auth/password", headers=reader_headers,
                   json={"old_password": "wrong-pass", "new_password": "reader456"})
    # 1003 落在 1000-1999 段，按错误码推导 HTTP 状态是 401 而不是 400
    check(r.status_code == 401 and r.json()["code"] == 1003, "旧密码错误 -> 401/1003", r.text[:100])
    r = client.put("/auth/password", headers=reader_headers,
                   json={"old_password": reader_pass, "new_password": "reader456"})
    check(r.status_code == 200, "改密码成功", r.text[:100])
    r = client.post("/auth/login", json={"username": reader_name, "password": "reader456"})
    check(r.status_code == 200, "新密码可登录")
    r = client.post("/auth/login", json={"username": reader_name, "password": reader_pass})
    check(r.status_code == 401 and r.json()["code"] == 1003, "旧密码已失效")

    # ----------------------------------------------------------------- 媒体
    r = client.post(
        "/media/upload",
        headers=headers,
        files={"file": ("pixel.png", _PNG, "image/png")},
        data={"category": "avatar"},
    )
    check(r.status_code == 200, "上传图片", r.text[:120])
    uploaded = r.json()["data"]
    check(uploaded["url"].startswith("/uploads/avatar/"), "落在 avatar 分类目录", uploaded["url"])
    stored_name = uploaded["url"].rsplit("/", 1)[-1]

    r = client.get(ORIGIN + uploaded["url"])
    check(r.status_code == 200 and r.content == _PNG, "静态服务能取回原文件")

    r = get("/media", headers=headers, params={"category": "avatar", "page_size": 50})
    names = [item["name"] for item in r.json()["data"]["list"]]
    check(stored_name in names, "媒体列表能扫到新文件")

    r = client.post(
        "/media/upload", headers=headers,
        files={"file": ("bad.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    check(r.status_code == 400, "非白名单扩展名被拒")

    # 伪装：扩展名 .png 但内容不是图片，必须被文件头嗅探拦下
    r = client.post(
        "/media/upload", headers=headers,
        files={"file": ("fake.png", b"MZ\x90\x00not-an-image", "image/png")},
    )
    check(r.status_code == 400 and "不匹配" in r.json()["message"], "改后缀伪装图片被拦", r.text[:100])

    r = client.delete(f"/media/{stored_name}", headers=headers, params={"category": "avatar"})
    check(r.status_code == 200, "删除文件", r.text[:100])
    r = client.get(ORIGIN + uploaded["url"])
    check(r.status_code == 404, "删除后静态地址失效")

    # 路径穿越必须被拒（不能靠 ../ 删到 uploads 之外）
    r = client.delete("/media/..%2F..%2Fconfig.yaml", headers=headers, params={"category": "avatar"})
    check(r.status_code in (400, 404), "路径穿越被拒", str(r.status_code))

    # -------------------------------------------------------- 定时发布自动上线
    # 不订阅内存定时器，靠 30 秒轮询扫 status='scheduled' AND scheduled_at <= now，
    # 进程重启天然可恢复。分两步验证：未来时间点不出现 → 改成过去时间后自动上线。
    future = (datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds")
    r = client.post("/admin/articles", headers=headers, json={
        "title": "Scheduled Auto Publish", "content": "定时正文", "summary": "定时",
        "category_id": category_id, "status": "scheduled", "scheduled_at": future,
    })
    sched_id = r.json()["data"]["id"]
    check(sched_id > 0, "创建定时文章", r.text[:100])

    r = get("/articles", params={"page": 1, "page_size": 50})
    titles = [it["title"] for it in r.json()["data"]["list"]]
    check("Scheduled Auto Publish" not in titles, "未到点的定时文章不出现在前台")

    past = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")
    r = client.put(f"/admin/articles/{sched_id}", headers=headers, json={"scheduled_at": past})
    check(r.status_code == 200, "把发布时间改到过去（部分更新 scheduled_at）")

    print("      等待轮询发布（最长 35 秒）...")
    time.sleep(35)
    r = get("/articles", params={"page": 1, "page_size": 50})
    titles = [it["title"] for it in r.json()["data"]["list"]]
    check("Scheduled Auto Publish" in titles, "到点后被轮询自动发布")

    # ---------------------------------------------------------------- 清理
    client.delete(f"/admin/articles/{article_id}", headers=headers)
    client.delete(f"/admin/articles/{top_id}", headers=headers)
    client.delete(f"/admin/articles/{draft_id}", headers=headers)
    client.delete(f"/admin/articles/{sched_id}", headers=headers)
    client.delete(f"/admin/categories/{category_id}", headers=headers)
    client.delete(f"/admin/tags/{tag_new_id}", headers=headers)
    r = get(f"/articles/{after['slug']}")
    check(r.status_code == 404, "删除文章后前台不可见")

    # ---------------------------------------------------------------- 汇总
    passed = sum(1 for ok, _, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"通过 {passed}/{total}")
    failed = [(name, detail) for ok, name, detail in results if not ok]
    if failed:
        print("失败项：")
        for name, detail in failed:
            print(f"  - {name}  {detail}")
    print("=" * 60)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
