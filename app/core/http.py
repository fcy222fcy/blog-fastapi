"""客户端 IP 提取。

生产环境前面有 Nginx，`request.client.host` 会退化成 127.0.0.1。
这里优先读 `X-Real-IP`，其次 `X-Forwarded-For` 第一段——与 Go 版配置了
TrustedProxies 之后的 `ctx.ClientIP()` 行为一致。

⚠️ 只应该在反向代理已经覆写这两个头的前提下依赖它。若服务直接暴露公网，
客户端可以伪造这两个头来刷点赞，因此在 Nginx 侧必须用
`proxy_set_header X-Real-IP $remote_addr;` 覆盖而不是透传。
"""

from __future__ import annotations

from fastapi import Request


def client_ip(request: Request) -> str:
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""
