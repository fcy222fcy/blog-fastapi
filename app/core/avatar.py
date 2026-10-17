"""头像地址生成。

复刻 Go 版 pkg/gravatar：QQ 邮箱优先走 qlogo.cn 官方头像（尺寸需映射到
平台支持的 40/100/140/240/640），其余邮箱走 Gravatar 的 identicon 默认图。
"""

from __future__ import annotations

import hashlib
import re

_QQ_EMAIL_RE = re.compile(r"^(\d+)@(?:vip\.)?qq\.com$")
_QQ_SUPPORTED_SIZES = (40, 100, 140, 240, 640)

DEFAULT_AVATAR_TYPE = "identicon"


def _normalize_qq_size(size: int) -> int:
    if size <= 0:
        return 100
    for supported in _QQ_SUPPORTED_SIZES:
        if supported >= size:
            return supported
    return _QQ_SUPPORTED_SIZES[-1]


def qq_avatar_url(qq_number: str, size: int = 100) -> str:
    number = (qq_number or "").strip()
    if not number:
        return ""
    return f"https://q1.qlogo.cn/g?b=qq&nk={number}&s={_normalize_qq_size(size)}"


def gravatar_url(email: str, size: int = 80) -> str:
    normalized = (email or "").strip().lower()
    if not normalized:
        return ""
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()
    capped = min(size if size > 0 else 80, 2048)
    return (
        f"https://www.gravatar.com/avatar/{digest}"
        f"?s={capped}&d={DEFAULT_AVATAR_TYPE}&r=g"
    )


def avatar_url_by_email(email: str | None, size: int = 80) -> str:
    """QQ 邮箱 → QQ 官方头像；其余邮箱 → Gravatar。"""
    normalized = (email or "").strip().lower()
    if not normalized:
        return ""
    match = _QQ_EMAIL_RE.match(normalized)
    if match:
        url = qq_avatar_url(match.group(1), size)
        if url:
            return url
    return gravatar_url(normalized, size)
