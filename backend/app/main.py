"""FastAPI application: upload, analyze, clips, export."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import DATA_DIR, UPLOAD_DIR
from .jobs import manager
from .pipeline import (
    delete_video_meta, load_video_meta, run_analysis, run_export, save_video_meta,
)
from .storage import delete_media, new_id, save_upload

app = FastAPI(title="Tennis Highlight Clipper")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=DATA_DIR), name="media")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/videos")
async def upload_video(file: UploadFile = File(...)):
    video_id, path = await save_upload(file)
    entry = {
        "id": video_id,
        "filename": file.filename,
        "path": str(path),
        "status": "uploaded",
        "created": time.time(),
        "clips": [],
        "exports": [],
        "video_url": "/media/uploads/" + path.name,
    }
    save_video_meta(entry)
    return entry


class AnalyzeBody(BaseModel):
    pass


@app.post("/api/videos/{video_id}/analyze")
def start_analysis(video_id: str):
    meta = load_video_meta(video_id)
    if not meta:
        raise HTTPException(404, "video not found")
    src = Path(meta["path"])
    if not src.exists():
        raise HTTPException(404, "source file missing")
    job = manager.submit("analyze", video_id, lambda j: run_analysis(j, video_id, src))
    return {"job_id": job.id}


class ExportBody(BaseModel):
    clip_ids: list[str]


@app.post("/api/videos/{video_id}/export")
def start_export(video_id: str, body: ExportBody):
    meta = load_video_meta(video_id)
    if not meta:
        raise HTTPException(404, "video not found")
    job = manager.submit("export", video_id,
                         lambda j: run_export(j, video_id, body.clip_ids))
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job.to_dict()


@app.get("/api/videos/{video_id}")
def video_meta(video_id: str):
    meta = load_video_meta(video_id)
    if not meta:
        raise HTTPException(404, "video not found")
    return {k: v for k, v in meta.items() if k != "path"}


@app.get("/api/videos")
def list_videos():
    import json
    meta_file = DATA_DIR / "meta.json"
    if not meta_file.exists():
        return []
    try:
        meta = json.loads(meta_file.read_text())
    except Exception:
        return []
    return [{k: v for k, v in e.items() if k != "path"}
            for e in sorted(meta.values(), key=lambda x: x.get("created", 0), reverse=True)]


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: str):
    meta = load_video_meta(video_id)
    if not meta:
        raise HTTPException(404, "video not found")
    clip_ids = [c["id"] for c in meta.get("clips", [])]
    delete_media(video_id, clip_ids)
    delete_media(video_id)
    delete_video_meta(video_id)
    return {"ok": True}
