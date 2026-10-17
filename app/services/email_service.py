"""邮件通知（可选能力）。

Go 版用 SMTP 发两种通知：新评论通知博主、回复通知被回复者。
这里保留同样的两个入口，但发信全程在后台线程，且**任何失败都只记日志**——
评论已经落库了，邮件发不出去不该让接口报错。

未配置 `EMAIL_HOST` 时直接短路返回，本地开发无需任何邮件服务。
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from app.core.config import settings

logger = logging.getLogger("blog.service.email")


def _enabled() -> bool:
    return bool(settings.email_host and settings.email_user and settings.email_password)


def _send_sync(to_email: str, subject: str, html: str) -> None:
    message = MIMEText(html, "html", "utf-8")
    message["Subject"] = Header(subject, "utf-8")
    message["From"] = formataddr((settings.email_from, settings.email_user))
    message["To"] = to_email

    # 465 走 SSL，其余端口按 STARTTLS 处理（与常见企业邮箱配置一致）
    if settings.email_port == 465:
        server = smtplib.SMTP_SSL(settings.email_host, settings.email_port, timeout=10)
    else:
        server = smtplib.SMTP(settings.email_host, settings.email_port, timeout=10)
        try:
            server.starttls()
        except smtplib.SMTPException:
            pass
    with server:
        server.login(settings.email_user, settings.email_password)
        server.sendmail(settings.email_user, [to_email], message.as_string())


async def _send(to_email: str, subject: str, html: str) -> None:
    if not _enabled() or not to_email:
        return
    try:
        await asyncio.to_thread(_send_sync, to_email, subject, html)
        logger.info("邮件发送成功 to=%s subject=%s", to_email, subject)
    except Exception as exc:  # noqa: BLE001 - 通知失败不影响主流程
        logger.warning("邮件发送失败 to=%s: %s", to_email, exc)


def _base_url() -> str:
    return "https://blog.fcyan.xyz"


async def notify_new_comment(
    comment, article_title: str, article_slug: str, target_email: str | None
) -> None:
    """新评论 / 回复通知。"""
    link = f"{_base_url()}/#/post/{article_slug}"
    snippet = (comment.content or "")[:500]

    if target_email:
        html = (
            f"<p><strong>{comment.nickname}</strong> 回复了你的评论：</p>"
            f"<blockquote>{snippet}</blockquote>"
            f'<p>文章：<a href="{link}">{article_title}</a></p>'
        )
        await _send(target_email, f"有人回复了你在《{article_title}》下的评论", html)
        return

    if not settings.email_from_email:
        logger.debug("博主邮箱未配置，跳过新评论通知")
        return

    html = (
        f"<p>你的博客收到一条新评论：</p>"
        f"<blockquote>{snippet}</blockquote>"
        f"<p>来自：{comment.nickname}（{comment.email or '未留邮箱'}）</p>"
        f'<p>文章：<a href="{link}">{article_title}</a></p>'
    )
    await _send(settings.email_from_email, f"《{article_title}》有新评论", html)
