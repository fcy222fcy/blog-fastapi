"""业务错误码与异常。

完全复刻 Go 版 pkg/errors/code.go：同一套错误码、同一套文案、同一套
「错误码区间 → HTTP 状态码」的映射规则，保证前端按 code 处理的分支不失效。
"""

from __future__ import annotations

from typing import Any

# 成功
CODE_SUCCESS = 0

# 通用错误
CODE_BAD_REQUEST = 400
CODE_UNAUTHORIZED = 401
CODE_FORBIDDEN = 403
CODE_NOT_FOUND = 404
CODE_INTERNAL_SERVER = 500

# 用户/认证业务错误 (1000+)
CODE_USER_NOT_FOUND = 1001
CODE_USER_ALREADY_EXISTS = 1002
CODE_PASSWORD_INCORRECT = 1003
CODE_TOKEN_EXPIRED = 1004
CODE_TOKEN_INVALID = 1005
CODE_ACCOUNT_DISABLED = 1006

# 参数错误 (2000+)
CODE_INVALID_PARAMS = 2001
CODE_MISSING_REQUIRED = 2002
CODE_INVALID_EMAIL = 2003
CODE_INVALID_PHONE = 2004
CODE_PASSWORD_TOO_SHORT = 2005
CODE_USERNAME_TOO_SHORT = 2006

# 资源错误 (3000+)
CODE_ARTICLE_NOT_FOUND = 3001
CODE_CATEGORY_NOT_FOUND = 3002
CODE_TAG_NOT_FOUND = 3003
CODE_COMMENT_NOT_FOUND = 3004
CODE_DAILY_QUESTION_NOT_FOUND = 3006
CODE_MEDIA_NOT_FOUND = 3007
CODE_PAGE_NOT_FOUND = 3008
CODE_RECORD_NOT_FOUND = 3009

# 业务错误 (4000+)
CODE_CATEGORY_NAME_EXISTS = 4001
CODE_CATEGORY_HAS_ARTICLES = 4002
CODE_TAG_NAME_EXISTS = 4003
CODE_TAG_HAS_ARTICLES = 4004
CODE_DAILY_QUESTION_DATE_EXISTS = 4005
CODE_COMMENT_ALREADY_LIKED = 4006
CODE_COMMENT_NOT_LIKED = 4007
CODE_ALREADY_LIKED = 4008

CODE_MESSAGES: dict[int, str] = {
    CODE_SUCCESS: "成功",
    CODE_BAD_REQUEST: "请求错误",
    CODE_UNAUTHORIZED: "未授权",
    CODE_FORBIDDEN: "禁止访问",
    CODE_NOT_FOUND: "资源不存在",
    CODE_INTERNAL_SERVER: "服务器内部错误",
    CODE_USER_NOT_FOUND: "用户不存在",
    CODE_USER_ALREADY_EXISTS: "用户已存在",
    CODE_PASSWORD_INCORRECT: "密码错误",
    CODE_TOKEN_EXPIRED: "Token 已过期",
    CODE_TOKEN_INVALID: "Token 无效",
    CODE_ACCOUNT_DISABLED: "账户已禁用",
    CODE_INVALID_PARAMS: "参数错误",
    CODE_MISSING_REQUIRED: "缺少必填参数",
    CODE_INVALID_EMAIL: "邮箱格式错误",
    CODE_INVALID_PHONE: "手机号格式错误",
    CODE_PASSWORD_TOO_SHORT: "密码长度不足",
    CODE_USERNAME_TOO_SHORT: "用户名长度不足",
    CODE_ARTICLE_NOT_FOUND: "文章不存在",
    CODE_CATEGORY_NOT_FOUND: "分类不存在",
    CODE_TAG_NOT_FOUND: "标签不存在",
    CODE_COMMENT_NOT_FOUND: "评论不存在",
    CODE_DAILY_QUESTION_NOT_FOUND: "每日一问不存在",
    CODE_MEDIA_NOT_FOUND: "媒体文件不存在",
    CODE_PAGE_NOT_FOUND: "页面不存在",
    CODE_RECORD_NOT_FOUND: "记录不存在",
    CODE_COMMENT_ALREADY_LIKED: "您已经点赞过了",
    CODE_COMMENT_NOT_LIKED: "您还没有点赞过",
    CODE_ALREADY_LIKED: "您已经点赞过了",
    # 以下 5 条是相对 Go 版的**改进**：原项目 CodeMessages 表里漏了 4001-4005，
    # 导致重名分类/标签这类错误直接回 "未知错误"，后台只能看到一句无意义的提示。
    # 前端是按 code 分支判断的，补文案不会影响任何已有逻辑。
    CODE_CATEGORY_NAME_EXISTS: "分类名称已存在",
    CODE_CATEGORY_HAS_ARTICLES: "该分类下还有文章，无法删除",
    CODE_TAG_NAME_EXISTS: "标签名称已存在",
    CODE_TAG_HAS_ARTICLES: "该标签下还有文章，无法删除",
    CODE_DAILY_QUESTION_DATE_EXISTS: "该日期已存在问题",
}


def get_message(code: int) -> str:
    return CODE_MESSAGES.get(code, "未知错误")


def http_status_for(code: int) -> int:
    """错误码区间 → HTTP 状态码，与 Go 版 response.BizError 的 switch 完全一致。"""
    if 1000 <= code < 2000:
        return 401
    if 2000 <= code < 3000:
        return 400
    if 3000 <= code < 4000:
        return 404
    if 4000 <= code < 5000:
        return 400
    return 200


class BizError(Exception):
    """业务异常。携带与 Go 版一致的 code，由全局异常处理器转换成统一响应体。

    `status` 用于少数需要显式指定 HTTP 状态码的场景（鉴权中间件返回 401/403，
    而不是错误码区间推导出的 200）。不传时按错误码区间推导。
    """

    def __init__(self, code: int, message: str | None = None, status: int | None = None) -> None:
        self.code = code
        self.message = message if message is not None else get_message(code)
        self._explicit_status = status
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        if self._explicit_status is not None:
            return self._explicit_status
        return http_status_for(self.code)


class RepoError(Exception):
    """仓库层通用异常，由上层转成 500 或对应业务错误。"""


class UnsupportedContentType(RepoError):
    """浏览量上报的 content_type 不合法。"""

    def __init__(self, value: Any = None) -> None:
        self.value = value
        super().__init__(f"unsupported content type: {value}")


class ViewTargetNotFound(RepoError):
    """浏览量上报的目标内容不存在。"""

    def __init__(self, content_type: Any = None, content_id: Any = None) -> None:
        self.content_type = content_type
        self.content_id = content_id
        super().__init__(f"view target not found: {content_type}/{content_id}")
