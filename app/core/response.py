"""统一响应封装。

Go 版所有接口都返回 {code, message, data}，业务失败也走同一个信封
（HTTP 状态码按错误码区间映射）。这里保持字节级一致的字段名与顺序。
"""

from __future__ import annotations

from typing import Any, Generic, Sequence, TypeVar

from fastapi.responses import JSONResponse

from app.core.errors import CODE_SUCCESS

T = TypeVar("T")


def envelope(code: int = CODE_SUCCESS, message: str = "success", data: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "data": data}


def success(data: Any = None, message: str = "success") -> dict[str, Any]:
    return envelope(CODE_SUCCESS, message, data)


def json_response(status_code: int, code: int, message: str, data: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=envelope(code, message, data))


class PageResult(Generic[T]):
    """分页结果容器。

    注意字段名是 total_page / size（与 Go 版 PageResponse 一致），
    前端直接读 res.data.total_page，不能改成 totalPage。
    """

    __slots__ = ("items", "total", "page", "size")

    def __init__(self, items: Sequence[T], total: int, page: int, size: int) -> None:
        self.items = list(items)
        self.total = int(total)
        self.page = page
        self.size = size

    @property
    def total_page(self) -> int:
        if self.size <= 0:
            return 0
        pages = self.total // self.size
        if self.total % self.size > 0:
            pages += 1
        return pages

    def to_dict(self) -> dict[str, Any]:
        return {
            "list": self.items,
            "total": self.total,
            "page": self.page,
            "size": self.size,
            "total_page": self.total_page,
        }


def page_response(items: Sequence[T], total: int, page: int, size: int) -> dict[str, Any]:
    return PageResult(items, total, page, size).to_dict()


def normalize_page(page: int | None, page_size: int | None, default_size: int = 10, max_size: int = 100) -> tuple[int, int]:
    """分页参数归一化，规则与 Go 版 PageRequest.GetOffset/GetPageSize 一致。"""
    p = page if page and page > 0 else 1
    s = page_size if page_size and page_size > 0 else default_size
    if s > max_size:
        s = max_size
    return p, s
