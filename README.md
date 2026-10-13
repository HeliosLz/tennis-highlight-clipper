# 🎾 网球高光自动剪辑 Tennis Highlight Clipper

上传本地网球比赛视频，AI 自动识别**得分回合**，剪出高光片段，勾选后一键合并导出集锦。
全部在本机处理，视频不会上传到任何服务器。

> 📐 下一步方向（逐分战术复盘 / AI 教练）见 [docs/ai-coach-design.md](docs/ai-coach-design.md)

## 工作流程

1. 上传视频（MP4 / MOV / MKV）
2. 后端以 5 fps 抽帧，用 **YOLOv8**（Apple MPS / CPU）检测**网球**和**球员**
3. 根据球的存在信号切分回合：连续的"球在场"区间 = 一个回合，长停顿 = 回合边界
4. 对每个候选回合在边界 ±3s 内以 20 fps 精修起止点（精确到发球抛球前的帧）
5. FFmpeg 按统一参数切割片段（含 ±0.8s 前后留白）+ 生成缩略图
6. 前端勾选片段 → 一键合并导出集锦

## 目录结构

```
backend/
  app/config.py        # 路径与算法参数（分析帧率、回合阈值、留白等）
  app/video.py         # PyAV 抽帧 + FFmpeg 切割/缩略图/合并（无系统 FFmpeg 时用内置二进制）
  app/detector.py      # YOLO 检测 + 回合切分算法
  app/pipeline.py      # 分析/导出流水线 + 元数据持久化
  app/jobs.py          # 后台任务管理（线程池）
  app/main.py          # FastAPI 接口
  data/                # 上传、片段、缩略图、导出（自动创建）
frontend/              # React + Vite + Tailwind 单页界面
```

## 快速开始

### 1. 后端

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8900
```

首次分析会自动下载 YOLOv8n 权重（约 6 MB）。

### 2. 前端

```bash
cd frontend
pnpm install
pnpm run dev        # http://localhost:5173
```

或直接运行 `./start.sh` 一键启动前后端。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/videos | 上传视频（multipart），返回 video_id |
| POST | /api/videos/{id}/analyze | 开始 AI 分析，返回 job_id |
| GET | /api/jobs/{id} | 查询任务进度（status/progress/stage） |
| GET | /api/videos/{id} | 获取片段列表与导出记录 |
| POST | /api/videos/{id}/export | 合并选中的片段，返回导出 job |
| DELETE | /api/videos/{id} | 删除视频及全部产物 |

## 可调参数（backend/app/config.py）

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| ANALYSIS_FPS | 5 | 粗扫描帧率（越高越准越慢） |
| REFINE_FPS / REFINE_WINDOW | 20 / 3s | 边界精修帧率与窗口 |
| BALL_PRESENT_RATIO | 0.25 | 回合内出现球的帧占比下限 |
| MIN_RALLY_SEC | 2.0 | 最短回合时长 |
| MAX_GAP_SEC | 3.5 | 大于此间隔拆分为两个片段 |
| CLIP_PAD_START / END | 0.8s / 1.0s | 片段前后留白 |
| CLIP_SCALE / CRF | 1280 / 21 | 导出分辨率与画质 |

## 已知限制

- 远景高速球检测有漏检：靠平滑窗口 + 回合连续性补偿
- 广播转播中的回放慢镜头可能被误判为短回合（由 MIN_RALLY_SEC 过滤）
- 「约 N 拍」在镜头切换频繁时可能不准
- 目前使用 COCO 预训练模型（person + sports ball），换用专门的网球检测模型（Roboflow Universe 等）可进一步提升精度：把模型名加进 detector.py 的 TENNIS_MODELS 即可

---

## 关于这个开源仓库

这个仓库公开的是**代码与设计文档**，不含任何视频素材：

- `backend/data/`（上传、切片、缩略图、导出，约 13 GB）与 `explainer/out/`（成品视频与配音，约 180 MB）
  都被 `.gitignore` 排除。素材是本人实拍的比赛录像，不上传，仓库里因此没有可播放的样例。
- 想跑起来：把一段自己的网球视频上传到前端，或放进 `backend/data/uploads/` 后再调分析接口。

设计文档都在 [`docs/`](docs/)：

| 文档 | 内容 |
| --- | --- |
| [`docs/ai-coach-design.md`](docs/ai-coach-design.md) | 从「高光剪辑」升级到「逐分战术复盘」的完整方案：机位与光学的量化依据、标定、球追踪、事件检测、分阶段验收标准，以及**已被实测否决**的方案清单 |
| [`docs/court-shooting-checklist.md`](docs/court-shooting-checklist.md) | 到球场一趟就能同时拿到标定素材与真值验证集的拍摄清单 |
| [`explainer/`](explainer/) | 从零手写的动画引擎（未用 Manim / After Effects），把这个回合检测算法做成一集 3 分 43 秒的解说视频 |

> 本仓库尚未添加 LICENSE。如果要让别人正式复用，建议补一个。
