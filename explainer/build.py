# -*- coding: utf-8 -*-
"""Build the explainer video end to end.

    python build.py audio     # synthesise narration, write timeline
    python build.py sheet     # render a QA contact sheet
    python build.py render    # render all frames (parallel) + encode + mux
    python build.py all

Deterministic: every frame is a pure function of its timestamp, so the render
step can be split across processes and re-run at will.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import narration  # noqa: E402
import scenes as S  # noqa: E402
from engine import H, W, Canvas, caption, A, BG, INK, MUTED, BALL, mix  # noqa: E402

OUT = HERE / "out"
AUDIO = OUT / "audio"
FRAMES = OUT / "frames"
FPS = 30
SR = 48000

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:  # pragma: no cover
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

import av  # noqa: E402


# ------------------------------------------------------------------- narration
def say_line(text: str, dst: Path) -> None:
    if dst.exists() and dst.stat().st_size > 1000:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["say", "-v", narration.VOICE, "-r", str(narration.RATE),
                    "-o", str(dst), "--data-format=LEF32@22050", text],
                   check=True, capture_output=True)


def read_audio(path: Path):
    with av.open(str(path)) as c:
        s = c.streams.audio[0]
        frames = [f.to_ndarray() for f in c.decode(s)]
        sr = s.rate
    a = np.concatenate([f.reshape(-1) for f in frames]).astype(np.float32)
    return a, sr


def trim(a: np.ndarray, sr: int, thr: float = 0.008, margin: float = 0.03):
    w = max(1, int(0.01 * sr))
    n = len(a) // w * w
    env = np.abs(a[:n]).reshape(-1, w).max(axis=1)
    nz = np.nonzero(env > thr)[0]
    if len(nz) == 0:
        return a
    i0 = max(0, int(nz[0] * w - margin * sr))
    i1 = min(len(a), int((nz[-1] + 1) * w + margin * sr))
    return a[i0:i1]


def resample(a: np.ndarray, sr: int, dst_sr: int = SR):
    if sr == dst_sr:
        return a
    n = int(round(len(a) * dst_sr / sr))
    xp = np.linspace(0, 1, len(a), endpoint=False)
    x = np.linspace(0, 1, n, endpoint=False)
    return np.interp(x, xp, a).astype(np.float32)


def build_timeline(verbose=True):
    """Synthesise every narration line, measure it, and lay out the timeline."""
    AUDIO.mkdir(parents=True, exist_ok=True)
    timing = {}
    cursor = 0.0
    for si, (sid, title, lines) in enumerate(narration.SCENES):
        durs, waves = [], []
        for li, text in enumerate(lines):
            h = hashlib.sha1(("%s|%d|%s" % (narration.VOICE, narration.RATE, text)).encode()).hexdigest()[:12]
            raw = AUDIO / ("%s_%02d_%s.wav" % (sid, li, h))
            say_line(text, raw)
            a, sr = read_audio(raw)
            a = trim(a, sr)
            a = resample(a, sr)
            waves.append(a)
            durs.append(len(a) / SR)
        lead = narration.LEAD_FIRST if si == 0 else narration.LEAD
        tail = narration.TAIL_LAST if si == len(narration.SCENES) - 1 else narration.TAIL
        starts = narration.line_starts(durs, lead, narration.GAP)
        dur = narration.scene_duration(durs, lead, narration.GAP, tail)
        timing[sid] = {"index": si, "title": title, "lines": lines, "durs": durs,
                       "starts": starts, "lead": lead, "tail": tail, "dur": dur,
                       "start_abs": cursor}
        cursor += dur
        if verbose:
            print("  %-9s %5.1fs  %s" % (sid, dur, lines[0][:28]))
    total = cursor
    (OUT / "timeline.json").write_text(json.dumps({"timing": timing, "total": total,
                                                   "fps": FPS}, ensure_ascii=False, indent=1))
    write_script_md(timing, total)
    if verbose:
        n_lines = sum(len(v["lines"]) for v in timing.values())
        print("  total %.1fs (%d:%02d), %d scenes, %d lines"
              % (total, total // 60, total % 60, len(timing), n_lines))
    return timing, total


def load_timeline():
    d = json.loads((OUT / "timeline.json").read_text())
    return d["timing"], d["total"]


def write_script_md(timing, total):
    out = ["# 旁白脚本 / Narration script", "",
           "由 `build.py audio` 自动生成，时间轴来自实测语音时长。", "",
           "总时长 **%d:%02d**  ·  配音 `%s`  ·  %d wpm  ·  %d 场"
           % (total // 60, total % 60, narration.VOICE, narration.RATE, len(timing)), ""]
    for sid, tm in timing.items():
        out.append("## %02d · %s  `%.1fs → %.1fs`" % (tm["index"], tm["title"],
                                                      tm["start_abs"], tm["start_abs"] + tm["dur"]))
        out.append("")
        for i, ln in enumerate(tm["lines"]):
            t0 = tm["start_abs"] + tm["starts"][i]
            out.append("- `%s` %s" % (S.mmss(t0), ln))
        out.append("")
    (OUT / "script.md").write_text("\n".join(out))


# ----------------------------------------------------------------------- audio
CHORDS = [
    [220.00, 261.63, 329.63, 392.00],   # Am7
    [174.61, 220.00, 261.63, 349.23],   # F
    [130.81, 196.00, 246.94, 329.63],   # Cmaj7
    [196.00, 246.94, 293.66, 392.00],   # G
]


def make_music(total: float, sr: int = SR, level: float = 0.05):
    n = int(total * sr)
    t = np.arange(n, dtype=np.float32) / sr
    left = np.zeros(n, dtype=np.float32)
    right = np.zeros(n, dtype=np.float32)
    seg = 9.0
    xf = 3.0
    for i, chord in enumerate(CHORDS):
        a0 = i * seg
        if a0 > total:
            break
        for j, f in enumerate(chord):
            lvl = level * (0.9 if j < 2 else 0.55) / len(chord) * 2.4
            det = 1.0 + (0.0009 if j % 2 else -0.0009)
            ph = np.random.RandomState(i * 17 + j).rand() * 6.28
            env = np.zeros(n, dtype=np.float32)
            i0 = int(a0 * sr)
            i1 = min(n, int((a0 + seg + xf) * sr))
            if i1 <= i0:
                continue
            k = np.arange(i1 - i0, dtype=np.float32) / sr
            e = np.minimum(1.0, k / xf) * np.minimum(1.0, np.maximum(0.0, (seg + xf - k) / xf))
            env[i0:i1] = e
            w = 2 * np.pi * (f * det) * t + ph
            v = (np.sin(w) + 0.22 * np.sin(2 * w) + 0.06 * np.sin(3 * w)).astype(np.float32)
            v *= (0.85 + 0.15 * np.sin(2 * np.pi * 0.08 * t + j)).astype(np.float32)
            pan = 0.5 + 0.28 * np.sin(j * 1.7 + i)
            left += v * env * lvl * pan
            right += v * env * lvl * (1 - pan)
    return left, right


def pluck(freq, dur, sr=SR, amp=0.05):
    n = int(dur * sr)
    t = np.arange(n, dtype=np.float32) / sr
    env = np.exp(-3.4 * t).astype(np.float32)
    v = (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)) * env * amp
    return v.astype(np.float32)


def build_audio(timing, total):
    n = int(total * SR) + SR
    voice = np.zeros(n, dtype=np.float32)
    gate = np.zeros(n, dtype=np.float32)
    for sid, tm in timing.items():
        for i, text in enumerate(tm["lines"]):
            h = hashlib.sha1(("%s|%d|%s" % (narration.VOICE, narration.RATE, text)).encode()).hexdigest()[:12]
            a, sr = read_audio(AUDIO / ("%s_%02d_%s.wav" % (sid, i, h)))
            a = resample(trim(a, sr), sr)
            i0 = int((tm["start_abs"] + tm["starts"][i]) * SR)
            i1 = min(n, i0 + len(a))
            voice[i0:i1] += a[:i1 - i0] * 1.0
            gate[max(0, i0 - int(0.15 * SR)):min(n, i1 + int(0.30 * SR))] = 1.0

    # duck the bed while the voice is speaking
    k = int(0.25 * SR)
    ker = np.ones(k, dtype=np.float32) / k
    duck = np.convolve(gate, ker, mode="same")
    duck = 1.0 - 0.55 * duck

    ml, mr = make_music(total)

    def _fit(a):
        a = a[:n]
        return np.pad(a, (0, max(0, n - len(a))))

    ml = _fit(ml) * duck
    mr = _fit(mr) * duck
    # a soft bell on every scene change
    for sid, tm in timing.items():
        i0 = int(tm["start_abs"] * SR)
        f = [329.63, 392.00, 440.00, 523.25][tm["index"] % 4]
        p = pluck(f, 1.6, amp=0.035)
        i1 = min(n, i0 + len(p))
        ml[i0:i1] += p[:i1 - i0] * 0.6
        mr[i0:i1] += p[:i1 - i0] * 0.4

    st = np.stack([voice * 1.0 + ml, voice * 1.0 + mr], axis=1)
    peak = float(np.abs(st).max()) or 1.0
    st = np.tanh(st / (peak * 0.92) * 1.15) * 0.92   # gentle soft-clip limiter
    st = st / (float(np.abs(st).max()) or 1.0) * 0.89

    wav = OUT / "narration.wav"
    pcm = (st * 32767).astype(np.int16)
    with av.open(str(wav), "w") as c:
        s = c.add_stream("pcm_s16le", rate=SR, layout="stereo")
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="stereo")
        frame.rate = SR
        for pkt in s.encode(frame):
            c.mux(pkt)
    print("  audio: %.1fs -> %s (peak %.2f)" % (len(st) / SR, wav.name, float(np.abs(st).max())))
    return wav


# ---------------------------------------------------------------- frame render
_SCENES = None
_TIMING = None
_TOTAL = None


def _init(timing, total):
    global _SCENES, _TIMING, _TOTAL
    _TIMING, _TOTAL = timing, total
    _SCENES = S.make_scenes(timing)
    for sc in _SCENES:
        tm = timing[sc.id]
        sc.start_abs = tm["start_abs"]
        sc.end_abs = tm["start_abs"] + tm["dur"]


def scene_at(t):
    for sc in _SCENES:
        if sc.start_abs <= t < sc.end_abs:
            return sc
    return _SCENES[-1]


def render_frame(n):
    t = n / FPS
    sc = scene_at(t)
    tl = t - sc.start_abs
    c = Canvas()
    sc.draw(c, tl, sc.ctx)
    if sc.chapter:
        S.chapter(c, sc.title, alpha=S.prog(tl, 0.15, 0.75))
    if sc.captions:
        idx = None
        for i in range(len(sc.ctx.starts)):
            if sc.ctx.ls(i) - 0.35 <= tl < sc.ctx.le(i) + 0.55:
                idx = i
                break
        if idx is not None:
            a = S.prog(tl, sc.ctx.ls(idx) - 0.35, sc.ctx.ls(idx) + 0.05) * \
                (1 - S.prog(tl, sc.ctx.le(idx) + 0.30, sc.ctx.le(idx) + 0.55))
            txt = sc.lines[idx]
            size = 34
            while c.tw(txt, size) > 1560 and size > 22:
                size -= 2
            caption(c, txt, alpha=a * 0.98, size=size)
    fade = 1.0
    if t < 0.9:
        fade = S.prog(t, 0.0, 0.9)
    if _TOTAL - t < 1.6:
        fade = min(fade, max(0.0, (_TOTAL - t) / 1.6))
    return c.finish(fade)


def render_chunk(args):
    """Render a contiguous frame range and stream it straight into its own H.264 segment."""
    start, end, timing, total = args
    _init(timing, total)
    FRAMES.mkdir(parents=True, exist_ok=True)
    path = FRAMES / ("chunk_%06d.mp4" % start)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p",
           "-g", "30", "-movflags", "+faststart", str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for n in range(start, end):
            proc.stdin.write(render_frame(n).tobytes())
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError("segment %s failed (ffmpeg rc=%d)" % (path.name, rc))
    return str(path)


def render_all(timing, total, workers=None):
    workers = workers or max(2, min(10, (os.cpu_count() or 4) - 1))
    total_frames = int(round(total * FPS))
    chunk = int(np.ceil(total_frames / workers))
    jobs = []
    for w in range(workers):
        a = w * chunk
        b = min(total_frames, a + chunk)
        if a < b:
            jobs.append((a, b, timing, total))
    print("  rendering %d frames on %d workers ..." % (total_frames, len(jobs)))
    t0 = time.time()
    FRAMES.mkdir(parents=True, exist_ok=True)
    for f in FRAMES.glob("chunk_*"):
        f.unlink()
    with mp.get_context("spawn").Pool(len(jobs)) as pool:
        paths = pool.map(render_chunk, jobs)
    dt = time.time() - t0
    print("  rendered in %.1fs (%.0f frames/s)" % (dt, total_frames / dt))
    return sorted(paths), total_frames


def encode(paths, total_frames, dst: Path, wav: Path | None = None):
    """Concat the per-worker segments (stream copy) and mux the audio."""
    silent = OUT / "silent.mp4"
    if len(paths) == 1:
        shutil.copyfile(paths[0], silent)
    else:
        lst = OUT / "segments.txt"
        lst.write_text("".join("file '%s'\n" % Path(x).resolve() for x in paths))
        print("  concatenating %d segments ..." % len(paths))
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-fflags", "+genpts",
                        "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                        "-movflags", "+faststart", str(silent)], check=True)
        lst.unlink(missing_ok=True)
    print("  video ok: %.1f MB" % (silent.stat().st_size / 1e6))
    if wav is None:
        return silent
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(silent), "-i", str(wav),
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True)
    return dst


# ------------------------------------------------------------------- QA sheets
def contact_sheet(timing, total, picks=None):
    """Render a grid of stills for visual QA. picks = [(scene_id, local_time)]"""
    from PIL import Image
    _init(timing, total)
    if picks is None:
        picks = []
        for sid, tm in timing.items():
            n = len(tm["lines"])
            for i in range(n):
                picks.append((sid, tm["starts"][i] + tm["durs"][i] * 0.55))
    cols = 3
    rows = int(np.ceil(len(picks) / cols))
    tw, th = 620, 349
    sheet = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
    for k, (sid, lt) in enumerate(picks):
        sc = [s for s in _SCENES if s.id == sid][0]
        c = Canvas()
        sc.draw(c, lt, sc.ctx)
        if sc.chapter:
            S.chapter(c, sc.title, alpha=1.0)
        if sc.captions:
            for i in range(len(sc.ctx.starts)):
                if sc.ctx.ls(i) <= lt < sc.ctx.le(i):
                    txt = sc.lines[i]
                    size = 34
                    while c.tw(txt, size) > 1560 and size > 22:
                        size -= 2
                    caption(c, txt, alpha=0.95, size=size)
                    break
        im = c.finish().resize((tw, th), Image.LANCZOS)
        r, cc = divmod(k, cols)
        sheet.paste(im, (cc * tw, r * th))
    dst = OUT / "contact-sheet.png"
    sheet.save(dst)
    print("  sheet -> %s (%d stills)" % (dst, len(picks)))
    return dst


# ------------------------------------------------------------------------ main
def audio_is_stale():
    """narration.wav must be rebuilt whenever the timeline it was mixed from changed."""
    wav, tl = OUT / "narration.wav", OUT / "timeline.json"
    if not wav.exists():
        return True
    return tl.stat().st_mtime > wav.stat().st_mtime


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", nargs="?", default="all",
                    choices=["audio", "sheet", "render", "encode", "all"])
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--no-audio", action="store_true", help="skip audio rebuild on 'all'")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if a.stage in ("audio", "all"):
        print("[1/3] narration")
        timing, total = build_timeline()
    else:
        timing, total = load_timeline()
        print("[1/3] narration (cached, %.1fs)" % total)

    if a.stage == "audio":
        return
    if a.stage == "sheet":
        contact_sheet(timing, total)
        return

    wav = OUT / "narration.wav"
    if a.stage == "encode":
        paths = sorted(FRAMES.glob("chunk_*.mp4"))
        if not paths:
            print("no segments in out/frames — run `render` first")
            return
        nf = int(round(total * FPS))
        if audio_is_stale():
            print("  (rebuilding stale audio)")
            wav = build_audio(timing, total)
        dst = encode(paths, nf, OUT / "explainer.mp4", wav if wav.exists() else None)
        print("done ->", dst)
        return

    need_audio = (a.stage == "all" and not a.no_audio) or audio_is_stale()
    if need_audio:
        print("[2/3] audio mix")
        wav = build_audio(timing, total)
    print("[3/3] frames + encode")
    paths, nf = render_all(timing, total, a.workers)
    dst = encode(paths, nf, OUT / "explainer.mp4", wav if wav.exists() else None)
    print("done ->", dst)


if __name__ == "__main__":
    main()
