"""媒体文件路由（/api/v1/media）。

文件列表直接扫 `uploads/` 目录而不查数据库——与 Go 版一致，
因为这里的事实源是磁盘。`media` 表保留但只作为历史兼容，不参与读写。

上传限制：≤5MB，扩展名白名单，且非 PDF 时用文件头嗅探确认真的是图片
（防止把 .exe 改名成 .jpg 传上来）。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.deps import require_blogger
from app.core.errors import BizError, CODE_NOT_FOUND, CODE_INVALID_PARAMS
from app.core.response import success

router = APIRouter(prefix="/media", tags=["media"], dependencies=[Depends(require_blogger)])

ALLOWED_CATEGORIES = {"avatar", "article", "daily", "entertainment", "link", "common"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}
MAX_SIZE = 5 * 1024 * 1024

_MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}


def _normalize_category(value: str | None) -> str:
    cat = (value or "").strip().lower()
    return cat if cat in ALLOWED_CATEGORIES else "common"


def _mime_of(name: str) -> str:
    return _MIME_MAP.get(Path(name).suffix.lower(), "application/octet-stream")


def _detect_content_type(head: bytes) -> str:
    """按文件头判断真实类型，只关心是否图片（PDF 单独放行）。"""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF"):
        return "application/pdf"
    return "application/octet-stream"


@router.post("/upload")
async def upload(
    file: UploadFile = File(...), category: str = Form("common")
) -> dict:
    cat = _normalize_category(category)

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise BizError(CODE_INVALID_PARAMS, "不支持的文件类型")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise BizError(CODE_INVALID_PARAMS, "文件大小不能超过 5MB")

    detected = _detect_content_type(content[:512])
    if ext != ".pdf" and not detected.startswith("image/"):
        raise BizError(CODE_INVALID_PARAMS, "文件类型与内容不匹配")

    target_dir = settings.upload_path / cat
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{time.time_ns()}{ext}"
    (target_dir / filename).write_bytes(content)

    return success(
        {
            "url": f"/uploads/{cat}/{filename}",
            "category": cat,
            "filename": file.filename,
            "size": len(content),
        }
    )


@router.get("")
async def list_media(
    category: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    keyword: str = Query(""),
) -> dict:
    filter_cat = category.strip().lower()
    if filter_cat and filter_cat not in ALLOWED_CATEGORIES:
        filter_cat = ""

    base = settings.upload_path
    if not base.exists():
        # 注意这里返回的是 page_size 而不是 size：与 Go 版字段名保持一致
        return success({"list": [], "total": 0, "page": page, "page_size": page_size, "category": filter_cat})

    entries: list[dict] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        if "/" in rel:
            cat, name = rel.split("/", 1)
            cat = cat.lower()
            if cat not in ALLOWED_CATEGORIES:
                continue
        else:
            cat, name = "common", rel

        if filter_cat and cat != filter_cat:
            continue
        if keyword and keyword.lower() not in name.lower():
            continue

        stat = path.stat()
        entries.append(
            {
                "id": len(entries) + 1,
                "name": name,
                "category": cat,
                "url": f"/uploads/{rel}",
                "size": stat.st_size,
                "type": _mime_of(name),
                "modified": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime(stat.st_mtime)),
            }
        )

    total = len(entries)
    start = min((page - 1) * page_size, total)
    end = min(start + page_size, total)
    return success(
        {
            "list": entries[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
            "category": filter_cat,
        }
    )


@router.delete("/{filename:path}")
async def delete_media(filename: str, category: str = Query("")) -> dict:
    """删除文件。

    支持两种写法（与 Go 版兼容）：
    - 新格式：`?category=avatar` + 纯文件名
    - 旧格式：文件名里自带分类，如 `avatar/123.jpg`；裸文件名视为根目录旧文件
    """
    raw = (filename or "").strip()
    if not raw:
        raise BizError(CODE_INVALID_PARAMS, "文件名不能为空")

    query_cat = (category or "").strip()
    if not query_cat and "/" in raw:
        head, _, tail = raw.partition("/")
        rel = f"{_normalize_category(head)}/{tail}"
        name = tail
    elif query_cat:
        rel = f"{_normalize_category(query_cat)}/{raw}"
        name = raw
    else:
        rel = raw
        name = raw

    # 路径穿越防护：目录穿越、绝对路径、反斜杠一律拒绝
    if ".." in name or ".." in rel or rel.startswith("/") or "\\" in rel:
        raise BizError(CODE_INVALID_PARAMS, "非法文件名或分类")

    target = settings.upload_path / rel
    if not target.is_file():
        raise BizError(CODE_NOT_FOUND, "文件不存在")

    try:
        os.remove(target)
    except OSError as exc:
        raise BizError(500, "删除文件失败") from exc

    return success(None)
