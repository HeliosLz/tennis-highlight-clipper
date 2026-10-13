# -*- coding: utf-8 -*-
"""Storyboard: one draw(canvas, t, ctx) function per scene.

All timings are driven by the *measured* narration durations, so the visuals
stay in sync no matter how fast the voice reads. `ctx` exposes:

    ctx.ls(i)            start of narration line i, in seconds from scene start
    ctx.le(i)            end of narration line i
    ctx.f(i, off)       ctx.ls(i) + off
    ctx.p(t, i, a, b)    eased progress within line i, from a to b (fractions)

Coordinate space is 1920x1080 with y growing downwards.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from engine import *  # noqa: F401,F403
import engine as E


# --------------------------------------------------------------------- context
@dataclass
class Ctx:
    id: str
    title: str
    lines: list
    starts: list
    durs: list
    lead: float
    tail: float
    dur: float

    def ls(self, i):
        return self.starts[i]

    def le(self, i):
        return self.starts[i] + self.durs[i]

    def at(self, i, off=0.0):
        """Absolute time: off seconds after line i starts."""
        return self.starts[i] + off

    def f(self, i, frac):
        """Absolute time: frac of the way through line i (may exceed 1 -> into the tail)."""
        return self.starts[i] + frac * self.durs[i]

    def p(self, t, i, a=0.0, b=1.0, e=out_cubic):
        s, d = self.starts[i], self.durs[i]
        return prog(t, s + a * d, s + b * d, e)

    def pa(self, t, i, a, b, e=out_cubic):
        """Progress between two absolute offsets from line i's start."""
        s = self.starts[i]
        return prog(t, s + a, s + b, e)


@dataclass
class Scene:
    id: str
    title: str
    lines: list
    lead: float
    tail: float
    draw: object
    chapter: bool = True
    captions: bool = True
    ctx: Ctx = None


# ------------------------------------------------------------------- utilities
def mmss(sec):
    sec = max(0.0, sec)
    return "%d:%02d" % (int(sec) // 60, int(sec) % 60)


def mapx(x0, x1, t0, t1, v):
    return x0 + (x1 - x0) * (v - t0) / (t1 - t0)


def strike(c, x, y, s, size=54, kind="zh", color=INK, alpha=1.0, p=1.0, thick=4):
    c.text(x, y, s, size=size, kind=kind, color=color, alpha=alpha, anchor="lm")
    w = c.tw(s, size, kind)
    c.line([(x - 6, y), (x - 6 + (w + 12) * p, y)], RED, width=thick, alpha=alpha * 0.95)


def chapter(c, title, alpha=1.0):
    if alpha <= 0.01 or not title:
        return
    c.rect(80, 54, 86, 86, fill=BALL, alpha=alpha * 0.9, radius=3)
    c.text(104, 70, title, size=27, kind="zh", color=MUTED, alpha=alpha * 0.95, anchor="lm", track=1.5)


def match_frame(c, x0, y0, x1, y1, alpha=1.0, ball_xy=None, players=(0.30, 0.70),
                crowd=True, court_lines=True):
    """A stylised broadcast frame: crowd band, court, two players, optional ball."""
    w, h = x1 - x0, y1 - y0
    c.rect(x0, y0, x1, y1, fill=(7, 11, 17), outline=BG3, width=2, alpha=alpha, radius=8)
    if crowd:
        c.rect(x0 + 2, y0 + 2, x1 - 2, y0 + h * 0.20, fill=mix(BG, BG3, 0.85),
               alpha=alpha * 0.95, radius=7)
        rng = np.random.RandomState(11)
        for _ in range(80):
            dx = x0 + 8 + (w - 16) * rng.rand()
            dy = y0 + 6 + (h * 0.20 - 12) * rng.rand()
            c.circle(dx, dy, 2.4, fill=mix(MUTED, BG3, rng.rand() * 0.8), alpha=alpha * 0.55)
    if court_lines:
        c.poly([(x0 + w * 0.10, y0 + h * 0.96), (x1 - w * 0.10, y0 + h * 0.96),
                (x0 + w * 0.34, y0 + h * 0.30), (x1 - w * 0.34, y0 + h * 0.30)],
               fill=(14, 26, 34), alpha=alpha * 0.85)
        for a, b in (((0.10, 0.96), (0.34, 0.30)), ((0.90, 0.96), (0.66, 0.30)),
                     ((0.10, 0.96), (0.90, 0.96)), ((0.34, 0.30), (0.66, 0.30))):
            c.line([(x0 + w * a[0], y0 + h * a[1]), (x0 + w * b[0], y0 + h * b[1])],
                   mix(BG3, PAPER, 0.35), width=2, alpha=alpha * 0.55)
        c.line([(x0 + w * 0.27, y0 + h * 0.55), (x1 - w * 0.27, y0 + h * 0.55)],
               PAPER, width=2, alpha=alpha * 0.28)
        for sgn in (-1, 1):
            c.line([(x0 + w * (0.5 + sgn * 0.30), y0 + h * 0.96),
                    (x0 + w * (0.5 + sgn * 0.22), y0 + h * 0.30)], PAPER, width=1.2, alpha=alpha * 0.14)
    for k, px in enumerate(players):
        player(c, x0 + w * px, y0 + h * 0.90, h=min(h * 0.34, 150), color=BLUE,
               alpha=alpha, facing=1 if k == 0 else -1, arm=0.3)
    if ball_xy is not None:
        ball(c, x0 + w * ball_xy[0], y0 + h * ball_xy[1], max(5.0, h * 0.028), alpha=alpha, glow=0.8)


# =============================================================== 00 · title ===
def draw_title(c, t, x):
    # arc traced by the ball (comet tail, only behind the ball)
    pr = prog(t, 0.4, 3.0, out_cubic)
    n = 110
    for i in range(n + 1):
        u = i / n
        if u > pr:
            break
        age = (pr - u) * 3.4
        a = max(0.0, 1.0 - age) * 0.7
        if a <= 0.02:
            continue
        px, py = bezier((300, 820), (960, 300), (1620, 760), u)
        c.circle(px, py, 2.6 + 4.0 * (1 - age), fill=BALL, alpha=a * 0.55)
    bx, by = bezier((300, 820), (960, 300), (1620, 760), pr)
    ball(c, bx, by, 15, alpha=1.0, glow=0.9, rot=t * 1.6)

    # kicker
    k = prog(t, 1.0, 1.9)
    if k > 0:
        c.text(960, 300 - 18 * (1 - k), "TENNIS HIGHLIGHT CLIPPER  ·  ALGORITHM", size=22,
               kind="mono", color=DIM, alpha=k, anchor="mm", track=5)

    # title
    p = prog(t, 1.5, 2.5, out_cubic)
    if p > 0:
        c.text(960, 452 - 22 * (1 - p), "机器如何看懂", size=94, kind="zhb", color=INK,
               alpha=p, anchor="mm", track=3)
        c.text(960, 552 - 22 * (1 - p), "一场网球比赛", size=94, kind="zhb", color=INK,
               alpha=p, anchor="mm", track=3)
    # rule
    r = prog(t, 2.5, 3.3)
    if r > 0:
        c.line([(960 - 230 * r, 626), (960 + 230 * r, 626)], BALL, width=3, alpha=0.9 * r)
    s = prog(t, 2.7, 3.5)
    if s > 0:
        c.text(960, 672, "网球高光自动剪辑 · 算法拆解", size=36, kind="zh", color=MUTED, alpha=s, anchor="mm")

    # payoff: candidate clips assembling while the line is spoken
    base = prog(t, x.ls(0) + 4.6, x.ls(0) + 5.1)
    if base > 0:
        n = 17
        wbar, gap = 74, 12
        total = n * wbar + (n - 1) * gap
        x0 = 960 - total / 2
        for i in range(n):
            p = stagger(t, i, x.ls(0) + 4.6, 0.075, 0.5, out_back)
            if p <= 0:
                continue
            y = 866 + 26 * (1 - p)
            c.rect(x0 + i * (wbar + gap), y, x0 + i * (wbar + gap) + wbar, y + 30,
                   fill=BALL, alpha=min(1.0, p) * (0.55 + 0.45 * (i % 3 == 0)), radius=6)
        lab = prog(t, x.ls(0) + 5.7, x.ls(0) + 6.3)
        if lab > 0:
            c.text(960, 936, "42:17 素材  →  17 段候选", size=28, kind="mono", color=MUTED,
                   alpha=lab, anchor="mm", track=2)


# ============================================================= 01 · problem ===
def draw_problem(c, t, x):
    bx0, bx1, by = 210, 1710, 660
    bw = bx1 - bx0
    # preview window
    pv = prog(t, 0.15, 0.9, out_cubic)
    if pv > 0:
        c.push(1.0)
        y0 = 300 - 16 * (1 - pv)
        match_frame(c, bx0, y0, bx1, y0 + 300, alpha=pv)
        if pv > 0.99:
            # flicker inside the preview: content changes as the playhead scrubs
            for i in range(28):
                a = prog(t, x.ls(1) + i * 0.10, x.ls(1) + i * 0.10 + 0.14)
                if a <= 0 or a >= 1:
                    continue
                rng = np.random.RandomState(i * 977)
                match_frame(c, bx0 + 6, y0 + 6, bx0 + 6 + (bw - 12) * 0.30, y0 + 6 + 92,
                            alpha=a * 0.9, ball_xy=(rng.rand(), 0.25 + 0.4 * rng.rand()))
        c.text(bx0, 266, "素材预览", size=24, kind="zh", color=DIM, alpha=pv * 0.9, anchor="lm")

    # the source bar
    g = prog(t, 0.3, 1.0)
    if g > 0:
        c.rect(bx0, by, bx0 + bw * g, by + 46, fill=mix(BG, BG3, 0.9), alpha=0.95, radius=8)

    fill = prog(t, x.f(0, 0.2), x.f(0, 0.9), linear)
    if fill > 0:
        c.rect(bx0, by, bx0 + bw * fill, by + 46, fill=mix(BG2, BG3, 0.5), alpha=0.95, radius=8)
    # ticks
    for m in range(0, 45, 5):
        tx = mapx(bx0, bx1, 0, 42.3, m * 60)
        c.line([(tx, by + 46), (tx, by + 60)], DIM, width=2, alpha=0.7)
        c.text(tx, by + 68, "%d:00" % m, size=20, kind="mono", color=DIM, alpha=0.85, anchor="ma")

    # duration counter
    if fill > 0:
        secs = 42.3 * 60 * fill
        c.text(bx1, 600, mmss(secs), size=46, kind="mono", color=INK, alpha=0.95, anchor="rm")
        c.text(bx1, 548, "素材时长", size=24, kind="zh", color=DIM, alpha=0.9, anchor="rm")

    # scrub: a playhead racing left -> right while the second line is spoken
    ph = prog(t, x.f(1, 0.05), x.f(1, 0.85), linear)
    if ph > 0:
        hx = bx0 + bw * ph
        c.line([(hx, by - 26), (hx, by + 72)], BALL, width=3, alpha=0.95)
        c.circle(hx, by - 26, 7, fill=BALL, alpha=1.0)
        c.text(hx, by - 46, "第 %d 帧" % int(ph * 76000), size=22, kind="mono", color=BALL,
               alpha=0.9, anchor="mm")
        for i in range(6):
            a = prog(t, x.f(1, 0.05 + i * 0.13), x.f(1, 0.05 + i * 0.13 + 0.1))
            if 0 < a < 1:
                c.rect(bx0, by - 20, bx0 + bw * ph, by + 66, outline=PAPER, width=1.5,
                       alpha=(1 - a) * 0.10, radius=8)

    lab = prog(t, x.f(1, 0.35), x.f(1, 0.6))
    if lab > 0:
        chip(c, 960, 880, "从头看到尾   ·   42 分钟", size=30, fg=ORANGE, bg=mix(BG, ORANGE, 0.10),
             border=ORANGE, alpha=lab, anchor="mm")
    q = prog(t, x.f(1, 0.7), x.f(1, 0.95))
    if q > 0:
        c.text(960, 966, "而你并不知道，哪几段值得看", size=30, kind="zh", color=MUTED, alpha=q, anchor="mm")


# ============================================================= 02 · insight ===
def draw_insight(c, t, x):
    fx0, fx1 = 140, 1085
    px0, px1 = 1145, 1790
    cxs = (fx0 + fx1) / 2

    # ---- how much of the "rich" scene is dimmed away
    dim = prog(t, x.f(0, 0.5), x.f(0, 0.95))
    base = 1.0 - 0.62 * dim

    # ---- left: the court
    c.rect(fx0, 250, fx1, 830, fill=mix(BG, BG2, 0.5), outline=BG3, width=2, alpha=0.85, radius=12)
    crowd_a = 0.6 * (1 - dim)
    if crowd_a > 0.02:
        c.rect(fx0 + 4, 254, fx1 - 4, 330, fill=mix(BG, BG3, 0.85), alpha=crowd_a, radius=10)
        rng = np.random.RandomState(5)
        for _ in range(90):
            c.circle(fx0 + 12 + (fx1 - fx0 - 24) * rng.rand(), 260 + 64 * rng.rand(), 2.6,
                     fill=MUTED, alpha=crowd_a * 0.75)
        c.text(cxs, 292, "比分  ·  观众  ·  风向  ·  战术", size=26, kind="zh",
               color=mix(MUTED, BG, 0.35), alpha=crowd_a, anchor="mm")
    court(c, cxs, 790, 840, 400, alpha=base * 0.95, color=mix(BG3, PAPER, 0.28 * (1 - dim)))
    lx, rx = cxs - 215, cxs + 215
    pa = base
    player(c, lx, 782, h=140, color=BLUE, alpha=pa, facing=1, arm=0.45)
    player(c, rx, 782, h=140, color=BLUE, alpha=pa, facing=-1, arm=0.45)
    if crowd_a > 0.02:
        c.text(cxs, 900, "一台摄像机  ·  42 分钟  ·  你只想看几分", size=27, kind="zh",
               color=MUTED, alpha=crowd_a, anchor="mm")

    # ---- right: the ball-present signal
    c.rect(px0, 250, px1, 830, fill=mix(BG, BG2, 0.45), outline=BG3, width=2, alpha=0.85, radius=12)
    c.text(px0 + 34, 296, "球在场上吗？", size=30, kind="zh", color=INK, alpha=0.95, anchor="lm")

    ax0, ax1 = px0 + 62, px1 - 40
    yv1, yv0 = 460, 700
    axes = prog(t, x.f(1, 0.15), x.f(1, 0.6))
    if axes > 0:
        c.line([(ax0, yv0), (ax1, yv0)], DIM, width=2, alpha=axes * 0.85)
        c.line([(ax0, yv1 - 20), (ax0, yv0 + 8)], DIM, width=2, alpha=axes * 0.85)
        c.text(ax0 - 20, yv1, "1", size=27, kind="mono", color=MUTED, alpha=axes, anchor="rm")
        c.text(ax0 - 20, yv0, "0", size=27, kind="mono", color=MUTED, alpha=axes, anchor="rm")
        c.text(ax0 - 20, yv1 - 40, "有球", size=24, kind="zh", color=BALL, alpha=axes * 0.9, anchor="rm")
        c.text(ax0 - 20, yv0 + 38, "无球", size=24, kind="zh", color=RED, alpha=axes * 0.9, anchor="rm")

    # ---- the ball: idle (L1) then a rally (L2)
    t0, t1 = x.ls(2), x.le(2) + 0.25
    t_on = x.f(2, 0.07)
    t_off = x.f(2, 0.68)
    exit_t = x.f(2, 0.74)
    idle = prog(t, x.f(1, 0.2), x.f(1, 0.8)) * (1 - prog(t, t_on - 0.35, t_on + 0.15))
    bx, by = cxs, 620
    if idle > 0:
        ball(c, bx, by, 14, alpha=idle, glow=0.7 + 0.5 * pulse(t, 1.8), rot=t * 1.2)
        q = prog(t, x.f(1, 0.45), x.f(1, 0.9)) * idle
        if q > 0:
            arrow(c, bx + 40, by - 10, px0 - 14, 560, BALL, width=2.5, alpha=q * 0.7,
                  head=12, curve=-90)
            c.text((bx + px0) / 2 + 10, 470, "只需要这一个信号", size=24, kind="zh",
                   color=BALL, alpha=q * 0.9, anchor="mm")

    def SX(tt):
        return mapx(ax0, ax1, t0, t1, min(max(tt, t0), t1))

    if t > t0:
        step = [(SX(t0), yv0), (SX(t_on), yv0), (SX(t_on), yv1), (SX(t_off), yv1), (SX(t_off), yv0),
                (SX(t), yv0)]
        seg = [p for p in step if p[0] <= SX(t) + 0.5]
        if len(seg) >= 2:
            on_l = SX(min(t, t_off))
            if on_l > SX(t_on):
                c.rect(SX(t_on), yv1, on_l, yv0, fill=BALL, alpha=0.09)
            for i in range(len(seg) - 1):
                c.line([seg[i], seg[i + 1]], BALL, width=4, alpha=0.95)
            c.circle(SX(t), yv0 if (t < t_on or t > t_off) else yv1, 7, fill=BALL, alpha=0.9)
        if t > t_on:
            lab = prog(t, t_on + 0.3, t_on + 0.8)
            if lab > 0:
                c.text((SX(t_on) + SX(min(t_off, t))) / 2, yv1 - 34, "球在场 = 回合进行中",
                       size=24, kind="zh", color=BALL, alpha=lab, anchor="mm")
        if t > t_off:
            lab = prog(t, t_off + 0.25, t_off + 0.8)
            if lab > 0:
                c.text(SX(t_off) + 6, yv0 + 44, "球不见了 → 这一分结束", size=24, kind="zh",
                       color=RED, alpha=lab, anchor="lm")
    at = prog(t, x.f(1, 0.7), x.f(1, 1.1))
    if at > 0:
        c.text(ax1, yv0 + 46, "时间 →", size=24, kind="zh", color=DIM, alpha=at * 0.9, anchor="rm")

    # ---- the rally itself, on the same clock
    u = clamp01((t - t_on) / (t_off - t_on))
    if t > t_on:
        nh = 7
        seg2 = min(0.999, u) * nh
        i = int(seg2)
        f = seg2 - i
        byx = lx + 42 + (rx - lx - 84) * (f if i % 2 == 0 else 1 - f)
        byy = 782 - 140 * 0.62 - 4 * 96 * f * (1 - f)
        ex = prog(t, exit_t, exit_t + 1.1)
        if ex > 0:
            byx += 900 * ex
            byy -= 420 * ex
        if ex < 0.96:
            for k in range(1, 6):
                uu = clamp01(u - k * 0.014)
                s2 = min(0.999, uu) * nh
                i2, f2 = int(s2), s2 - int(s2)
                tx2 = lx + 42 + (rx - lx - 84) * (f2 if i2 % 2 == 0 else 1 - f2)
                ty2 = 782 - 140 * 0.62 - 4 * 96 * f2 * (1 - f2)
                c.circle(tx2, ty2, 4.4 - k * 0.7, fill=BALL, alpha=0.22 - k * 0.035)
            ball(c, byx, byy, 13, alpha=1.0, glow=1.0, rot=t * 2.4)

    # ---- the rally ribbon
    rib = prog(t, t_on + 0.5, t_off)
    if rib > 0:
        rw = (fx1 - 120) - (fx0 + 120)
        c.rect(fx0 + 120, 862, fx0 + 120 + rw * min(1.0, (t - t_on) / max(0.1, t_off - t_on)),
               894, fill=BALL, alpha=0.85, radius=8)
        c.text(fx0 + 120, 916, "一个回合", size=26, kind="zh", color=BALL, alpha=rib, anchor="lm")
        if t > t_off:
            c.text(fx0 + 330, 916, "·  球离开画面，信号归零", size=26, kind="zh", color=RED,
                   alpha=prog(t, t_off + 0.3, t_off + 0.9), anchor="lm")

    # ---- L0: "not about understanding tennis"
    sp = prog(t, x.f(0, 0.05), x.f(0, 0.4))
    if sp > 0:
        a = sp * (1 - prog(t, x.f(1, 0.1), x.f(1, 0.6)))
        if a > 0.02:
            strike(c, 340, 200, "看懂网球", size=52, color=INK, alpha=a,
                   p=prog(t, x.f(0, 0.35), x.f(0, 0.7)), thick=5)
            c.text(360 + c.tw("看懂网球", 52), 200, "  —— 这件事，程序不需要会",
                   size=30, kind="zh", color=MUTED, alpha=a * 0.9, anchor="lm")


# ============================================================ 03 · sampling ===
def draw_sampling(c, t, x):
    cols, rows = 15, 2
    cw, ch, gp = 106, 60, 10
    total_w = cols * cw + (cols - 1) * gp
    x0 = 960 - total_w / 2
    y0 = 268
    c.text(x0, 222, "以 30 fps 素材为例  ·  1 秒 = 30 帧", size=27, kind="zh", color=MUTED,
           alpha=0.9, anchor="lm")

    picked = set(range(0, 30, 6))  # 5 fps out of 30 fps
    for i in range(30):
        r, cc = divmod(i, cols)
        cx = x0 + cc * (cw + gp)
        cy = y0 + r * (ch + gp + 26)
        p = stagger(t, i, 0.25, 0.028, 0.45, out_cubic)
        if p <= 0:
            continue
        on = prog(t, x.f(1, 0.15 + i * 0.012), x.f(1, 0.30 + i * 0.012))
        keep = i in picked
        a = (0.28 + 0.72 * on) if keep else (1.0 - 0.72 * on)
        mini_frame(c, cx, cy - 6 * (1 - p), cw, ch - 6 * (1 - p), seed=i * 31,
                   alpha=p * a)
        if keep and on > 0.02:
            c.rect(cx - 3, cy - 3 - 6 * (1 - p), cx + cw + 3, cy + ch + 3 - 6 * (1 - p),
                   outline=BALL, width=2.5, alpha=on, radius=8)
        c.text(cx, cy + ch + 14, str(i), size=17, kind="mono", color=DIM,
               alpha=p * (0.9 if keep else 0.45), anchor="ma")

    # selection marker under the top row
    br = prog(t, x.f(1, 0.35), x.f(1, 0.75))
    if br > 0:
        for k, i in enumerate(sorted(picked)):
            r, cc = divmod(i, cols)
            cx = x0 + cc * (cw + gp) + cw / 2
            cy = y0 + r * (ch + gp + 26) + ch + 30
            p = stagger(t, k, x.f(1, 0.35), 0.05, 0.35, out_back)
            if p <= 0:
                continue
            c.circle(cx, cy, 5 * p, fill=BALL, alpha=p)
        c.text(960, y0 + 2 * (ch + gp + 26) + 34, "每秒 5 帧  ·  粗扫描", size=30, kind="zh",
               color=BALL, alpha=br, anchor="ma")

    # cost bar
    cb_y = 664
    full_w = 1100
    c.rect(960 - full_w / 2, cb_y, 960 + full_w / 2, cb_y + 34, fill=mix(BG, BG3, 0.6),
           alpha=0.9, radius=8)
    cost = 1.0 - (5 / 6) * prog(t, x.f(1, 0.55), x.f(1, 1.05))
    c.rect(960 - full_w / 2, cb_y, 960 - full_w / 2 + full_w * cost, cb_y + 34,
           fill=mix(ORANGE, BALL, prog(t, x.f(1, 0.6), x.f(1, 1.0))), alpha=0.95, radius=8)
    c.text(960 - full_w / 2, cb_y - 26, "检测量", size=26, kind="zh", color=MUTED, alpha=0.9, anchor="lm")
    c.text(960 + full_w / 2, cb_y - 26, "%d%%" % round(cost * 100), size=30, kind="mono",
           color=INK, alpha=0.95, anchor="rm")
    if 1 - cost > 0.5:   # show where a 60 fps source would land
        m60 = 960 - full_w / 2 + full_w * (5 / 60)
        c.line([(m60, cb_y - 10), (m60, cb_y + 44)], MUTED, width=2, alpha=0.8)
        c.text(m60, cb_y + 58, "60 fps 素材 8%", size=21, kind="zh", color=MUTED, alpha=0.85, anchor="ma")
    fa = prog(t, x.f(1, 0.8), x.f(1, 1.1))
    if fa > 0:
        chip(c, 960, 800, "30 fps → 1/6    ·    60 fps → 1/12", size=28, fg=BALL,
             bg=mix(BG, BALL, 0.10), border=BALL, alpha=fa, anchor="mm")


# ============================================================== 04 · detect ===
def draw_detect(c, t, x):
    fx0, fy0, fx1, fy1 = 130, 258, 1030, 764
    slide = prog(t, 0.1, 0.9, out_cubic)
    dx = -70 * (1 - slide)
    c.push(1.0, dx=dx)
    match_frame(c, fx0, fy0, fx1, fy1, alpha=slide, ball_xy=(0.62, 0.42), players=(0.28, 0.72))
    c.pop()

    scan = prog(t, x.f(0, 0.25), x.f(0, 0.95))
    if 0 < scan < 1:
        sy = fy0 + (fy1 - fy0) * scan
        c.rect(fx0, sy - 3, fx1, sy + 3, fill=BALL, alpha=0.55)
        for k in range(1, 30):
            yy = sy - k * 9
            if yy < fy0:
                break
            c.rect(fx0, yy, fx1, yy + 2, fill=BALL, alpha=0.16 * (1 - k / 30))
        c.rect(fx0, fy0, fx1, sy, outline=BALL, width=1.4, alpha=0.10)

    chip(c, fx0, fy0 - 30, "YOLOv8n  ·  imgsz 1024  ·  batch 8", size=24, fg=INK,
         bg=mix(BG, BG3, 0.8), border=BG3, alpha=prog(t, 0.2, 0.8), anchor="lm")

    # ---- boxes
    pb = prog(t, x.f(1, 0.05), x.f(1, 0.45), out_back)
    if pb > 0:
        for (bx, bw2, conf, delay) in ((0.28, 0.20, 0.93, 0.0), (0.72, 0.19, 0.88, 0.06)):
            p = prog(t, x.f(1, 0.05 + delay), x.f(1, 0.40 + delay), out_back)
            if p <= 0:
                continue
            x0 = fx0 + (fx1 - fx0) * (bx - bw2 / 2)
            x1 = fx0 + (fx1 - fx0) * (bx + bw2 / 2)
            y0, y1 = fy0 + (fy1 - fy0) * 0.32, fy0 + (fy1 - fy0) * 0.90
            bbox(c, x0, y0, x1, y1, BLUE, alpha=p, p=p, width=3.5)
            chip(c, x0, y0 - 22, "person  %.2f" % conf, size=22, fg=BG, bg=BLUE, alpha=p, anchor="lm")
    bb = prog(t, x.f(1, 0.5), x.f(1, 0.8), out_back)
    if bb > 0:
        bx = fx0 + (fx1 - fx0) * 0.62
        by = fy0 + (fy1 - fy0) * 0.42
        bbox(c, bx - 26, by - 26, bx + 26, by + 26, BALL, alpha=bb, p=bb, width=3.5)
        chip(c, bx + 34, by - 34, "sports ball  0.31", size=22, fg=BG, bg=BALL, alpha=bb, anchor="lm")
        if bb > 0.9:
            c.circle(bx, by, 34 + 8 * pulse(t, 1.6), outline=BALL, width=2, alpha=0.35 * pulse(t, 1.6))

    # ---- class legend / threshold
    lx = 1090
    lg = prog(t, x.f(1, 0.1), x.f(1, 0.6))
    if lg > 0:
        c.text(lx, 274, "模型返回两类目标", size=28, kind="zh", color=INK, alpha=lg, anchor="lm")
        for k, (name, cls, conf, col) in enumerate((("person", "class 0", "0.30", BLUE),
                                                    ("sports ball", "class 32", "0.10", BALL))):
            p = stagger(t, k, x.f(1, 0.2), 0.12, 0.5, out_cubic)
            if p <= 0:
                continue
            y = 340 + k * 108 - 14 * (1 - p)
            c.rect(lx, y, 1770, y + 84, fill=mix(BG, BG2, 0.7), outline=col, width=1.6,
                   alpha=p * 0.95, radius=10)
            c.rect(lx, y, lx + 6, y + 84, fill=col, alpha=p, radius=3)
            c.text(lx + 26, y + 26, name, size=30, kind="mono", color=col, alpha=p, anchor="lm")
            c.text(lx + 26, y + 60, cls, size=23, kind="mono", color=MUTED, alpha=p, anchor="lm")
            c.text(1770 - 22, y + 42, "conf ≥ " + conf, size=25, kind="mono", color=INK,
                   alpha=p * 0.9, anchor="rm")

    th = prog(t, x.f(2, 0.05), x.f(2, 0.55))
    if th > 0:
        gy = 620
        c.text(lx, gy - 34, "球的可信度门槛", size=28, kind="zh", color=INK, alpha=th, anchor="lm")
        c.rect(lx, gy, 1770, gy + 30, fill=mix(BG, BG3, 0.6), alpha=th * 0.9, radius=8)
        mark = mapx(lx, 1770, 0.0, 1.0, 0.10)
        c.rect(lx, gy, mark, gy + 30, fill=mix(RED, ORANGE, 0.3), alpha=th * 0.85, radius=8)
        c.line([(mark, gy - 16), (mark, gy + 46)], PAPER, width=3, alpha=th)
        c.text(mark, gy + 62, "0.10", size=26, kind="mono", color=PAPER, alpha=th, anchor="ma")
        bx2 = mapx(lx, 1770, 0.0, 1.0, 0.31)
        c.circle(bx2, gy + 15, 11, fill=BALL, alpha=th)
        c.text(bx2 + 20, gy - 22, "实际检测到 0.31", size=24, kind="mono", color=BALL, alpha=th, anchor="lm")

    em = prog(t, x.f(2, 0.55), x.f(2, 0.95))
    if em > 0:
        c.text(lx, 762, "网球在画面里只有十几个像素。", size=28, kind="zh", color=MUTED,
               alpha=em, anchor="lm")
        c.text(lx, 806, "门槛放低，宁可多看一眼。", size=28, kind="zh", color=MUTED,
               alpha=em, anchor="lm")


# ================================================================ 05 · gaps ===
PATTERN = [1, 1, 1, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1, 0, 1, 1, 1, 0, 1,
           1, 1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1]


def _dilated(pat, k=1):
    n = len(pat)
    return [1 if any(pat[max(0, i - k):min(n, i + k + 1)]) else 0 for i in range(n)]


def draw_gaps(c, t, x):
    n = len(PATTERN)
    bw, gp = 36, 6
    total = n * bw + (n - 1) * gp
    x0 = 960 - total / 2
    ya, yb = 430, 620

    c.text(x0, 344, "每秒 5 帧的检测结果  ·  8 秒", size=26, kind="zh", color=MUTED, alpha=0.9, anchor="lm")
    c.text(x0, 386, "看得见", size=24, kind="zh", color=DIM, alpha=0.9, anchor="lm")
    c.text(x0 + total + 22, 386, "", size=24)

    # raw detections
    for i in range(n):
        p = stagger(t, i, 0.2, 0.016, 0.35, out_cubic)
        if p <= 0:
            continue
        on = PATTERN[i]
        cx = x0 + i * (bw + gp)
        y = ya - 8 * (1 - p)
        c.rect(cx, y, cx + bw, y + bw, fill=BALL if on else mix(BG, BG3, 0.7),
               alpha=p * (0.92 if on else 0.9), radius=5)
        if not on:
            c.line([(cx + 9, y + 9), (cx + bw - 9, y + bw - 9)], RED, width=2.5, alpha=p * 0.75)
            c.line([(cx + bw - 9, y + 9), (cx + 9, y + bw - 9)], RED, width=2.5, alpha=p * 0.75)

    # motion blur / speed illustration
    mb = prog(t, x.f(0, 0.15), x.f(0, 0.8))
    if mb > 0:
        cx0, cx1 = x0 + 120, x0 + total - 120
        u = prog(t, x.f(0, 0.15), x.f(0, 0.8), linear)
        bx = cx0 + (cx1 - cx0) * u
        for k in range(8):
            c.circle(bx - k * 26, 250 + 10 * np.sin(k * 0.7), 9 - k * 0.6, fill=BALL,
                     alpha=mb * (0.5 - k * 0.055))
        ball(c, bx, 250, 10, alpha=mb, glow=0.8)
        c.text(cx1 + 30, 250, "球速可达 50 m/s", size=26, kind="zh", color=MUTED, alpha=mb, anchor="lm")

    # dilation
    dil = _dilated(PATTERN, 1)
    dp = prog(t, x.f(1, 0.05), x.f(1, 0.45))
    win = int(prog(t, x.f(1, 0.05), x.f(1, 0.75), linear) * (n - 1))
    if dp > 0:
        c.text(x0, yb - 78, "膨胀后的信号", size=26, kind="zh", color=MUTED, alpha=dp * 0.95, anchor="lm")
        for i in range(n):
            a = 1.0 if i <= win else 0.0
            if a <= 0:
                continue
            cx = x0 + i * (bw + gp)
            on = dil[i]
            c.rect(cx, yb, cx + bw, yb + bw, fill=BALL if on else mix(BG, BG3, 0.7),
                   alpha=0.9 * dp, radius=5)
            if PATTERN[i] == 0 and on:
                c.rect(cx, yb, cx + bw, yb + bw, outline=GREEN, width=2.5, alpha=dp, radius=5)

        # sliding 3-frame window
        wc = min(win, n - 2)
        wx = x0 + (wc - 1) * (bw + gp)
        c.rect(wx - 5, ya - 12, wx + 2 * (bw + gp) + bw + 5, ya + bw + 12, outline=PAPER,
               width=2.5, alpha=dp * 0.7, radius=8)
        c.text(wx + (3 * (bw + gp) - gp) / 2, ya - 34, "相邻 3 帧", size=22, kind="zh",
               color=PAPER, alpha=dp * 0.85, anchor="mm")
        for i in range(max(0, wc - 1), min(n, wc + 2)):
            cx = x0 + i * (bw + gp) + bw / 2
            c.line([(cx, ya + bw + 6), (x0 + wc * (bw + gp) + bw / 2, yb - 8)], GREEN,
                   width=1.6, alpha=dp * 0.35)

    rule = prog(t, x.f(1, 0.5), x.f(1, 0.85))
    if rule > 0:
        chip(c, 960, 800, "只要 3 帧里有 1 帧看到球   →   这 0.2 秒就算「有球」", size=28,
             fg=GREEN, bg=mix(BG, GREEN, 0.10), border=GREEN, alpha=rule, anchor="mm")
        c.text(960, 872, "远景漏检造成的空洞，被补上了", size=28, kind="zh", color=MUTED,
               alpha=prog(t, x.f(1, 0.75), x.f(1, 1.05)), anchor="mm")


# =============================================================== 06 · merge ===
RUNS = [(1.0, 3.2, 0.90), (4.4, 6.0, 0.85), (9.5, 12.8, 0.92), (14.0, 15.0, 0.70),
        (20.0, 21.2, 0.80), (25.0, 31.5, 0.90), (38.0, 39.0, 0.60), (43.0, 47.5, 0.12)]
T0, T1 = 0.0, 50.0
MERGED = [(1.0, 15.0), (20.0, 21.2), (25.0, 31.5), (38.0, 39.0), (43.0, 47.5)]
SURVIVE = [0, 2]


def draw_merge(c, t, x):
    ax0, ax1 = 150, 1790
    ytop = 470
    bh = 56

    def X(v):
        return mapx(ax0, ax1, T0, T1, v)

    # rules
    rr = prog(t, 0.1, 0.7)
    if rr > 0:
        for k, (s, col) in enumerate((("MAX_GAP_SEC  3.5s", BALL), ("MIN_RALLY_SEC  2.0s", GREEN),
                                      ("BALL_PRESENT_RATIO  0.25", VIOLET))):
            chip(c, ax0 + k * 360, 300, s, size=24, fg=col, bg=mix(BG, col, 0.10), border=col,
                 alpha=rr, anchor="lm")

    # axis
    ax = prog(t, 0.15, 0.8)
    if ax > 0:
        c.line([(ax0, ytop + bh + 44), (ax1, ytop + bh + 44)], DIM, width=2, alpha=ax * 0.8)
        for v in range(0, 51, 10):
            c.line([(X(v), ytop + bh + 44), (X(v), ytop + bh + 54)], DIM, width=2, alpha=ax * 0.7)
            c.text(X(v), ytop + bh + 62, "%ds" % v, size=20, kind="mono", color=DIM, alpha=ax * 0.8, anchor="ma")

    # raw runs
    for i, (a, b, ratio) in enumerate(RUNS):
        p = stagger(t, i, 0.25, 0.06, 0.4, out_back)
        if p <= 0:
            continue
        c.rect(X(a), ytop - 8 * (1 - p), X(b), ytop + bh, fill=BALL, alpha=p * 0.85, radius=6)
        c.text((X(a) + X(b)) / 2, ytop + bh / 2, "%.1fs" % (b - a), size=22, kind="mono",
               color=BG, alpha=p * 0.95, anchor="mm")

    # gaps
    gaps = [(RUNS[i][1], RUNS[i + 1][0]) for i in range(len(RUNS) - 1)]
    gp = prog(t, x.f(0, 0.15), x.f(0, 0.75))
    for i, (a, b) in enumerate(gaps):
        g = b - a
        merges = g <= 3.5
        if gp <= 0:
            continue
        p = stagger(t, i, x.f(0, 0.15), 0.09, 0.4)
        if p <= 0:
            continue
        col = GREEN if merges else RED
        my = ytop - 46
        c.line([(X(a), my), (X(b), my)], col, width=2.5, alpha=p * 0.9)
        c.line([(X(a), my - 8), (X(a), my + 8)], col, width=2, alpha=p * 0.9)
        c.line([(X(b), my - 8), (X(b), my + 8)], col, width=2, alpha=p * 0.9)
        c.text((X(a) + X(b)) / 2, my - 22, "%.1fs" % g, size=21, kind="mono", color=col,
               alpha=p, anchor="mm")
        if not merges:
            c.text((X(a) + X(b)) / 2, my - 46, "拆开", size=21, kind="zh", color=RED, alpha=p, anchor="mm")

    # merge animation
    mp = prog(t, x.f(0, 0.55), x.f(0, 1.05))
    if mp > 0:
        for i, (a, b) in enumerate(gaps):
            if b - a > 3.5:
                continue
            p = stagger(t, i, x.f(0, 0.55), 0.16, 0.45, out_cubic)
            if p <= 0:
                continue
            c.rect(X(a), ytop, X(a) + (X(b) - X(a)) * p, ytop + bh, fill=BALL, alpha=0.85, radius=6)

    # filtering
    fp = prog(t, x.f(1, 0.05), x.f(1, 0.9))
    if fp > 0:
        c.text(ax0, 660, "过滤", size=28, kind="zh", color=MUTED, alpha=fp, anchor="lm")
        for i, (a, b) in enumerate(MERGED):
            dur = b - a
            ratio = 0.12 if i == 4 else 0.85
            ok = dur >= 2.0 and ratio >= 0.25
            p = stagger(t, i, x.f(1, 0.05), 0.1, 0.4)
            if p <= 0:
                continue
            y = 700
            if ok:
                c.rect(X(a), y, X(b), y + bh, fill=mix(BALL, GREEN, 0.0), alpha=p * 0.9, radius=6)
            else:
                drop = prog(t, x.f(1, 0.35 + i * 0.08), x.f(1, 0.65 + i * 0.08), in_cubic)
                yy = y + 120 * drop
                aa = p * (1 - drop)
                c.rect(X(a), yy, X(b), yy + bh, fill=mix(BG, RED, 0.35), alpha=aa * 0.9, radius=6)
                reason = "%.1fs < 2.0s" % dur if dur < 2.0 else "球占比 12% < 25%"
                c.text((X(a) + X(b)) / 2, yy + bh + 26, reason, size=22, kind="mono",
                       color=RED, alpha=aa, anchor="ma")
        for k, i in enumerate(SURVIVE):
            a, b = MERGED[i]
            p = stagger(t, k, x.f(1, 0.45), 0.16, 0.45, out_back)
            if p <= 0:
                continue
            c.text((X(a) + X(b)) / 2, 690, "候选 %d" % (k + 1), size=24, kind="zh", color=GREEN,
                   alpha=p, anchor="mm")

    done = prog(t, x.f(2, 0.1), x.f(2, 0.8))
    if done > 0:
        chip(c, 960, 940, "8 段原始信号   →   5 段合并   →   2 段候选回合", size=30, fg=INK,
             bg=mix(BG, BG2, 0.9), border=BG3, alpha=done, anchor="mm")


# ============================================================== 07 · refine ===
SIGHTINGS = [-2.35, -2.20, -0.62, -0.48, -0.35, -0.20, -0.05, 0.95, 1.10, 1.25, 1.40,
             2.45, 2.60, 2.75, 2.88]
CLUSTERS = [(-2.45, -2.10, 2), (-0.72, 0.05, 5), (0.85, 1.50, 4), (2.35, 2.98, 4)]


def draw_refine(c, t, x):
    ax0, ax1 = 150, 1790
    P0, P1 = 330, 838
    Y_BALL, Y_CTICK, Y_CBAR, Y_FTICK, Y_DOT, Y_CLU, Y_FIN = 408, 470, 500, 578, 618, 648, 726

    def X(v):
        return mapx(ax0, ax1, -3.0, 3.0, v)

    wf = prog(t, 0.1, 0.7)
    if wf > 0:
        c.rect(ax0, P0, ax1, P1, fill=mix(BG, BG2, 0.45), outline=BG3, width=2,
               alpha=wf * 0.9, radius=12)
        c.text(ax0 + 24, P0 + 36, "候选边界 ± 3 秒", size=26, kind="zh", color=MUTED,
               alpha=wf, anchor="lm")
        c.text(ax1 - 24, P0 + 36, "边界 = 0s", size=24, kind="zh", color=DIM, alpha=wf, anchor="rm")
        c.line([(X(0), P0 + 56), (X(0), P1 - 18)], DIM, width=1.4, alpha=wf * 0.45)

    # ---- L0: the ball crosses the window far too fast for a 0.2 s grid
    ac = prog(t, x.f(0, 0.05), x.f(0, 0.55))
    gp = prog(t, 0.2, 0.8)
    if gp > 0:
        v = -3.0
        while v <= 3.0001:
            hot = abs(v) < 0.21
            col = RED if (hot and ac > 0.3) else DIM
            c.line([(X(v), Y_CTICK - 9), (X(v), Y_CTICK + 9)], col, width=2.2 if hot else 1.6,
                   alpha=gp * (0.95 if hot else 0.6))
            v += 0.2
        c.text(ax0 + 24, Y_CTICK + 40, "粗扫描   5 fps   =   0.2 秒一格", size=25, kind="mono",
               color=MUTED, alpha=gp, anchor="lm")
    if ac > 0:
        u = prog(t, x.f(0, 0.05), x.f(0, 0.75), linear)
        bx = X(-2.85 + 5.7 * u)
        for k in range(1, 8):
            c.circle(bx - k * 26, Y_BALL, 7.5 - k * 0.8, fill=BALL, alpha=ac * (0.34 - k * 0.038))
        ball(c, bx, Y_BALL, 11, alpha=ac, glow=0.9)
        c.text(ax1 - 24, Y_BALL - 34, "在这 0.2 秒里，球已经飞出去好几米", size=25, kind="zh",
               color=RED, alpha=ac, anchor="rm")

    # ---- the coarse candidate bar
    cp = prog(t, 0.35, 0.95)
    if cp > 0:
        c.rect(X(-0.25), Y_CBAR, X(0.45), Y_CBAR + 36, fill=mix(BALL, BG, 0.35), alpha=cp * 0.95,
               radius=6)
        c.text(X(0.45) + 16, Y_CBAR + 18, "粗扫描边界", size=24, kind="zh", color=MUTED,
               alpha=cp, anchor="lm")

    # ---- L1: densify with 20 fps
    ft = prog(t, x.f(1, 0.02), x.f(1, 0.5))
    if ft > 0:
        v = -3.0
        while v <= 3.0001:
            c.line([(X(v), Y_FTICK - 8), (X(v), Y_FTICK + 8)], BALL, width=1.1, alpha=ft * 0.6)
            v += 0.05
        chip(c, ax1 - 24, Y_FTICK - 46, "精修   20 fps   =   0.05 秒一格", size=25, fg=BALL,
             bg=mix(BG, BALL, 0.10), border=BALL, alpha=ft, anchor="rm")
        sw = prog(t, x.f(1, 0.2), x.f(1, 0.95), linear)
        sx = ax0 + (ax1 - ax0) * sw
        c.rect(ax0, Y_FTICK + 14, sx, Y_FTICK + 20, fill=BALL, alpha=ft * 0.3)
        c.line([(sx, Y_FTICK - 14), (sx, Y_FTICK + 26)], BALL, width=2, alpha=ft * 0.8)

    # ---- L2: sightings -> clusters
    sp = prog(t, x.f(1, 0.75), x.f(2, 0.35))
    if sp > 0:
        for j, v in enumerate(SIGHTINGS):
            seen = prog(t, x.f(1, 0.78 + j * 0.012), x.f(1, 0.86 + j * 0.012))
            if seen > 0.5:
                c.circle(X(v), Y_DOT, 6.5, fill=BALL, alpha=0.95)
    cl = prog(t, x.f(2, 0.1), x.f(2, 0.85))
    if cl > 0:
        for k, (a, b, cnt) in enumerate(CLUSTERS):
            small = cnt < 3
            p = stagger(t, k, x.f(2, 0.1), 0.12, 0.4, out_cubic)
            if p <= 0:
                continue
            kill = prog(t, x.f(2, 0.5 + k * 0.05), x.f(2, 0.7 + k * 0.05)) if small else 0.0
            col = RED if small else GREEN
            aa = p * (1 - kill)
            c.rect(X(a), Y_CLU, X(a) + (X(b) - X(a)) * p, Y_CLU + 20, outline=col, width=2,
                   alpha=aa * 0.9, radius=4)
            c.circle(X(a) + 9, Y_CLU + 50, 7.5, fill=col, alpha=aa)
            lab = ("只有 %d 次，丢弃" % cnt) if small else ("目击 %d 次" % cnt)
            c.text(X(a) + 24, Y_CLU + 50, lab, size=21, kind="zh", color=col, alpha=aa, anchor="lm")

    # ---- L3: pull the start back to the serve toss
    fl = prog(t, x.f(3, 0.02), x.f(3, 0.65))
    if fl > 0:
        c.rect(X(-2.4), Y_FIN, X(-2.4) + (X(2.9) - X(-2.4)) * fl, Y_FIN + 40, fill=GREEN,
               alpha=fl * 0.20, outline=GREEN, width=2, radius=8)
        c.text(X(2.9), Y_FIN - 14, "一个回合", size=25, kind="zh", color=GREEN, alpha=fl,
               anchor="rm")
    srv = prog(t, x.f(3, 0.3), x.f(3, 0.85), out_back)
    if srv > 0:
        px1 = X(-2.4)
        px0 = px1 - 150
        c.rect(px0, Y_FIN, px0 + (px1 - px0) * srv, Y_FIN + 40, fill=ORANGE, alpha=0.30,
               outline=ORANGE, width=2, radius=8)
        c.text((px0 + px1) / 2, Y_FIN - 16, "−0.8s 留白", size=22, kind="zh", color=ORANGE,
               alpha=srv, anchor="mm")
        player(c, px0 + 50, Y_FIN + 88, h=96, color=BLUE, alpha=srv, facing=1, arm=0.95)
        ball(c, px0 + 78, Y_FIN + 48 - 34 * prog(t, x.f(3, 0.4), x.f(3, 0.95)), 8,
             alpha=srv * 0.95, glow=0.7)
        c.text(px0, Y_FIN + 120, "发球抛球 · 被这 0.8 秒留白包住", size=22, kind="zh",
               color=ORANGE, alpha=srv, anchor="lm")


# ============================================================== 08 · export ===
CLIPS = [(0.00, 0.16), (0.20, 0.30), (0.34, 0.47), (0.51, 0.60), (0.64, 0.78), (0.82, 0.95)]


def draw_export(c, t, x):
    ax0, ax1 = 190, 1730
    ytop, bh = 430, 62

    def X(v):
        return ax0 + (ax1 - ax0) * v

    # ---- L0: pad handles + trim
    pad = prog(t, x.f(0, 0.05), x.f(0, 0.7))
    for i, (a, b) in enumerate(CLIPS):
        p = stagger(t, i, 0.15, 0.07, 0.4, out_back)
        if p <= 0:
            continue
        y = ytop - 10 * (1 - p)
        c.rect(X(a), y, X(b), y + bh, fill=mix(BALL, BG, 0.15), alpha=p * 0.9, radius=7)
        c.text((X(a) + X(b)) / 2, y + bh / 2, "C%d" % (i + 1), size=24, kind="mono", color=BG,
               alpha=p * 0.95, anchor="mm")
        if pad > 0:
            pp = stagger(t, i, x.f(0, 0.15), 0.07, 0.45, out_cubic)
            if pp > 0:
                lw_ = (X(b) - X(a)) * 0.14
                c.rect(X(a) - lw_ * pp, y, X(a), y + bh, fill=ORANGE, alpha=pp * 0.75, radius=7)
                c.rect(X(b), y, X(b) + lw_ * 0.8 * pp, y + bh, fill=ORANGE, alpha=pp * 0.75, radius=7)
                if i == 0:
                    c.text(X(a) - lw_ - 10, y + bh / 2, "−0.8s", size=22, kind="mono", color=ORANGE,
                           alpha=pp, anchor="rm")
                    c.text(X(b) + lw_ * 0.8 + 10, y + bh / 2, "+1.0s", size=22, kind="mono",
                           color=ORANGE, alpha=pp, anchor="lm")

    # ---- L1: uniform re-encode
    ff = prog(t, x.f(1, 0.02), x.f(1, 0.5))
    if ff > 0:
        chip(c, ax0, 300, "FFmpeg", size=28, fg=GREEN, bg=mix(BG, GREEN, 0.12), border=GREEN,
             alpha=ff, anchor="lm", kind="mono")
        for k, s in enumerate(("scale=1280:-2", "crf 21", "preset veryfast", "libx264")):
            p = stagger(t, k, x.f(1, 0.06), 0.09, 0.4)
            if p > 0:
                chip(c, ax0 + 190 + k * 250, 300, s, size=23, fg=MUTED, bg=mix(BG, BG2, 0.8),
                     border=BG3, alpha=p, anchor="lm", kind="mono")
    rp = prog(t, x.f(1, 0.45), x.f(1, 0.95))
    if rp > 0:
        c.rect(ax0 - 40, ytop - 26, ax1 + 40, ytop + bh + 26, outline=GREEN, width=2,
               alpha=rp * 0.4, radius=12)
        c.text(960, ytop + bh + 58, "统一参数重新编码  ·  每段都一样", size=26, kind="zh",
               color=GREEN, alpha=rp, anchor="mm")

    # ---- L2: selection + merge
    sel = [0, 2, 3, 4, 5]
    ticked = []
    for i, (a, b) in enumerate(CLIPS):
        cx = X(a) - 6
        p = prog(t, x.f(2, 0.03 + i * 0.09), x.f(2, 0.22 + i * 0.09), out_back)
        if p <= 0:
            continue
        on = i in sel
        c.rect(cx, ytop + bh + 26, cx + 26, ytop + bh + 52,
               fill=mix(BG, GREEN, 0.25) if on else mix(BG, BG3, 0.7),
               outline=GREEN if on else DIM, width=2, alpha=p, radius=6)
        if on:
            ticked.append(i)
            c.line([(cx + 6, ytop + bh + 40), (cx + 11, ytop + bh + 46), (cx + 20, ytop + bh + 32)],
                   BG, width=3.5, alpha=p)

    stack = prog(t, x.f(2, 0.45), x.f(2, 0.95), out_cubic)
    if stack > 0:
        for k, i in enumerate(ticked):
            a, b = CLIPS[i]
            w_ = (X(b) - X(a))
            ty = 700 - 7 * k * stack
            tx = 960 - w_ / 2
            c.rect(tx, ty, tx + w_, ty + 30, fill=mix(BALL, BG, 0.15), alpha=0.9 * stack, radius=5)
        c.rect(960 - 320, 694, 960 + 320, 706 + 6 * len(ticked) * stack,
               outline=PAPER, width=2, alpha=stack * 0.45, radius=12)
        fin = prog(t, x.f(2, 0.75), x.f(2, 1.1))
        if fin > 0:
            c.text(960, 880, "highlight.mp4", size=34, kind="mono", color=GREEN, alpha=fin, anchor="mm")
            c.rect(760, 914, 760 + 400 * fin, 928, fill=GREEN, alpha=0.9, radius=8)
            c.text(960, 960, "合并导出 · 5 段", size=25, kind="zh", color=MUTED, alpha=fin, anchor="mm")


# ============================================================== 09 · limits ===
def draw_limits(c, t, x):
    cards = [("远景快球 · 漏检", 0), ("慢镜头回放 · 假回合", 1), ("拍数估算 · 不可靠", 2)]
    cw, chh = 520, 330
    gap = 60
    total = 3 * cw + 2 * gap
    x0 = 960 - total / 2
    top = 250

    shrink = prog(t, x.f(3, 0.05), x.f(3, 0.6), out_cubic)
    scale = 1.0 - 0.42 * shrink
    dy = -70 * shrink

    for k, (title, kind) in enumerate(cards):
        p = stagger(t, k, x.f(k, 0.12), 0.0, 0.55, out_cubic)
        cx = x0 + k * (cw + gap) + cw / 2
        cy = top + chh / 2 + dy
        c.push(scale, cx, cy)
        shell = 0.30 + 0.70 * p
        # card
        c.rect(cx - cw / 2, cy - chh / 2, cx + cw / 2, cy + chh / 2,
               fill=mix(BG, BG2, 0.35 + 0.35 * p), outline=mix(RED, BG3, 0.62 - 0.30 * p),
               width=2, alpha=shell * 0.95, radius=16)
        c.rect(cx - cw / 2, cy - chh / 2, cx - cw / 2 + 6, cy + chh / 2, fill=RED,
               alpha=(0.25 + 0.6 * p), radius=3)
        c.text(cx - cw / 2 + 30, cy - chh / 2 + 42, title, size=29, kind="zh",
               color=mix(MUTED, INK, p), alpha=0.45 + 0.55 * p, anchor="lm")
        if p <= 0.001:
            c.pop()
            continue

        if kind == 0:
            mini_frame(c, cx - cw / 2 + 34, cy - 62, cw - 68, 150, seed=3, alpha=p * 0.9,
                       ball_on=False)
            bx, by = cx - 40, cy + 8
            for j in range(6):
                c.circle(bx + j * 26, by - j * 3.2, 3.4 - j * 0.3, fill=BALL,
                         alpha=p * (0.30 - j * 0.035))
            c.rect(bx + 22, by - 34, bx + 72, by + 34, outline=RED, width=2, alpha=p * 0.85)
            c.line([(bx + 34, by - 18), (bx + 60, by + 18)], RED, width=3, alpha=p * 0.95)
            c.line([(bx + 60, by - 18), (bx + 34, by + 18)], RED, width=3, alpha=p * 0.95)
            c.text(bx + 80, by - 12, "漏检", size=23, kind="zh", color=RED, alpha=p, anchor="lm")
            c.text(cx - cw / 2 + 34, cy + chh / 2 - 34, "高速 + 远景  →  这一帧没有球", size=23,
                   kind="zh", color=RED, alpha=p, anchor="lm")
        elif kind == 1:
            c.arc(cx, cy + 2, 44, 40, 320, VIOLET, width=4, alpha=p * 0.9)
            c.poly([(cx + 30, cy - 30), (cx + 48, cy - 24), (cx + 34, cy - 10)], fill=VIOLET, alpha=p * 0.9)
            c.rect(cx - 90, cy + 74, cx + 90, cy + 102, fill=mix(BG, RED, 0.4), alpha=p * 0.9, radius=5)
            c.text(cx, cy + 88, "假回合", size=24, kind="zh", color=PAPER, alpha=p, anchor="mm")
            c.text(cx - cw / 2 + 34, cy + chh / 2 - 34, "回放可能被当成新的一分", size=23,
                   kind="zh", color=RED, alpha=p, anchor="lm")
        else:
            pts = []
            rng = np.random.RandomState(9)
            v = 0.0
            for j in range(70):
                v += (1 if (j // 9) % 2 == 0 else -1) * 0.55 + rng.rand() * 0.12
                pts.append((cx - 120 + j * 3.5, cy - 10 + v * 6))
            for j in range(len(pts) - 1):
                col = BALL if pts[j][0] < cx + 16 else RED
                c.line([pts[j], pts[j + 1]], col, width=2.5, alpha=p * 0.85)
            c.line([(cx + 16, cy - 70), (cx + 16, cy + 62)], RED, width=2, alpha=p * 0.8)
            c.text(cx + 22, cy - 62, "镜头切换", size=21, kind="zh", color=RED, alpha=p, anchor="lm")
            c.text(cx - cw / 2 + 34, cy + chh / 2 - 34, "球在画面里翻来翻去  ÷ 2", size=23,
                   kind="zh", color=RED, alpha=p, anchor="lm")

    # human in the loop
    hp = prog(t, x.f(3, 0.35), x.f(3, 1.0))
    if hp > 0:
        c.rect(520, 720, 1400, 940, fill=mix(BG, BG2, 0.7), outline=BG3, width=2,
               alpha=hp * 0.95, radius=16)
        c.text(600, 768, "机器给候选", size=30, kind="zh", color=BALL, alpha=hp, anchor="lm")
        arrow(c, 800, 768, 900, 768, MUTED, width=3, alpha=hp * 0.9, head=14)
        c.text(930, 768, "你来定稿", size=30, kind="zh", color=GREEN, alpha=hp, anchor="lm")
        for k in range(5):
            bx = 600 + k * 150
            p = stagger(t, k, x.f(3, 0.5), 0.1, 0.4, out_back)
            if p <= 0:
                continue
            on = k != 3
            c.rect(bx, 830, bx + 46, 876, fill=mix(BG, GREEN, 0.25) if on else mix(BG, BG3, 0.7),
                   outline=GREEN if on else DIM, width=2, alpha=p, radius=8)
            if on:
                c.line([(bx + 10, 852), (bx + 20, 864), (bx + 36, 840)], BG, width=5, alpha=p)
            c.rect(bx + 60, 838, bx + 130, 868, fill=mix(BALL, BG, 0.25), alpha=p * 0.85, radius=5)
        c.text(960, 916, "它负责省时间，你负责做决定", size=26, kind="zh", color=MUTED, alpha=hp, anchor="mm")


# ============================================================= 10 · closing ===
RALLY_SPANS = [(0.04, 0.14), (0.18, 0.30), (0.34, 0.44), (0.48, 0.60), (0.64, 0.72),
               (0.76, 0.86), (0.89, 0.97)]
RULES = ["5 fps 粗扫描", "ball conf ≥ 0.10", "3 帧膨胀", "gap ≤ 3.5s", "时长 ≥ 2.0s",
         "球占比 ≥ 25%", "20 fps 精修", "−0.8s / +1.0s", "CRF 21"]


def draw_closing(c, t, x):
    bx0, bx1, by = 210, 1710, 640
    bw = bx1 - bx0

    # the whole footage returns
    g = prog(t, 0.15, 0.9, out_cubic)
    if g > 0:
        c.rect(bx0, by, bx0 + bw * g, by + 46, fill=mix(BG, BG3, 0.8), alpha=0.95, radius=8)

    # what the algorithm deliberately ignores
    disc = ["比分", "观众", "风向", "战术", "慢镜头回放"]
    dp = prog(t, x.f(0, 0.05), x.f(0, 0.5))
    dgone = 1 - prog(t, x.f(1, 0.0), x.f(1, 0.35))
    if dp > 0 and dgone > 0.02:
        tw_ = [c.tw(s_, 26) + 44 for s_ in disc]
        total_w = sum(tw_) + 20 * (len(disc) - 1)
        cxx = 960 - total_w / 2
        for k, s_ in enumerate(disc):
            p_ = stagger(t, k, x.f(0, 0.08), 0.07, 0.4, out_back)
            if p_ <= 0:
                continue
            w_ = tw_[k]
            yc = 528 + 14 * (1 - p_)
            c.rect(cxx, yc, cxx + w_, yc + 56, fill=mix(BG, BG2, 0.7), outline=BG3, width=2,
                   alpha=p_ * 0.9 * dgone, radius=12)
            c.text(cxx + w_ / 2, yc + 28, s_, size=26, kind="zh", color=MUTED,
                   alpha=p_ * 0.95 * dgone, anchor="mm")
            st = prog(t, x.f(0, 0.45 + k * 0.06), x.f(0, 0.68 + k * 0.06))
            if st > 0:
                c.line([(cxx + 12, yc + 28), (cxx + 12 + (w_ - 24) * st, yc + 28)], RED,
                       width=3, alpha=0.9 * dgone)
            cxx += w_ + 20

    # struck-through "看懂网球"
    sp = prog(t, x.f(0, 0.05), x.f(0, 0.45))
    if sp > 0:
        a = sp * (1 - prog(t, x.f(1, 0.0), x.f(1, 0.4)))
        if a > 0.02:
            strike(c, 700, 400, "看懂网球", size=56, color=mix(INK, BG, 0.2), alpha=a,
                   p=prog(t, x.f(0, 0.3), x.f(0, 0.75)), thick=5)

    # candidate rallies light up
    for k, (a, b) in enumerate(RALLY_SPANS):
        p = stagger(t, k, x.f(1, 0.05), 0.05, 0.4, out_cubic)
        if p <= 0:
            continue
        c.rect(bx0 + bw * a, by, bx0 + bw * a + (bw * (b - a)) * p, by + 46, fill=BALL,
               alpha=0.95, radius=8)

    lab = prog(t, x.f(1, 0.35), x.f(1, 0.9))
    if lab > 0:
        c.text(960, 560, "值得看的地方", size=34, kind="zh", color=BALL, alpha=lab, anchor="mm")
        c.text(bx0, by + 92, "0:00", size=22, kind="mono", color=DIM, alpha=lab, anchor="lm")
        c.text(bx1, by + 92, "42:17", size=22, kind="mono", color=DIM, alpha=lab, anchor="rm")

    # rules funnel
    rp = prog(t, x.f(2, 0.05), x.f(2, 0.75))
    if rp > 0:
        for k, s in enumerate(RULES):
            p = stagger(t, k, x.f(2, 0.05), 0.07, 0.45, out_back)
            if p <= 0:
                continue
            col = [BALL, BALL, GREEN, GREEN, GREEN, VIOLET, ORANGE, ORANGE, MUTED][k]
            yy = 210 + (k % 3) * 56
            xx = 300 + (k // 3) * 470
            c.push(1.0, dx=(1 - p) * (200 if k % 2 else -200))
            chip(c, xx, yy, s, size=24, fg=col, bg=mix(BG, col, 0.10), border=col, alpha=p,
                 anchor="lm", kind="mono")
            c.pop()
        fu = prog(t, x.f(2, 0.45), x.f(2, 0.85))
        if fu > 0:
            for k in range(3):
                c.line([(520 + k * 440, 386), (960, 460)], DIM, width=2, alpha=fu * 0.55)
            c.poly([(900, 452), (1020, 452), (960, 476)], fill=mix(BG, BALL, 0.5), alpha=fu * 0.9)
            c.line([(960, 476), (960, 636)], mix(BALL, BG3, 0.45), width=2, alpha=fu * 0.5)

    res = prog(t, x.f(2, 0.75), x.f(2, 1.05))
    if res > 0:
        c.text(960, 760, "42:17 素材   →   17 段候选", size=44, kind="mono", color=INK,
               alpha=res, anchor="mm")
        c.text(960, 826, "实测候选合计 37:27  ·  仍是四十二分钟里的一大半  ·  选哪几段，还是你定",
               size=26, kind="zh", color=MUTED, alpha=prog(t, x.f(2, 0.9), x.f(2, 1.2)), anchor="mm")


# ------------------------------------------------------------------- registry
DRAW = {
    "title": draw_title, "problem": draw_problem, "insight": draw_insight,
    "sampling": draw_sampling, "detect": draw_detect, "gaps": draw_gaps,
    "merge": draw_merge, "refine": draw_refine, "export": draw_export,
    "limits": draw_limits, "closing": draw_closing,
}
NO_CHAPTER = {"title", "closing"}
NO_CAPTION = {"title"}


def make_scenes(timing):
    """timing: {sid: dict(starts=..., durs=..., lead=..., tail=..., dur=...)}"""
    out = []
    for sid, title, lines in _narration_scenes():
        tm = timing[sid]
        ctx = Ctx(sid, title, lines, tm["starts"], tm["durs"], tm["lead"], tm["tail"], tm["dur"])
        out.append(Scene(sid, title, lines, tm["lead"], tm["tail"], DRAW[sid],
                         chapter=sid not in NO_CHAPTER, captions=sid not in NO_CAPTION, ctx=ctx))
    return out


def _narration_scenes():
    import narration
    return narration.SCENES
