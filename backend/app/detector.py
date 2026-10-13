"""YOLO-based tennis detection + rally (point) segmentation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .config import (
    ANALYSIS_FPS, BALL_PRESENT_RATIO, MAX_GAP_SEC, MIN_RALLY_SEC,
    REFINE_FPS, REFINE_WINDOW,
)
from .video import iter_frames

ProgressCb = Callable[[str, float, str], None]

PERSON_CLS = 0
BALL_CLS = 32
BALL_CONF = 0.10
PERSON_CONF = 0.30

TENNIS_MODELS = ["yolov8n.pt"]


@dataclass
class FrameObs:
    t: float
    ball: bool = False
    ball_x: float | None = None
    persons: int = 0
    person_boxes: list = field(default_factory=list)


@dataclass
class Rally:
    start: float
    end: float
    approx_hits: int = 0
    ball_ratio: float = 0.0


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a[:4]
    bx1, by1, bx2, by2 = b[:4]
    ix = max(0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


class RallyDetector:
    def __init__(self, progress: ProgressCb | None = None, device: str | None = None):
        self.progress = progress or (lambda *a: None)
        self.device = device or self._pick_device()
        self.model = None

    @staticmethod
    def _pick_device() -> str:
        try:
            import torch
            if torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"

    def load_model(self):
        from ultralytics import YOLO
        last_err = None
        for name in TENNIS_MODELS:
            try:
                self.model = YOLO(name)
                break
            except Exception as e:
                last_err = e
        if self.model is None:
            raise RuntimeError("unable to load detection model: " + str(last_err))
        self.progress("detect", 0.03, "model loaded")

    # ------------------------------------------------------------------ detect
    def _detect_batch(self, frames: list) -> list[FrameObs]:
        results = self.model.predict(
            frames, device=self.device, imgsz=1024, conf=0.05,
            classes=[PERSON_CLS, BALL_CLS], verbose=False, batch=8,
        )
        out: list[FrameObs] = []
        for r in results:
            boxes = r.boxes
            ball = False
            ball_conf = -1.0
            ball_x = None
            person_boxes: list[tuple] = []
            if boxes is not None and len(boxes):
                xyxy = boxes.xyxy.cpu().numpy()
                confs = boxes.conf.cpu().numpy()
                cls = boxes.cls.cpu().numpy()
                for i in range(len(boxes)):
                    if cls[i] == BALL_CLS and confs[i] >= BALL_CONF:
                        if not ball or confs[i] > ball_conf:
                            x1, y1, x2, y2 = xyxy[i]
                            ball, ball_x = True, float((x1 + x2) / 2)
                            ball_conf = float(confs[i])
                    elif cls[i] == PERSON_CLS and confs[i] >= PERSON_CONF:
                        person_boxes.append((*xyxy[i], float(confs[i])))
            person_boxes.sort(key=lambda b: b[4], reverse=True)
            distinct = []
            for b in person_boxes:
                if not any(_iou(b, d) > 0.6 for d in distinct):
                    distinct.append(b)
                if len(distinct) >= 2:
                    break
            out.append(FrameObs(t=0.0, ball=ball, ball_x=ball_x,
                                persons=len(distinct), person_boxes=distinct))
        return out

    def _coarse_pass(self, video_path: Path, duration: float) -> list[FrameObs]:
        obs: list[FrameObs] = []
        total = max(1.0, duration)
        self.progress("detect", 0.05, "extracting frames + detecting")
        batch: list = []
        times: list[float] = []
        for t, frame in iter_frames(video_path, ANALYSIS_FPS):
            batch.append(frame)
            times.append(t)
            if len(batch) >= 16:
                for ob, t0 in zip(self._detect_batch(batch), times):
                    ob.t = t0
                    obs.append(ob)
                batch.clear()
                times.clear()
                frac = min(1.0, obs[-1].t / total)
                self.progress("detect", 0.05 + 0.45 * frac,
                              "detecting %.0fs / %.0fs" % (obs[-1].t, total))
        if batch:
            for ob, t0 in zip(self._detect_batch(batch), times):
                ob.t = t0
                obs.append(ob)
        return obs

    # --------------------------------------------------------------- segment
    @staticmethod
    def _smooth(signal: list[bool], window: int = 3) -> list[bool]:
        n = len(signal)
        out = [False] * n
        for i in range(n):
            lo, hi = max(0, i - window // 2), min(n, i + window // 2 + 1)
            out[i] = any(signal[lo:hi])
        return out

    def _segment(self, obs: list[FrameObs]) -> list[tuple[float, float]]:
        if not obs:
            return []
        dt = 1.0 / ANALYSIS_FPS
        ball = self._smooth([o.ball for o in obs])
        runs: list[list[int]] = []
        cur: list[int] = []
        for i, b in enumerate(ball):
            if b:
                cur.append(i)
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        merged: list[list[int]] = []
        for run in runs:
            if merged and (run[0] - merged[-1][-1]) * dt <= MAX_GAP_SEC:
                merged[-1].extend(run)
            else:
                merged.append(run)
        segments: list[tuple[float, float]] = []
        for run in merged:
            dur = (run[-1] - run[0] + 1) * dt
            ratio = sum(1 for i in run if obs[i].ball) / len(run)
            if dur >= MIN_RALLY_SEC and ratio >= BALL_PRESENT_RATIO:
                segments.append((obs[run[0]].t, obs[run[-1]].t + dt))
        return segments

    def _refine(self, video_path: Path, seg: tuple[float, float]) -> list[list[float]]:
        """High-fps rescan of the window; return ball-sighting clusters (lists of timestamps)."""
        s0, e0 = seg
        lo = max(0.0, s0 - REFINE_WINDOW)
        hi = e0 + REFINE_WINDOW
        seen: list[float] = []
        batch: list = []
        times: list[float] = []
        for t, frame in iter_frames(video_path, REFINE_FPS, lo, hi):
            batch.append(frame)
            times.append(t)
            if len(batch) >= 32:
                for ob, tt in zip(self._detect_batch(batch), times):
                    if ob.ball:
                        seen.append(tt)
                batch.clear()
                times.clear()
        if batch:
            for ob, tt in zip(self._detect_batch(batch), times):
                if ob.ball:
                    seen.append(tt)
        if not seen:
            return []
        clusters: list[list[float]] = []
        for t in sorted(seen):
            if clusters and t - clusters[-1][-1] <= 1.2:
                clusters[-1].append(t)
            else:
                clusters.append([t])
        return [c for c in clusters if len(c) >= 3]

    @staticmethod
    def _group_clusters(clusters: list[list[float]], gap: float = 4.0) -> list[list[list[float]]]:
        """Group consecutive ball clusters separated by <= gap seconds of absence."""
        groups: list[list[list[float]]] = []
        cur: list[list[float]] = []
        for c in clusters:
            if cur and c[0] - cur[-1][-1] > gap:
                groups.append(cur)
                cur = []
            cur.append(c)
        if cur:
            groups.append(cur)
        return groups

    # ----------------------------------------------------------------- main
    def analyze(self, video_path: Path, duration: float) -> list[Rally]:
        self.progress("detect", 0.04, "starting analysis")
        obs = self._coarse_pass(video_path, duration)
        self.progress("detect", 0.50, "detection done, segmenting rallies")
        segments = self._segment(obs)
        rallies: list[Rally] = []
        total = max(1, len(segments))
        dt_ref = 1.0 / REFINE_FPS
        for i, seg in enumerate(segments):
            clusters = self._refine(video_path, seg)
            for group in self._group_clusters(clusters):
                first = group[0][0]
                last = group[-1][-1] + dt_ref
                if last - first < MIN_RALLY_SEC:
                    continue
                idx = [o for o in obs
                       if first - 0.5 <= o.t <= last + 0.5 and o.ball and o.ball_x is not None]
                rallies.append(Rally(start=first, end=last,
                                     approx_hits=self._count_hits(idx)))
            self.progress("detect", 0.50 + 0.20 * ((i + 1) / total),
                          "refining boundaries %d/%d" % (i + 1, total))
        rallies.sort(key=lambda r: r.start)
        merged: list[Rally] = []
        for r in rallies:
            if merged and r.start - merged[-1].end <= MAX_GAP_SEC * 0.4:
                merged[-1].end = max(merged[-1].end, r.end)
                merged[-1].approx_hits += r.approx_hits
            else:
                merged.append(r)
        return merged

    @staticmethod
    def _count_hits(obs: list[FrameObs]) -> int:
        if len(obs) < 6:
            return 0
        xs = [o.ball_x for o in obs if o.ball_x is not None]
        if not xs:
            return 0
        jumps = [abs(b - a) for a, b in zip(xs, xs[1:])]
        median_jump = float(np.median(jumps)) if jumps else 0.0
        if median_jump > 80:
            return 0
        signs = 0
        prev = 0
        for a, b in zip(xs, xs[1:]):
            d = b - a
            s = 1 if d > 3 else -1 if d < -3 else 0
            if s and s != prev:
                signs += 1
            if s:
                prev = s
        return max(0, signs // 2)
