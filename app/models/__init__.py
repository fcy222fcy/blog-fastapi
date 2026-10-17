"""模型导出。

集中导入保证 SQLAlchemy 的 metadata 在被 `create_all` 使用之前已经注册了
全部表与关系；service 层从这里取模型，不直接依赖具体模块文件。
"""

from app.models.about_page import AboutPage
from app.models.article import (
    Article,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    STATUS_SCHEDULED,
    VALID_STATUSES,
)
from app.models.audit import (
    CONTENT_TYPE_ARTICLE,
    CONTENT_TYPE_DAILY_QUESTION,
    SUPPORTED_CONTENT_TYPES,
    AuditLog,
    ContentViewEvent,
    Media,
    VisitLog,
)
from app.models.comment import (
    Comment,
    CommentLikeLog,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    VALID_STATUSES as COMMENT_VALID_STATUSES,
)
from app.models.daily_question import (
    DailyQuestion,
    DailyQuestionLikeLog,
    STATUS_DISABLED as DQ_STATUS_DISABLED,
    STATUS_PUBLISHED as DQ_STATUS_PUBLISHED,
    STATUS_SCHEDULED as DQ_STATUS_SCHEDULED,
)
from app.models.taxonomy import ArticleTag, Category, Tag
from app.models.user import User

__all__ = [
    "AboutPage",
    "Article",
    "ArticleTag",
    "AuditLog",
    "Category",
    "Comment",
    "CommentLikeLog",
    "ContentViewEvent",
    "DailyQuestion",
    "DailyQuestionLikeLog",
    "Media",
    "Tag",
    "User",
    "VisitLog",
    "STATUS_DRAFT",
    "STATUS_PUBLISHED",
    "STATUS_SCHEDULED",
    "VALID_STATUSES",
    "COMMENT_VALID_STATUSES",
    "STATUS_APPROVED",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "DQ_STATUS_DISABLED",
    "DQ_STATUS_PUBLISHED",
    "DQ_STATUS_SCHEDULED",
    "CONTENT_TYPE_ARTICLE",
    "CONTENT_TYPE_DAILY_QUESTION",
    "SUPPORTED_CONTENT_TYPES",
]
