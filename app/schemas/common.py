"""Pydantic 公共基类与字段类型。

时间字段刻意不用 pydantic 默认的 ISO 格式，而是输出带 `+08:00` 的 RFC3339
字符串 —— 与 Go 的 `time.Time.MarshalJSON` 对齐。前端 `new Date(str)` 在两边
拿到的都是同一时刻，不会出现 8 小时漂移。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, PlainSerializer

CST = timezone(timedelta(hours=8))


def format_datetime(value: datetime) -> str:
    """naive 时间按东八区解释后输出 RFC3339，带时区的原样规整。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=CST)
    else:
        value = value.astimezone(CST)
    return value.isoformat(timespec="seconds")


DateTimeStr = Annotated[datetime, PlainSerializer(format_datetime, return_type=str)]


class APIModel(BaseModel):
    """所有响应模型的基类：允许从 ORM 对象直接构造。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class StrictModel(BaseModel):
    """所有请求模型的基类：忽略未声明的多余字段。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, str_strip_whitespace=True)


def optional(value: Any) -> Any:
    """把 ORM 里可能为 None 的文本列规整成空串，避免前端拿到 null 后渲染出 'null'。"""
    return "" if value is None else value
