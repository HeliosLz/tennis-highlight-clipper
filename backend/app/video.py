"""FFmpeg / PyAV video helpers: probe, frame extraction, cutting, merging."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import av
import imageio_ffmpeg

from .config import CLIP_CRF, CLIP_PRESET, CLIP_SCALE


def ffmpeg_bin() -> str:
    """Prefer a system FFmpeg, fall back to the imageio-ffmpeg bundled binary."""
    exe = shutil.which("ffmpeg")
    return exe or imageio_ffmpeg.get_ffmpeg_exe()


def probe(video_path: Path) -> dict:
    """Return duration (seconds), fps and size of the first video stream."""
    with av.open(str(video_path)) as c:
        s = c.streams.video[0]
        duration = float(s.duration * s.time_base) if s.duration else float(c.duration / av.time_base)
        if not duration or duration <= 0:
            duration = float(s.frames / s.average_rate) if s.frames else 0.0
        return {
            "duration": duration,
            "fps": float(s.average_rate) if s.average_rate else 0.0,
            "width": s.width,
            "height": s.height,
        }


def iter_frames(video_path: Path, fps: float, start: float = 0.0, end: float | None = None):
    """Yield (t, ndarray RGB) frames sampled at 'fps' between start and end."""
    container = av.open(str(video_path))
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"
    interval = 1.0 / fps
    next_t = start
    for frame in container.decode(stream):
        t = float(frame.pts * stream.time_base) if frame.pts is not None else None
        if t is None:
            continue
        if end is not None and t >= end:
            break
        if t + 1e-6 >= next_t:
            yield t, frame.to_ndarray(format="rgb24")
            next_t += interval
            while next_t <= t:
                next_t += interval
    container.close()


def run_ffmpeg(args: list[str], timeout: int = 600) -> None:
    """Run ffmpeg and raise on failure."""
    proc = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-800:]}")


def cut_clip(src: Path, start: float, end: float, dst: Path) -> None:
    """Cut [start, end] from src and re-encode to a uniform clip."""
    dur = max(0.2, end - start)
    run_ffmpeg([
        "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{dur:.3f}",
        "-vf", f"scale={CLIP_SCALE}:-2:flags=lanczos,fps=30",
        "-c:v", "libx264", "-preset", CLIP_PRESET, "-crf", str(CLIP_CRF),
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(dst),
    ], timeout=900)


def make_thumbnail(src: Path, t: float, dst: Path, width: int = 480) -> None:
    """Extract a single frame at time t as JPEG thumbnail."""
    run_ffmpeg([
        "-ss", f"{max(0.0, t):.3f}", "-i", str(src),
        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3",
        str(dst),
    ])


def concat_clips(clip_paths: list[Path], dst: Path) -> None:
    """Merge uniformly-encoded clips with the concat demuxer."""
    if len(clip_paths) == 1:
        shutil.copyfile(clip_paths[0], dst)
        return
    lst = dst.with_suffix(".txt")
    lines = "".join("file '" + str(p.resolve()) + "'" + chr(10) for p in clip_paths)
    lst.write_text(lines)
    try:
        run_ffmpeg([
            "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c", "copy", "-movflags", "+faststart", str(dst),
        ])
    finally:
        lst.unlink(missing_ok=True)
