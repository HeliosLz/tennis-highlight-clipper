"""Upload / media storage helpers."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from .config import CLIPS_DIR, EXPORTS_DIR, THUMBS_DIR, UPLOAD_DIR

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


async def save_upload(file: UploadFile) -> tuple[str, Path]:
    """Persist an uploaded video, returning (video_id, path)."""
    vid = new_id()
    ext = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    if ext not in VIDEO_EXTS:
        ext = ".mp4"
    dest = UPLOAD_DIR / f"{vid}{ext}"
    with dest.open("wb") as fh:
        while chunk := await file.read(8 * 1024 * 1024):
            fh.write(chunk)
    return vid, dest


def clip_path(video_id: str, clip_id: str) -> Path:
    return CLIPS_DIR / f"{video_id}_{clip_id}.mp4"


def thumb_path(video_id: str, clip_id: str) -> Path:
    return THUMBS_DIR / f"{video_id}_{clip_id}.jpg"


def export_path(video_id: str, export_id: str) -> Path:
    return EXPORTS_DIR / f"{video_id}_{export_id}.mp4"


def delete_media(video_id: str, clip_ids: list[str] | None = None) -> None:
    """Remove all generated media for a video (or only listed clips)."""
    targets = clip_ids or []
    for cid in targets:
        for p in (clip_path(video_id, cid), thumb_path(video_id, cid)):
            p.unlink(missing_ok=True)
    if clip_ids is None:
        for pattern in (f"{video_id}_*.mp4", f"{video_id}_*.jpg"):
            for p in CLIPS_DIR.glob(pattern):
                p.unlink(missing_ok=True)
            for p in THUMBS_DIR.glob(pattern):
                p.unlink(missing_ok=True)
        for p in UPLOAD_DIR.glob(f"{video_id}.*"):
            p.unlink(missing_ok=True)
        for p in EXPORTS_DIR.glob(f"{video_id}_*"):
            p.unlink(missing_ok=True)
