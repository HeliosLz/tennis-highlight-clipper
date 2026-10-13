# -*- coding: utf-8 -*-
"""A tiny purpose-built animation engine.

Everything is drawn in a 1920x1080 design space at SS-times supersampling and
downscaled with Lanczos, which is what gives the crisp 3b1b-ish look without
needing a real vector renderer.

The engine is deterministic: frame(t) depends only on t, so frames can be
rendered out of order and in parallel by any number of processes.
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

W, H = 1920, 1080
SS = 2  # supersampling factor

# --------------------------------------------------------------------- palette
BG      = (9, 14, 20)
BG2     = (17, 25, 36)
BG3     = (26, 36, 50)
INK     = (232, 238, 246)
MUTED   = (132, 150, 172)
DIM     = (74, 89, 108)
BALL    = (214, 240, 74)
BALL_D  = (146, 170, 38)
BLUE    = (88, 196, 221)
ORANGE  = (255, 158, 74)
GREEN   = (94, 230, 168)
RED     = (255, 107, 107)
VIOLET  = (167, 139, 250)
PAPER   = (246, 248, 250)

ZH_FONT    = ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0)   # W3
ZH_BOLD    = ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2)   # W6
SERIF_FONT = ("/System/Library/Fonts/Supplemental/Songti.ttc", 1)
MONO_FONT  = ("/System/Library/Fonts/SFNSMono.ttf", 0)


def A(color, alpha=1.0):
    """Add alpha to an RGB tuple."""
    if alpha >= 0.999:
        return (color[0], color[1], color[2], 255)
    return (color[0], color[1], color[2], max(0, min(255, int(round(alpha * 255)))))


def mix(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def _has_cjk(s):
    return any(ord(ch) > 0x2E7F for ch in s)


@lru_cache(maxsize=2048)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    path, idx = {"zh": ZH_FONT, "zhb": ZH_BOLD, "serif": SERIF_FONT, "mono": MONO_FONT}[kind]
    return ImageFont.truetype(path, max(6, int(size)), index=idx)


def pick_kind(s, kind):
    """The mono font has no CJK glyphs — fall back to the CJK face for mixed strings."""
    if kind == "mono" and _has_cjk(s):
        return "zh"
    return kind


# ----------------------------------------------------------------------- easing
def clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def linear(x):
    return clamp01(x)


def smooth(x):
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def smoother(x):
    x = clamp01(x)
    return x * x * x * (x * (x * 6 - 15) + 10)


def out_cubic(x):
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def out_quint(x):
    x = clamp01(x)
    return 1 - (1 - x) ** 5


def out_expo(x):
    x = clamp01(x)
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def in_cubic(x):
    x = clamp01(x)
    return x ** 3


def in_out(x):
    x = clamp01(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def out_back(x, s=1.7):
    x = clamp01(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def spring(x, freq=2.4, damp=5.0):
    """Overshooting settle, good for things that 'snap' into place."""
    x = clamp01(x)
    if x >= 1:
        return 1.0
    return 1 - math.exp(-damp * x) * math.cos(freq * math.pi * x)


def prog(t, a, b, e=smooth):
    """Eased 0..1 progress of t through the absolute interval [a, b]."""
    if b <= a:
        return 1.0 if t >= b else 0.0
    return e((t - a) / (b - a))


def stagger(t, i, start, step, dur, e=out_cubic):
    return prog(t, start + i * step, start + i * step + dur, e)


def pulse(t, period=2.0, lo=0.0, hi=1.0):
    return lo + (hi - lo) * (0.5 - 0.5 * math.cos(2 * math.pi * t / period))


def bezier(p0, p1, p2, u):
    v = 1 - u
    return (v * v * p0[0] + 2 * v * u * p1[0] + u * u * p2[0],
            v * v * p0[1] + 2 * v * u * p1[1] + u * u * p2[1])


# ------------------------------------------------------------------- background
@lru_cache(maxsize=1)
def _background():
    """Cached 4K background.

    The gradient is computed tiny and upscaled: it is perfectly smooth, so the
    result is identical, but peak memory drops from ~400 MB per process to a
    few MB — which matters when 5 render workers start at once.
    """
    w, h = W * SS, H * SS
    tw, th = 240, 135
    x = np.linspace(-1.0, 1.0, tw, dtype=np.float32)
    y = np.linspace(-1.0, 1.0, th, dtype=np.float32)
    r2 = np.add.outer(y * y * 1.15, x * x * 0.85)
    glow = np.exp(-r2 * 1.5)
    vig = np.clip(1.0 - 0.55 * r2, 0.0, 1.0)
    base = np.array(BG, dtype=np.float32)
    light = np.array(BG3, dtype=np.float32)
    arr = base + (light - base) * (glow * 0.55)[:, :, None]
    arr *= vig[:, :, None]
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").resize((w, h), Image.BICUBIC)
    # static dither: dark gradients band badly in H.264, and a fixed noise pattern
    # breaks the contours without costing the encoder anything frame to frame
    img = ImageChops.add(img, Image.effect_noise((w, h), 2.2).convert("RGB"), 1.0, -128)
    d = ImageDraw.Draw(img, "RGBA")
    step = 60 * SS
    for gy in range(step, h, step):
        for gx in range(step, w, step):
            d.ellipse([gx - SS, gy - SS, gx + SS, gy + SS], fill=A(DIM, 0.10))
    return img


@lru_cache(maxsize=1)
def _background_small():
    # 2x box reduce == exactly what finish() does, so fades blend cleanly
    return _background().reduce(SS)


@lru_cache(maxsize=1)
def _bg_rgb():
    return np.asarray(_background(), dtype=np.uint8)


@lru_cache(maxsize=96)
def _glow_sprite(color, abucket):
    """Cached radial-gradient sprite; much smoother than concentric rings."""
    size = 128
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    d = np.sqrt((x - size / 2 + 0.5) ** 2 + (y - size / 2 + 0.5) ** 2) / (size / 2)
    a = (np.clip(1.0 - d, 0.0, 1.0) ** 2.3) * (abucket / 10.0)
    rgb = np.empty((size, size, 3), dtype=np.uint8)
    rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2] = color
    return Image.fromarray(np.dstack([rgb, (a * 255).astype(np.uint8)]), "RGBA")


class Canvas:
    """Design-space drawing surface with a transform stack (zoom / pan)."""

    def __init__(self):
        self.buf = _background().copy()   # 7 ms vs 200 ms for a bytes round-trip
        self.d = ImageDraw.Draw(self.buf, "RGBA")
        self.stack = [(1.0, 0.0, 0.0)]

    # -------------------------------------------------------------- transform
    def push(self, scale=1.0, cx=W / 2, cy=H / 2, dx=0.0, dy=0.0):
        s0, ox, oy = self.stack[-1]
        self.stack.append((
            s0 * scale,
            ((cx - cx * scale + dx) * s0) + ox,
            ((cy - cy * scale + dy) * s0) + oy,
        ))

    def pop(self):
        self.stack.pop()

    @property
    def scale(self):
        return self.stack[-1][0]

    def m(self, x, y):
        s, ox, oy = self.stack[-1]
        return ((x * s + ox) * SS, (y * s + oy) * SS)

    def mx(self, x):
        s, ox, _ = self.stack[-1]
        return (x * s + ox) * SS

    def my(self, y):
        s, _, oy = self.stack[-1]
        return (y * s + oy) * SS

    def lw(self, w):
        return max(1, int(round(w * self.scale * SS)))

    def rect_pts(self, x0, y0, x1, y1):
        a = self.m(x0, y0)
        b = self.m(x1, y1)
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]

    # -------------------------------------------------------------- primitives
    def rect(self, x0, y0, x1, y1, fill=None, outline=None, width=2, alpha=1.0, radius=0):
        box = self.rect_pts(x0, y0, x1, y1)
        f = A(fill, alpha) if fill else None
        o = A(outline, alpha) if outline else None
        if radius:
            self.d.rounded_rectangle(box, radius=int(radius * self.scale * SS),
                                     fill=f, outline=o, width=self.lw(width) if o else 0)
        else:
            self.d.rectangle(box, fill=f, outline=o, width=self.lw(width) if o else 0)

    def line(self, pts, color, width=3, alpha=1.0, joint="curve"):
        p = [self.m(*q) for q in pts]
        self.d.line(p, fill=A(color, alpha), width=self.lw(width), joint=joint)

    def poly(self, pts, fill=None, outline=None, width=2, alpha=1.0):
        p = [self.m(*q) for q in pts]
        self.d.polygon(p, fill=A(fill, alpha) if fill else None,
                       outline=A(outline, alpha) if outline else None,
                       width=self.lw(width) if outline else 0)

    def circle(self, x, y, r, fill=None, outline=None, width=2, alpha=1.0):
        box = self.rect_pts(x - r, y - r, x + r, y + r)
        self.d.ellipse(box, fill=A(fill, alpha) if fill else None,
                       outline=A(outline, alpha) if outline else None,
                       width=self.lw(width) if outline else 0)

    def ellipse(self, x, y, rx, ry, fill=None, outline=None, width=2, alpha=1.0):
        box = self.rect_pts(x - rx, y - ry, x + rx, y + ry)
        self.d.ellipse(box, fill=A(fill, alpha) if fill else None,
                       outline=A(outline, alpha) if outline else None,
                       width=self.lw(width) if outline else 0)

    def arc(self, x, y, r, start, end, color, width=3, alpha=1.0):
        box = self.rect_pts(x - r, y - r, x + r, y + r)
        self.d.arc(box, start, end, fill=A(color, alpha), width=self.lw(width))

    def ring(self, x, y, r, color, width=3, alpha=1.0):
        self.circle(x, y, r, outline=color, width=width, alpha=alpha)

    def glow(self, x, y, r, color, alpha=0.5, spread=2.8):
        ab = max(1, min(10, int(round(clamp01(alpha) * 10))))
        s = _glow_sprite(tuple(color), ab)
        X, Y = self.m(x, y)
        rad = max(2.5, r * spread * self.scale * SS * 0.5)
        n = max(4, int(rad * 2))
        im = s.resize((n, n), Image.BILINEAR)
        self.buf.paste(im.convert("RGB"), (int(X - rad), int(Y - rad)), im.split()[3])

    def text(self, x, y, s, size=32, kind="zh", color=INK, alpha=1.0, anchor="la",
             track=0.0, bold=False):
        kind = pick_kind(s, kind)
        if bold and kind == "zh":
            kind = "zhb"
        f = font(kind, int(round(size * self.scale)))
        if track:
            self._text_tracked(x, y, s, f, color, alpha, anchor, track)
            return
        X, Y = self.m(x, y)
        self.d.text((X, Y), s, font=f, fill=A(color, alpha), anchor=anchor)

    def _text_tracked(self, x, y, s, f, color, alpha, anchor, track):
        d = self.d
        px = self.scale * SS
        widths = [d.textlength(ch, font=f) for ch in s]
        total = sum(widths) + track * px * (len(s) - 1)
        X, Y = self.m(x, y)
        if anchor[0] == "m":
            X -= total / 2
        elif anchor[0] == "r":
            X -= total
        for ch, w in zip(s, widths):
            d.text((X, Y), ch, font=f, fill=A(color, alpha), anchor="l" + anchor[1])
            X += w + track * px

    def tw(self, s, size=32, kind="zh", track=0.0):
        f = font(pick_kind(s, kind), int(round(size * self.scale)))
        base = self.d.textlength(s, font=f)
        return (base + track * self.scale * SS * max(0, len(s) - 1)) / (self.scale * SS)

    def thumb(self, im, x0, y0, x1, y1, alpha=1.0, radius=0):
        """Paste a PIL image into a design-space box."""
        box = self.rect_pts(x0, y0, x1, y1)
        w = max(1, int(box[2] - box[0]))
        h = max(1, int(box[3] - box[1]))
        im = im.resize((w, h), Image.LANCZOS)
        if alpha < 0.999:
            im = im.convert("RGB")
            self.buf.paste(im, (int(box[0]), int(box[1])),
                           Image.new("L", (w, h), int(alpha * 255)))
        else:
            self.buf.paste(im, (int(box[0]), int(box[1])))

    # ------------------------------------------------------------------ output
    def finish(self, fade=1.0):
        out = self.buf.reduce(SS)         # 34 ms vs 400 ms for Lanczos
        if fade < 0.999:
            out = Image.blend(_background_small(), out, clamp01(fade))
        return out


# ---------------------------------------------------------------------- widgets
def ball(c: Canvas, x, y, r, alpha=1.0, glow=0.0, color=BALL, seam=BALL_D, rot=0.0):
    """A tennis ball: fill, two bezier seams that stay inside the ball, highlight."""
    if glow > 0:
        c.glow(x, y, r * 1.15, color, alpha=glow * 0.85)
    c.circle(x, y, r, fill=color, alpha=alpha)
    if r > 1.5:
        for sgn in (-1, 1):
            pts = []
            for k in range(15):
                u = k / 14
                a = (1 - u) ** 2
                b = 2 * (1 - u) * u
                cc = u * u
                pts.append((a * x + b * (x + sgn * 1.45 * r) + cc * x,
                            a * (y - r * 0.99) + b * y + cc * (y + r * 0.99)))
            c.line(pts, seam, width=max(1.0, r * 0.11), alpha=alpha * 0.9)
    if r > 5:
        c.circle(x - r * 0.34, y - r * 0.36, r * 0.19, fill=PAPER, alpha=alpha * 0.45)


def player(c: Canvas, x, y, h=130, color=BLUE, alpha=1.0, facing=1, arm=0.0, racket=True):
    """Stylised player standing on (x, y) — feet at y, height h."""
    w = h * 0.075
    c.ellipse(x, y + h * 0.012, h * 0.17, h * 0.035, fill=(0, 0, 0), alpha=alpha * 0.30)
    hip = y - h * 0.44
    sh = y - h * 0.74
    for sgn in (-1, 1):
        kx, ky = x + sgn * h * 0.10 * facing, y - h * 0.22
        c.line([(x + sgn * h * 0.035 * facing, hip), (kx, ky)], color, width=w * 1.05, alpha=alpha)
        c.line([(kx, ky), (kx + sgn * h * 0.075 * facing, y - h * 0.01)], color,
               width=w * 0.95, alpha=alpha)
    c.line([(x, hip), (x, sh)], color, width=w * 1.5, alpha=alpha)
    c.circle(x, y - h * 0.855, h * 0.086, fill=color, alpha=alpha)
    ax, ay = x + h * 0.26 * facing, y - h * (0.58 + 0.20 * arm)
    c.line([(x, sh - h * 0.01), (ax, ay)], color, width=w * 0.8, alpha=alpha)
    if racket:
        rx, ry = ax + h * 0.13 * facing, ay - h * 0.30
        c.line([(ax, ay), (rx, ry)], MUTED, width=max(1.0, w * 0.42), alpha=alpha * 0.85)
        c.circle(rx + h * 0.045 * facing, ry - h * 0.055, h * 0.082,
                 outline=color, width=max(1.2, w * 0.42), alpha=alpha * 0.85)


def court(c: Canvas, cx, ybase, w, h, alpha=1.0, color=None, net=True, fill=True):
    """Perspective court; (cx, ybase) is the centre of the near baseline."""
    color = color or DIM
    hb, ht = w * 0.5, w * 0.33

    def half_at(d):
        return hb + (ht - hb) * d

    yn, yf = ybase, ybase - h
    if fill:
        c.poly([(cx - hb, yn), (cx + hb, yn), (cx + ht, yf), (cx - ht, yf)],
               fill=mix(BG, mix(color, BG3, 0.5), 0.30), alpha=alpha)
    # outer boundary
    c.line([(cx - hb, yn), (cx + hb, yn)], mix(color, PAPER, 0.30), width=2.2, alpha=alpha * 0.8)
    c.line([(cx - ht, yf), (cx + ht, yf)], mix(color, PAPER, 0.30), width=2.2, alpha=alpha * 0.6)
    c.line([(cx - hb, yn), (cx - ht, yf)], mix(color, PAPER, 0.30), width=2.2, alpha=alpha * 0.8)
    c.line([(cx + hb, yn), (cx + ht, yf)], mix(color, PAPER, 0.30), width=2.2, alpha=alpha * 0.8)
    # singles sidelines
    for sgn in (-1, 1):
        c.line([(cx + sgn * half_at(0.0) * 0.84, yn), (cx + sgn * half_at(1.0) * 0.84, yf)],
               color, width=1.4, alpha=alpha * 0.5)
    # service lines + centre service line
    for d in (0.30, 0.86):
        y = yn + (yf - yn) * d
        c.line([(cx - half_at(d) * 0.84, y), (cx + half_at(d) * 0.84, y)], color,
               width=1.6, alpha=alpha * 0.55)
    dnet = 0.60
    c.line([(cx, yn + (yf - yn) * 0.30), (cx, yn + (yf - yn) * 0.86)], color, width=1.6,
           alpha=alpha * 0.5)
    if net:
        ynet = yn + (yf - yn) * dnet
        hn = half_at(dnet)
        c.line([(cx - hn, ynet), (cx + hn, ynet)], PAPER, width=3.0, alpha=alpha * 0.55)
        for sgn in (-1, 1):
            c.line([(cx + sgn * hn, ynet + 6), (cx + sgn * hn, ynet - 6)], PAPER, width=2.5,
                   alpha=alpha * 0.45)
        for i in range(1, 18):
            xg = cx - hn + (2 * hn) * i / 18
            c.line([(xg, ynet - 5), (xg, ynet + 5)], PAPER, width=0.9, alpha=alpha * 0.20)


def bbox(c: Canvas, x0, y0, x1, y1, color, alpha=1.0, width=3.5, p=1.0, corner=0.22):
    """Detection box with corner ticks, growing from its centre."""
    if p <= 0.001:
        return
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    sx, sy = (x1 - x0) / 2 * p, (y1 - y0) / 2 * p
    x0, x1, y0, y1 = cx - sx, cx + sx, cy - sy, cy + sy
    lx, ly = (x1 - x0) * corner, (y1 - y0) * corner
    for (px, py, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        c.line([(px, py), (px + dx * lx, py)], color, width=width, alpha=alpha)
        c.line([(px, py), (px, py + dy * ly)], color, width=width, alpha=alpha)


def chip(c: Canvas, x, y, s, size=26, fg=INK, bg=BG2, border=None, alpha=1.0, pad=14,
         kind="zh", anchor="lm", radius=None, track=0.0):
    """Rounded label pill. anchor 'lm' means x is the left edge, y the centre."""
    tw = c.tw(s, size, kind, track)
    h = size * 1.72
    x0 = x - pad if anchor[0] == "m" else x
    if anchor[0] == "m":
        x0 = x - tw / 2 - pad
    elif anchor[0] == "r":
        x0 = x - tw - 2 * pad
    y0 = y - h / 2
    r = radius if radius is not None else h * 0.32
    c.rect(x0, y0, x0 + tw + 2 * pad, y0 + h, fill=bg, outline=border,
           width=2, alpha=alpha, radius=r)
    c.text(x0 + pad, y, s, size=size, kind=kind, color=fg, alpha=alpha, anchor="lm", track=track)
    return tw + 2 * pad


def arrow(c: Canvas, x0, y0, x1, y1, color=MUTED, width=3, alpha=1.0, head=14, curve=0.0):
    if curve:
        mx_, my_ = (x0 + x1) / 2, (y0 + y1) / 2
        nx, ny = -(y1 - y0), (x1 - x0)
        n = math.hypot(nx, ny) or 1
        pts = [bezier((x0, y0), (mx_ + nx / n * curve, my_ + ny / n * curve), (x1, y1), u / 12)
               for u in range(13)]
        c.line(pts, color, width=width, alpha=alpha)
    else:
        c.line([(x0, y0), (x1, y1)], color, width=width, alpha=alpha)
    ang = math.atan2(y1 - y0, x1 - x0)
    c.poly([(x1, y1),
            (x1 - head * math.cos(ang - 0.42), y1 - head * math.sin(ang - 0.42)),
            (x1 - head * math.cos(ang + 0.42), y1 - head * math.sin(ang + 0.42))],
           fill=color, alpha=alpha)


def mini_frame(c: Canvas, x, y, w, h, seed=0, alpha=1.0, ball_on=True, hue=None):
    """Abstract miniature of a tennis frame, used inside filmstrips."""
    rng = np.random.RandomState(seed % (2 ** 31))
    hue = hue or DIM
    c.rect(x, y, x + w, y + h, fill=mix(BG, BG3, 0.55), outline=hue, width=1.2,
           alpha=alpha * 0.9, radius=h * 0.06)
    c.line([(x + w * 0.12, y + h * 0.30), (x + w * 0.88, y + h * 0.30)], hue, width=1, alpha=alpha * 0.45)
    c.line([(x + w * 0.10, y + h * 0.80), (x + w * 0.90, y + h * 0.72)], hue, width=1, alpha=alpha * 0.25)
    for k in range(2):
        px = x + w * (0.30 + 0.32 * k + 0.05 * (rng.rand() - 0.5))
        py = y + h * (0.62 + 0.10 * rng.rand())
        c.circle(px, py - h * 0.22, h * 0.075, fill=BLUE, alpha=alpha * 0.75)
        c.line([(px, py - h * 0.17), (px, py)], BLUE, width=max(1.0, h * 0.035), alpha=alpha * 0.7)
        c.line([(px, py), (px - h * 0.06, py + h * 0.12)], BLUE, width=max(1.0, h * 0.03), alpha=alpha * 0.7)
        c.line([(px, py), (px + h * 0.06, py + h * 0.12)], BLUE, width=max(1.0, h * 0.03), alpha=alpha * 0.7)
    if ball_on:
        bx = x + w * (0.20 + 0.60 * rng.rand())
        by = y + h * (0.20 + 0.35 * rng.rand())
        ball(c, bx, by, max(1.6, h * 0.030), alpha=alpha)


def track_line(c: Canvas, x, y, w, h, segs, alpha=1.0, radius=None, glow=False):
    """segments: list of (t0, t1, color, alpha) in seconds over a time axis."""
    c.rect(x, y, x + w, y + h, fill=mix(BG, BG3, 0.6), alpha=alpha * 0.9,
           radius=radius if radius is not None else h / 2)
    for t0, t1, col, al in segs:
        if t1 <= t0:
            continue
        c.rect(x + w * t0, y, x + w * t1, y + h, fill=col, alpha=alpha * al,
               radius=radius if radius is not None else h / 2)
        if glow:
            c.rect(x + w * t0 - 3, y - 3, x + w * t1 + 3, y + h + 3, outline=col,
                   width=2, alpha=alpha * al * 0.35, radius=(radius or h / 2) + 3)


def caption(c: Canvas, s, alpha=1.0, y=H - 74, size=34):
    """Bottom caption bar; the narration line currently being spoken."""
    if alpha <= 0.01 or not s:
        return
    w = c.tw(s, size)
    pad = 26
    x0 = W / 2 - w / 2 - pad
    c.rect(x0, y - 34, x0 + w + 2 * pad, y + 34, fill=(6, 10, 15), alpha=alpha * 0.72,
           radius=14)
    c.text(W / 2, y, s, size=size, color=PAPER, alpha=alpha * 0.95, anchor="mm")


def label_value(c: Canvas, x, y, label, value, size=30, color=INK, kind="mono",
                alpha=1.0, anchor="lm"):
    """e.g. ANALYSIS_FPS  ·  5"""
    c.text(x, y, label, size=size * 0.82, kind="zh", color=MUTED, alpha=alpha, anchor=anchor)
    off = c.tw(label, size * 0.82) + 14
    c.text(x + off, y, value, size=size, kind=kind, color=color, alpha=alpha, anchor=anchor)
    return off + c.tw(value, size, kind)
