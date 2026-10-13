# -*- coding: utf-8 -*-
"""Narration script — the single source of truth for text, timing and captions.

Every line below becomes exactly one TTS utterance, one caption, and one row of
the timeline. Facts are taken from backend/app/{config,detector,video}.py.
Edit the text here and re-run build.py; nothing else needs to change.
"""

VOICE = "Tingting"     # macOS zh_CN voice
RATE = 180             # words/min; measure chars/sec with calibrate.py

LEAD_FIRST = 3.2       # music-only beat before the first line of the video
LEAD = 0.55            # silence before the first line of a scene
TAIL = 1.65            # silence after the last line of a scene
GAP = 0.30             # silence between two lines inside a scene
TAIL_LAST = 3.0        # longer hold on the closing card

# Each scene: (id, title, [lines])
SCENES = [
    ("title", "标题", [
        "一个程序，如何自己看完一场网球比赛，然后告诉你：哪几段值得看。",
    ]),

    ("problem", "问题", [
        "你录下一场网球比赛。四十二分钟，从第一分到最后一分。",
        "想剪出高光，你得自己从头看到尾。",
    ]),

    ("insight", "核心洞察", [
        "但剪辑真正需要的，不是看懂网球。",
        "它只需要回答一个更小的问题：球，还在不在场上。",
        "球在场，回合就在进行；球不见了，这一分就结束了。",
    ]),

    ("sampling", "第一步 · 抽帧", [
        "素材通常是每秒三十帧，或者六十帧。逐帧检测太慢，也没有必要。",
        "程序每秒只取五帧做粗扫描。三十帧的素材，检测量降到六分之一；六十帧的，降到十二分之一。",
    ]),

    ("detect", "第二步 · 检测", [
        "每一帧都送进一个 YOLOv8 模型。",
        "它返回两类目标：人的框，是场上的球员；球的框，是模型认出的那个球。",
        "球的判定门槛放得很低：可信度超过百分之十，就算数。因为网球实在太小了。",
    ]),

    ("gaps", "第三步 · 补漏", [
        "问题是，球飞得很快，镜头又远。有些帧看得到球，有些帧看不到。",
        "于是程序把这段信号做一次膨胀：相邻三帧里，只要有一帧看到球，就认为球还在场上。",
    ]),

    ("merge", "第四步 · 合并", [
        "接着，把这些有球的片段接起来。两段之间不超过三点五秒，就并成一段。",
        "短于两秒，或者球出现得太少的片段，直接丢掉。",
        "留下来的，就是候选回合。",
    ]),

    ("refine", "第五步 · 精修", [
        "但粗扫描的边界不够准。五分之一秒里，球能飞出去好几米。",
        "程序回到原视频，在候选边界的前后三秒里，用每秒二十帧重扫一遍。",
        "连续三次以上看到球，才算一次真正的目击；相邻的目击，再聚成一个回合。",
        "于是起点落在最早的那次目击上。而真正包住发球抛球的，是导出时那零点八秒的留白。",
    ]),

    ("export", "第六步 · 导出", [
        "最后交给 FFmpeg。候选片段先补上留白：起点往前零点八秒，终点往后一秒。",
        "再统一缩放到一千二百八十像素宽，用 CRF 二十一重新编码。",
        "你勾选想要的片段，它们会被合并成一个文件。",
    ]),

    ("limits", "边界", [
        "它当然不完美。远处的快球，会漏检。",
        "转播里的慢镜头回放，可能被当成新的一分；太短的回放，会被时长下限挡掉。",
        "球拍数，只是球在画面里左右翻转的次数除以二。镜头一切，就不准了。",
        "这些误差，一部分被平滑和时长下限挡住，剩下的，交给你勾选。",
    ]),

    ("closing", "结语", [
        "所以整件事的重点是：程序不需要看懂网球。",
        "它只需要知道，哪里值得看。",
        "而把「值得」翻译成几条可以计算的规则，这四十二分钟，就不用你从头看到尾了。",
    ]),
]


def line_starts(durs, lead=None, gap=GAP):
    """Absolute start time of each line inside a scene, given measured durations."""
    if lead is None:
        lead = LEAD
    out, t = [], lead
    for d in durs:
        out.append(t)
        t += d + gap
    return out


def scene_duration(durs, lead=None, gap=GAP, tail=None):
    if lead is None:
        lead = LEAD
    if tail is None:
        tail = TAIL
    if not durs:
        return lead + tail
    return lead + sum(durs) + gap * (len(durs) - 1) + tail
