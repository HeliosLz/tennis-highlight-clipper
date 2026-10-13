# 🎬 解说视频生成器 · Bespoke Explainer Video

一个**从零手写的动画引擎**，把本项目的回合检测算法做成一支 3b1b 风格的解说视频。
没有用 Manim、没有 After Effects、没有素材库 —— 每一帧都是代码算出来的。

```
out/explainer.mp4      ← 成品（1920×1080 · 30fps · H.264 + AAC · 3:43 · 124 MB）
out/script.md          ← 旁白脚本 + 实测时间轴（改文案的入口）
out/contact-sheet.png  ← 全部 30 句旁白对应的分镜缩略图（评审用）
```

## 为什么这样做

* **文字 → 图 → 网页 → 视频**。同一个算法，写成文档没人看，做成视频能讲清楚「为什么」。
* 这支视频是**一次性产物**：写它的成本约等于写一篇长文，但它能重复播放、能给别人看。
* 视频内容不是比喻，而是 `backend/app/detector.py` 里真实的参数与流程：
  5 fps 粗扫描、`BALL_CONF=0.10`、3 帧膨胀、`MAX_GAP_SEC=3.5`、`MIN_RALLY_SEC=2.0`、
  球占比 `0.25`、20 fps 边界精修、`CLIP_PAD 0.8/1.0`、`CRF 21`。

## 重新生成

```bash
cd explainer
PY=../backend/.venv/bin/python          # 已有 numpy / Pillow / PyAV / imageio-ffmpeg

$PY build.py audio      # 1. 合成旁白 + 测量时长 + 生成时间轴和脚本
$PY build.py sheet      # 2. 渲染 30 张分镜图，肉眼检查版式
$PY build.py render     # 3. 并行渲染全部帧 → 拼接 → 混音 → out/explainer.mp4
$PY still.py gaps 12    # 单帧调试： out/still_gaps.png
```

全流程无需联网、无需 API key、无需系统 FFmpeg
（FFmpeg 7.1 由 `imageio-ffmpeg` 自带），配音用 macOS 内置的 `Tingting` 中文语音。

## 改成别的主题

1. 改 `narration.py` 里的 `SCENES`：每行文字 = 一句配音 = 一条字幕 = 一个时间轴刻度。
2. 改 `scenes.py` 里的 `DRAW`：每个场景一个 `draw(canvas, t, ctx)` 函数。
3. `python build.py audio && python build.py render`。

时长不用手填：`build.py` 用 `say` 逐句合成、静音裁剪、实测时长，
再按 `LEAD / GAP / TAIL` 排布，视觉动画用 `ctx.f(i, 0.5)`（第 i 句的第 50%）对齐语音，
所以改文案不会让画面和声音脱节。

## 换成 ElevenLabs

`build.py` 里只有 `say_line()` 一个函数负责出声，替换它即可：

```python
def say_line(text, dst):
    r = requests.post(
        "https://api.elevenlabs.io/v1/text-to-speech/<voice_id>",
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"text": text, "model_id": "eleven_multilingual_v2",
              "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
    )
    dst.write_bytes(r.content)          # 后面全是自动的：测长、对齐、混音
```

缓存文件名带文案哈希，改一句只会重 synthesise 那一句。

## 结构

| 文件 | 作用 |
| --- | --- |
| `engine.py` | 绘图引擎：2× 超采样画布、缓动、径向光晕精灵、网球场/球/球员/检测框等图元 |
| `narration.py` | 旁白文案（唯一事实来源） |
| `scenes.py` | 11 个场景的导演脚本：`Ctx` 时间轴 + 每场一个 `draw()` |
| `build.py` | 配音、时间轴、并行渲染（7 进程 → 各自 ffmpeg 分段）、拼接、混音、QA 分镜 |
| `still.py` | 单帧渲染，调版式用 |
| `music.py` | 无 —— 背景音乐是 `build.py` 里用 numpy 现场合成的四和弦铺底，随人声自动闪避 |

## 实现要点

* **确定性渲染**：`frame(t)` 是纯函数，所以可以把 6684 帧切给 5 个进程，
  每个进程把 RGB 直接管进自己的 ffmpeg 编码成分段 mp4，最后 `-c copy` 拼接——
  不落盘原始帧（试过，要 39 GB）。实测 105 秒渲染完 6684 帧（63 帧/秒）。
* **超采样**：所有绘制在 3840×2160 上进行，2×2 box 降采样到 1080p（比 Lanczos 快 12 倍，效果等同），
  再叠一层静态抖动，避免暗部渐变在 H.264 里出现色带。
* **语音同步**：视觉不等估算时长，而是读实测的每句语音起止点。
* **音乐**：`Am7–F–Cmaj7–G` 正弦叠加 + 缓慢失谐，人声出现时侧链压低 55%，场景切换时一声轻铃。

## 事实核查

脚本里每一条技术断言都经过独立审计（对照 `config.py` / `detector.py` / `video.py` / `meta.json`），
并据此改掉了 5 处不严谨的说法：

| 原说法 | 问题 | 现在 |
| --- | --- | --- |
| 视频是每秒三十帧 / 降到六分之一 | 代码从不假设帧率；4 条真实素材里 2 条是 ~60 fps | 30 fps 降到 1/6，60 fps 降到 1/12 |
| 球的框，是那颗黄色的网球 | COCO `sports ball`，代码无颜色或网球判别 | 球的框，是模型认出的那个球 |
| 起点被拉到发球抛球之前 | 精修只取窗口内最早的目击，没有抛球检测 | 起点落在最早那次目击；包住抛球的是导出时 −0.8 s 留白 |
| 慢镜头回放会被当成新的一分 | 代码会按 `MIN_RALLY_SEC` 滤掉太短的回放 | 可能被当成新的一分；太短的会被时长下限挡掉 |
| 替你省下那四十二分钟 | 样本里 17 段候选合计 37:27，占 88.6% | 这四十二分钟，就不用你从头看到尾了（画面注明实测覆盖率） |
