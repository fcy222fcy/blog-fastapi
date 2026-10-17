"""Slug 生成与 Markdown 文本处理。

复刻 Go 版 pkg/slug.Generate 与 service/article_service.go 里的
generateSlug / calculateReadingTime / stripMarkdown / buildSearchSnippet。

这几段逻辑决定了：中文标题如何退化为时间戳 slug、阅读时长怎么算、
搜索结果的高亮片段长什么样。行为必须与 Go 版一致，否则同一篇文章
在两个实现里会生成不同的 URL。
"""

from __future__ import annotations

import re
import time

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]+")
_MULTI_HYPHEN = re.compile(r"-{2,}")
_WS = re.compile(r"\s+")


def generate(name: str) -> str:
    """按名称生成 slug；纯非 ASCII（如纯中文）退化为时间戳。"""
    if not name:
        return _timestamp_slug()
    lowered = name.lower()
    ascii_only = "".join(ch for ch in lowered if 32 <= ord(ch) <= 126)
    if not ascii_only:
        return _timestamp_slug()
    slug = _NON_ALNUM.sub("-", ascii_only).strip("-")
    slug = _MULTI_HYPHEN.sub("-", slug)
    return slug or _timestamp_slug()


def _timestamp_slug() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def generate_article_slug(title: str) -> str:
    """文章 slug：只保留 ASCII 字母数字，纯中文标题用 post-<unix> 兜底。

    注意与 pkg/slug.Generate 的差异（Go 版文章走的是自己那份实现）：
    兜底格式是 `post-<unix>` 而不是 `YYYYMMDDHHmmss`。历史数据里两种都存在，
    所以这里按模块分别复刻，不能合并。
    """
    slug = (title or "").lower()
    slug = "".join(ch for ch in slug if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in (" ", "-"))
    slug = slug.strip()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    if not slug:
        slug = f"post-{int(time.time())}"
    return slug[:200]


_MD_REPLACEMENTS = ("#", "*", "`", ">", "[", "]", "(", ")", "!", "-")


def calculate_reading_time(content: str | None) -> int:
    """阅读时长（分钟）：中文 ~400 字/分钟，英文 ~200 词/分钟。至少 1 分钟。"""
    if not content:
        return 1
    cleaned = content
    for token in _MD_REPLACEMENTS:
        cleaned = cleaned.replace(token, "")
    cleaned = cleaned.strip()
    if not cleaned:
        return 1
    rune_count = len(cleaned)
    word_count = len(cleaned.split())
    minutes = rune_count // 400 + word_count // 200
    return minutes if minutes >= 1 else 1


# stripMarkdown 用的正则：从外向内逐条剥离，不用反向引用
_RE_FENCED = re.compile(r"```[^\n]*\n?(.*?)```", re.S)
_RE_INLINE_CODE = re.compile(r"`([^`]*)`")
_RE_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_RE_HTML_TAG = re.compile(r"<[^>]+>")
_RE_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_RE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_RE_LINE_PREFIX = re.compile(r"(?m)^\s{0,3}(#{1,6}\s*|>\s*|[-*+]\s+|\d+\.\s+)")
_RE_TRIPLE_STAR = re.compile(r"\*\*\*([^*]+?)\*\*\*")
_RE_DOUBLE_STAR = re.compile(r"\*\*([^*]+?)\*\*")
_RE_SINGLE_STAR = re.compile(r"(^|[^*])\*([^*\n]+?)\*([^*]|$)")
_RE_TRIPLE_TILDE = re.compile(r"~~~([^~]+?)~~~")
_RE_DOUBLE_TILDE = re.compile(r"~~([^~]+?)~~")
_RE_TRIPLE_UNDER = re.compile(r"___([^_]+?)___")
_RE_DOUBLE_UNDER = re.compile(r"__([^_]+?)__")
_RE_SINGLE_UNDER = re.compile(r"(^|[^_\w])_([^_\n]+?)_([^_\w]|$)")


def strip_markdown(src: str | None) -> str:
    """粗粒度清除 Markdown 标记，只留纯文本（用于搜索片段）。"""
    if not src:
        return ""
    s = _RE_FENCED.sub(r" \1 ", src)
    s = _RE_INLINE_CODE.sub(r" \1 ", s)
    s = _RE_HTML_COMMENT.sub("", s)
    s = _RE_HTML_TAG.sub("", s)
    s = _RE_IMAGE.sub(r"\1", s)
    s = _RE_LINK.sub(r"\1", s)
    s = _RE_LINE_PREFIX.sub("", s)
    while _RE_TRIPLE_STAR.search(s):
        s = _RE_TRIPLE_STAR.sub(r"\1", s)
    while _RE_DOUBLE_STAR.search(s):
        s = _RE_DOUBLE_STAR.sub(r"\1", s)
    while _RE_SINGLE_STAR.search(s):
        s = _RE_SINGLE_STAR.sub(r"\1\2\3", s)
    while _RE_TRIPLE_TILDE.search(s):
        s = _RE_TRIPLE_TILDE.sub(r"\1", s)
    while _RE_DOUBLE_TILDE.search(s):
        s = _RE_DOUBLE_TILDE.sub(r"\1", s)
    while _RE_TRIPLE_UNDER.search(s):
        s = _RE_TRIPLE_UNDER.sub(r"\1", s)
    while _RE_DOUBLE_UNDER.search(s):
        s = _RE_DOUBLE_UNDER.sub(r"\1", s)
    while _RE_SINGLE_UNDER.search(s):
        s = _RE_SINGLE_UNDER.sub(r"\1\2\3", s)
    s = s.replace("*", "").replace("~", "")
    s = _WS.sub(" ", s)
    return s.strip()


def _keyword_regex(keyword: str) -> re.Pattern[str] | None:
    words = [w for w in keyword.split() if w]
    if not words:
        return None
    return re.compile("(" + "|".join(re.escape(w) for w in words) + ")", re.IGNORECASE)


def build_search_snippet(content: str | None, summary: str | None, keyword: str, radius: int = 45) -> str:
    """抽取包含关键词的上下文片段，前后用 [...] 省略。

    如果 Summary 本身命中关键词则返回空串，让前端直接展示 Summary。
    """
    if not keyword:
        return ""
    kw_lower = keyword.lower()
    sum_lower = (summary or "").lower()
    for word in kw_lower.split():
        if word and word in sum_lower:
            return ""
    clean = strip_markdown(content)
    if not clean:
        return ""
    pattern = _keyword_regex(keyword)
    if pattern is None:
        return ""
    match = pattern.search(clean)
    if match is None:
        return ""
    start, end = match.start(), match.end()
    left = max(0, start - radius)
    right = min(len(clean), end + radius)
    segment = clean[left:right].strip()
    if not segment:
        return ""
    prefix = "[...]" if left > 0 else ""
    suffix = "[...]" if right < len(clean) else ""
    return f"{prefix}{segment}{suffix}"
