"""In-process background job registry (single-user local app)."""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable


class Job:
    def __init__(self, kind: str, video_id: str):
        self.id = uuid.uuid4().hex[:10]
        self.kind = kind
        self.video_id = video_id
        self.status = "queued"   # queued | running | done | failed
        self.stage = ""
        self.progress = 0.0
        self.message = ""
        self.result = None
        self.error = None
        self.created = time.time()
        self._lock = threading.Lock()

    def update(self, stage: str, progress: float, message: str):
        with self._lock:
            self.stage = stage
            self.progress = round(float(progress), 4)
            self.message = message

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "id": self.id, "kind": self.kind, "video_id": self.video_id,
                "status": self.status, "stage": self.stage,
                "progress": self.progress, "message": self.message,
                "result": self.result, "error": self.error,
            }


class JobManager:
    def __init__(self, workers: int = 2):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers)

    def submit(self, kind: str, video_id: str, fn: Callable[[Job], object]) -> Job:
        job = Job(kind, video_id)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[Job], object]):
        try:
            job.status = "running"
            job.result = fn(job)
            job.status = "done"
            job.update("", 1.0, "done")
        except Exception as e:  # noqa: BLE001
            job.status = "failed"
            job.error = str(e)
            job.message = str(e)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def prune(self, max_age_sec: float = 3600.0):
        now = time.time()
        with self._lock:
            stale = [j for j in self._jobs.values()
                     if j.status in ("done", "failed") and now - j.created > max_age_sec]
            for j in stale:
                self._jobs.pop(j.id, None)


manager = JobManager()
