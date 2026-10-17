"""请求体模型。

字段名与 Go 版 DTO 的 json tag 完全一致（`category_id`、`tag_ids`、`seo_title`…），
校验规则也对齐 `binding` tag 的语义。

「部分更新」是这里最容易踩坑的地方：Go 用指针区分「字段未传」和「显式传零值」，
Pydantic 用 `model_fields_set` 表达同一件事——只要字段出现在请求体里就算显式提交。
service 层统一通过 `has_field()` 判断，不要用 `is not None`。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import StrictModel

ArticleStatus = Literal["published", "draft", "scheduled"]
CommentStatus = Literal["approved", "rejected"]
CommentStatusFilter = Literal["pending", "approved", "rejected"]


class HasFieldMixin(StrictModel):
    """给部分更新请求用的辅助方法。"""

    def has_field(self, name: str) -> bool:
        return name in self.model_fields_set


# --------------------------------------------------------------------------- auth


class LoginRequest(StrictModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    password: str = Field(min_length=6, max_length=50)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        # Go 版这里是 omitempty,email，只做格式校验（不允许空串当作已填）
        if "@" not in v or v.strip() != v:
            raise ValueError("邮箱格式错误")
        return v.strip()

    @field_validator("username")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return v if (v and v.strip()) else None

    def validate_login(self) -> bool:
        return bool((self.email or "").strip() or (self.username or "").strip())


class RegisterRequest(StrictModel):
    username: str | None = Field(default=None, max_length=50)
    password: str = Field(min_length=6, max_length=50)
    nickname: str = Field(min_length=1, max_length=50)
    email: EmailStr


class UpdateUserRequest(StrictModel):
    nickname: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=100)
    avatar: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=500)


class ChangePasswordRequest(StrictModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6, max_length=50)


# ------------------------------------------------------------------------ article


class CreateArticleRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    summary: str = Field(default="", max_length=500)
    cover: str = Field(default="", max_length=500)
    category_id: int = Field(gt=0)
    tag_ids: list[int] = Field(default_factory=list)
    status: ArticleStatus | None = None
    is_top: bool = False
    slug: str = Field(default="", max_length=200)
    scheduled_at: datetime | None = None
    # 迁移历史文章时保留原始发布时间
    created_at: datetime | None = None
    seo_title: str = Field(default="", max_length=200)
    seo_description: str = Field(default="", max_length=500)
    seo_keywords: str = Field(default="", max_length=300)


class UpdateArticleRequest(HasFieldMixin):
    """部分更新。未出现的字段不改动，显式 null 表示清空（仅对可空字段生效）。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    summary: str | None = Field(default=None, max_length=500)
    cover: str | None = Field(default=None, max_length=500)
    category_id: int | None = None
    tag_ids: list[int] | None = None
    status: ArticleStatus | None = None
    is_top: bool | None = None
    slug: str | None = Field(default=None, max_length=200)
    scheduled_at: datetime | None = None
    seo_title: str | None = Field(default=None, max_length=200)
    seo_description: str | None = Field(default=None, max_length=500)
    seo_keywords: str | None = Field(default=None, max_length=300)


class UpdateArticleStatusRequest(StrictModel):
    status: ArticleStatus


class BatchIdsRequest(StrictModel):
    ids: list[int] = Field(min_length=1)


# --------------------------------------------------------------------- categories


class CreateCategoryRequest(StrictModel):
    name: str = Field(min_length=1, max_length=50)
    slug: str = Field(default="", max_length=50)
    description: str = Field(default="", max_length=200)
    icon: str = Field(default="", max_length=10)
    sort_order: int = 0


class UpdateCategoryRequest(HasFieldMixin):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    slug: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=200)
    icon: str | None = Field(default=None, max_length=10)
    sort_order: int | None = None


class CreateTagRequest(StrictModel):
    name: str = Field(min_length=1, max_length=50)
    slug: str = Field(default="", max_length=50)


class UpdateTagRequest(HasFieldMixin):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    slug: str | None = Field(default=None, max_length=50)


# ----------------------------------------------------------------------- comments


class CreateCommentRequest(StrictModel):
    article_id: int = 0
    article_slug: str = ""
    content: str = Field(min_length=1, max_length=1000)
    nickname: str = Field(min_length=1, max_length=50)
    email: str = Field(default="", max_length=100)
    website: str = Field(default="", max_length=200)
    parent_id: int | None = None
    reply_to_id: int | None = None
    # 前端 JS 精确检测（能区分 Win11/Win10），不传则后端解析 UA 兜底
    os: str = ""
    os_version: str = ""
    browser: str = ""
    browser_version: str = ""

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = (v or "").strip()
        if v and ("@" not in v or "." not in v.split("@")[-1]):
            raise ValueError("邮箱格式错误")
        return v


class UpdateCommentStatusRequest(StrictModel):
    status: CommentStatus


# ----------------------------------------------------------------- daily question


class CreateDailyQuestionRequest(StrictModel):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=2000)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: int | None = Field(default=None, ge=0, le=2)


class UpdateDailyQuestionRequest(HasFieldMixin):
    question: str | None = Field(default=None, min_length=1)
    answer: str | None = None
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: int | None = Field(default=None, ge=0, le=2)


# --------------------------------------------------------------------- about page


class UpdateAboutPageRequest(StrictModel):
    title: str = ""
    subtitle: str = ""
    bio: str = ""
    skills: str = ""
    about_me: str = ""
    about_site: str = ""
    projects: str = ""
    contact_info: str = ""
    site_history: str = ""


# ------------------------------------------------------------------- view record


class RecordViewRequest(StrictModel):
    content_type: Literal["article", "daily_question"]
    content_id: int = Field(gt=0)


# ---------------------------------------------------------------- query parameters


class ArticleListQuery(StrictModel):
    page: int = 1
    page_size: int = 10
    category_id: int = 0
    tag: int = 0
    keyword: str = ""
    status: str = ""


class CommentListQuery(StrictModel):
    page: int = 1
    page_size: int = 10
    status: str = ""
    keyword: str = ""
    article_id: int = 0
    sort_by: str = "desc"


class DailyQuestionListQuery(StrictModel):
    page: int = 1
    page_size: int = 10
    status: int | None = None
    keyword: str = ""
    date: str = ""


class AuditLogListQuery(StrictModel):
    page: int = 1
    page_size: int = 20
    action: str = ""
    target_type: str = ""
    start_date: str = ""
    end_date: str = ""


def collect_present(data: dict[str, Any]) -> set[str]:
    return set(data.keys())
