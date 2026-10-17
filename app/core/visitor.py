"""访客身份派生（用于浏览量按天去重）。

复刻 Go 版 pkg/visitor.DeriveKey：
- 前端传了合法 UUID 的 X-Visitor-ID → 用 `anonymous:<uuid>`
- 否则退化为 `ip:<client_ip>`
- 再用 JWT_SECRET 做 HMAC-SHA256，库里只存 64 位 hex 指纹，不落原始身份
"""

from __future__ import annotations

import hashlib
import hmac
import re

_ANON_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class VisitorIdentityError(ValueError):
    """既没有合法匿名 ID 也没有 IP，无法识别访客。"""


def derive_key(secret: str, anonymous_id: str | None, client_ip: str | None) -> str:
    if not (secret or "").strip():
        raise VisitorIdentityError("visitor hash secret is required")

    identity = ""
    anon = (anonymous_id or "").strip()
    ip = (client_ip or "").strip()
    if anon and _ANON_ID_RE.match(anon):
        identity = f"anonymous:{anon.lower()}"
    elif ip:
        identity = f"ip:{ip}"
    if not identity:
        raise VisitorIdentityError("visitor identity is required")

    return hmac.new(secret.encode("utf-8"), identity.encode("utf-8"), hashlib.sha256).hexdigest()
