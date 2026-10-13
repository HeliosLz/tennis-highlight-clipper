# -*- coding: utf-8 -*-
"""Render one full-resolution still for visual QA.

    python still.py <scene_id> <t> [out.png]     # t = seconds from scene start
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine import Canvas, caption  # noqa: E402
import scenes as S  # noqa: E402

d = json.loads((HERE / "out" / "timeline.json").read_text())
timing, total = d["timing"], d["total"]
SCENES = S.make_scenes(timing)
by_id = {s.id: s for s in SCENES}

sid = sys.argv[1]
tl = float(sys.argv[2])
dst = Path(sys.argv[3]) if len(sys.argv) > 3 else HERE / "out" / ("still_%s.png" % sid)
sc = by_id[sid]
c = Canvas()
sc.draw(c, tl, sc.ctx)
if sc.chapter:
    S.chapter(c, sc.title, alpha=1.0)
if sc.captions:
    for i in range(len(sc.ctx.starts)):
        if sc.ctx.ls(i) - 0.35 <= tl < sc.ctx.le(i) + 0.55:
            txt = sc.lines[i]
            size = 34
            while c.tw(txt, size) > 1560 and size > 22:
                size -= 2
            caption(c, txt, alpha=0.98, size=size)
            break
c.finish().save(dst)
print(dst, "scene=%s t=%.2f dur=%.2f lines=%d" % (sid, tl, sc.ctx.dur, len(sc.ctx.starts)))
