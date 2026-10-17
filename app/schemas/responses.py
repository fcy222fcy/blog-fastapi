"""响应模型。

字段名、可空性、以及 Go `omitempty` 的效果都逐一对齐。特别注意几处容易被
“优化”掉、但前端正在依赖的细节：

- 分页外壳是 `{list, total, page, size, total_page}`，不是 `page_size`
- 评论的 `article` 是值类型，Go 的 omitempty 对它无效，因此永远输出（哪怕是空对象）
- 评论的 `replies` 是切片，空切片被 omitempty 省略，前端用 `?? []` 兜底
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.common import APIModel, DateTimeStr


def _drop_empty(data: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        if not data.get(key):
            data.pop(key, None)
    return data


class CategoryResponse(APIModel):
    id: int = 0
    name: str = ""
    slug: str = ""
    description: str = ""
    icon: str = ""
    sort_order: int = 0
    article_count: int = 0


class TagResponse(APIModel):
    id: int = 0
    name: str = ""
    slug: str = ""
    article_count: int = 0
    created_at: DateTimeStr | None = None

    def dump(self) -> dict[str, Any]:
        data = self.model_dump()
        if data.get("created_at") is None:
            data["created_at"] = None
        return data


class ArticleBriefResponse(APIModel):
    id: int = 0
    title: str = ""
    slug: str = ""


class CommentResponse(APIModel):
    id: int
    content: str = ""
    nickname: str = ""
    email: str = ""
    website: str = ""
    avatar: str = ""
    status: str = ""
    is_admin: bool = False
    reply_to: str | None = None
    like_count: int = 0
    os: str | None = None
    os_version: str | None = None
    browser: str | None = None
    browser_version: str | None = None
    article: ArticleBriefResponse = Field(default_factory=ArticleBriefResponse)
    parent_id: int | None = None
    replies: list["CommentResponse"] | None = None
    created_at: DateTimeStr

    def dump(self) -> dict[str, Any]:
        data = self.model_dump()
        _drop_empty(data, ("reply_to", "os", "os_version", "browser", "browser_version"))
        if not data.get("replies"):
            data.pop("replies", None)
        return data


CommentResponse.model_rebuild()


class ArticleListItemResponse(APIModel):
    id: int
    title: str
    slug: str
    summary: str = ""
    cover: str = ""
    category: CategoryResponse = Field(default_factory=CategoryResponse)
    tags: list[TagResponse] = Field(default_factory=list)
    view_count: int = 0
    comment_count: int = 0
    reading_time: int = 0
    created_at: DateTimeStr


class ArticleDetailResponse(APIModel):
    id: int
    title: str
    slug: str
    content: str = ""
    summary: str = ""
    cover: str = ""
    category: CategoryResponse = Field(default_factory=CategoryResponse)
    tags: list[TagResponse] = Field(default_factory=list)
    view_count: int = 0
    comment_count: int = 0
    status: str = ""
    is_top: bool = False
    reading_time: int = 0
    seo_title: str = ""
    seo_description: str = ""
    seo_keywords: str = ""
    created_at: DateTimeStr
    updated_at: DateTimeStr


class AdminArticleDetailResponse(APIModel):
    id: int
    title: str
    slug: str
    content: str = ""
    summary: str = ""
    cover: str = ""
    status: str = ""
    is_top: bool = False
    category_id: int = 0
    tag_ids: list[int] = Field(default_factory=list)
    scheduled_at: DateTimeStr | None = None
    seo_title: str = ""
    seo_description: str = ""
    seo_keywords: str = ""


class SearchArticleResponse(ArticleListItemResponse):
    search_snippet: str | None = None

    def dump(self) -> dict[str, Any]:
        data = self.model_dump()
        _drop_empty(data, ("search_snippet",))
        return data


class ArchiveArticleResponse(APIModel):
    id: int
    title: str
    slug: str
    created_at: DateTimeStr


class ArchiveGroupResponse(APIModel):
    year: int
    articles: list[ArchiveArticleResponse]


class DailyQuestionResponse(APIModel):
    id: int
    question: str = ""
    answer: str = ""
    date: str = ""
    like_count: int = 0
    comment_count: int = 0
    view_count: int = 0
    status: int = 0
    created_at: DateTimeStr


class UserInfoResponse(APIModel):
    id: int
    username: str = ""
    nickname: str = ""
    avatar: str = ""
    email: str = ""


class LoginResponse(APIModel):
    token: str
    expires_at: int
    user: UserInfoResponse


class SocialLinkResponse(APIModel):
    name: str = ""
    url: str = ""


class UserProfileResponse(APIModel):
    id: int
    username: str = ""
    nickname: str = ""
    email: str = ""
    avatar: str = ""
    bio: str = ""
    social_links: list[SocialLinkResponse] = Field(default_factory=list)


class AuditLogResponse(APIModel):
    id: int
    operator_id: int = 0
    operator_name: str = ""
    action: str = ""
    target_type: str = ""
    target_id: int = 0
    target_title: str = ""
    detail: str = ""
    ip: str = ""
    created_at: DateTimeStr


class AboutPageResponse(APIModel):
    id: int = 0
    title: str = ""
    subtitle: str = ""
    bio: str = ""
    skills: str = ""
    about_me: str = ""
    about_site: str = ""
    projects: str = ""
    contact_info: str = ""
    site_history: str = ""


class DashboardStatsResponse(APIModel):
    article_count: int = 0
    published_count: int = 0
    draft_count: int = 0
    scheduled_count: int = 0
    total_views: int = 0
    today_views: int = 0
    comment_count: int = 0
    pending_count: int = 0


class RecentArticleResponse(APIModel):
    id: int
    title: str = ""
    summary: str = ""
    cover: str = ""
    view_count: int = 0
    created_at: str = ""


class ContentViewResult(APIModel):
    counted: bool = False
    view_count: int = 0
