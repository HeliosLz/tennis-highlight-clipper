"""Analysis + export pipelines wiring detector, video tools and storage."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .config import (
    CLIP_PAD_END, CLIP_PAD_START, DATA_DIR,
)
from .detector import RallyDetector
from .storage import (
    clip_path, export_path, new_id, thumb_path,
)
from .video import concat_clips, cut_clip, make_thumbnail, probe

META_FILE = DATA_DIR / "meta.json"
_meta_lock = threading.Lock()


def _load_meta() -> dict:
    if META_FILE.exists():
        try:
            return json.loads(META_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_meta(meta: dict) -> None:
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2))


def load_video_meta(video_id: str) -> dict | None:
    with _meta_lock:
        return _load_meta().get(video_id)


def save_video_meta(entry: dict) -> None:
    with _meta_lock:
        meta = _load_meta()
        meta[entry["id"]] = entry
        _save_meta(meta)


def delete_video_meta(video_id: str) -> None:
    with _meta_lock:
        meta = _load_meta()
        meta.pop(video_id, None)
        _save_meta(meta)


def run_analysis(job, video_id: str, src: Path) -> dict:
    """Full pipeline: probe -> detect rallies -> cut clips -> thumbnails."""
    media = probe(src)
    if media["duration"] <= 0:
        raise RuntimeError("无法读取视频时长，文件可能已损坏")

    def on_progress(stage: str, frac: float, msg: str):
        # detect stage covers 0..0.70 of the whole job
        job.update(stage, frac * 0.70, msg)

    detector = RallyDetector(progress=on_progress)
    detector.load_model()
    rallies = detector.analyze(src, media["duration"])

    clips: list[dict] = []
    total = max(1, len(rallies))
    for i, r in enumerate(rallies):
        start = max(0.0, r.start - CLIP_PAD_START)
        end = min(media["duration"], r.end + CLIP_PAD_END)
        if end - start < 1.0:
            continue
        cid = f"c{i:03d}"
        job.update("cut", 0.70 + 0.25 * (i / total), "cutting clips %d/%d" % (i + 1, total))
        cut_clip(src, start, end, clip_path(video_id, cid))
        make_thumbnail(clip_path(video_id, cid), 0.8, thumb_path(video_id, cid))
        clips.append({
            "id": cid,
            "start": round(start, 2),
            "end": round(end, 2),
            "duration": round(end - start, 2),
            "approx_hits": int(r.approx_hits),
            "video_url": "/media/clips/%s_%s.mp4" % (video_id, cid),
            "thumb_url": "/media/thumbs/%s_%s.jpg" % (video_id, cid),
        })
        job.update("cut", 0.70 + 0.25 * ((i + 1) / total), "clip %d/%d" % (i + 1, total))

    prev = load_video_meta(video_id) or {}
    entry = {
        "id": video_id,
        "filename": prev.get("filename") or src.name,
        "created": prev.get("created", time.time()),
        "duration": round(media["duration"], 2),
        "fps": round(media["fps"], 2),
        "width": media["width"],
        "height": media["height"],
        "status": "ready",
        "clips": clips,
        "exports": prev.get("exports", []),
        "video_url": "/media/uploads/" + src.name,
    }
    save_video_meta(entry)
    job.update("", 0.95, "done, %d clips" % len(clips))
    return {"clips": len(clips), "duration": entry["duration"]}


def run_export(job, video_id: str, clip_ids: list[str]) -> dict:
    meta = load_video_meta(video_id)
    if not meta:
        raise RuntimeError("video not found")
    known = {c["id"]: c for c in meta.get("clips", [])}
    paths = []
    for cid in clip_ids:
        if cid in known:
            p = clip_path(video_id, cid)
            if p.exists():
                paths.append(p)
    if not paths:
        raise RuntimeError("no valid clips selected")
    eid = new_id()
    job.update("export", 0.5, "merging %d clips" % len(paths))
    concat_clips(paths, export_path(video_id, eid))
    meta.setdefault("exports", []).append({
        "id": eid,
        "clips": clip_ids,
        "url": "/media/exports/%s_%s.mp4" % (video_id, eid),
    })
    save_video_meta(meta)
    return {"export_id": eid, "url": meta["exports"][-1]["url"]}
