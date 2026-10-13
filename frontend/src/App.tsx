import { useCallback, useEffect, useRef, useState } from "react";
import {
  type Clip, type Job, type VideoMeta,
  getVideo, listVideos, pollJob, startAnalysis, startExport, uploadVideo,
} from "./api";

const STAGE_LABELS: Record<string, string> = {
  detect: "AI 识别回合",
  cut: "切割片段",
  export: "合并导出",
};

function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export default function App() {
  const [video, setVideo] = useState<VideoMeta | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<Clip | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [library, setLibrary] = useState<VideoMeta[]>([]);
  const pollCtrl = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => pollCtrl.current?.abort();
  }, []);

  const refreshLibrary = useCallback(async () => {
    try {
      setLibrary(await listVideos());
    } catch {
      /* backend not ready yet */
    }
  }, []);

  useEffect(() => {
    refreshLibrary();
  }, [refreshLibrary]);

  const openVideo = (meta: VideoMeta) => {
    setVideo(meta);
    setSelected(new Set());
    setJob(null);
    setError(null);
  };

  const handleFile = useCallback(async (file: File) => {
    if (!file) return;
    if (!file.type.startsWith("video/") && !/\.(mp4|mov|mkv|avi|m4v|webm)$/i.test(file.name)) {
      setError("请选择视频文件（mp4 / mov / mkv 等）");
      return;
    }
    setError(null);
    setUploading(true);
    try {
      const meta = await uploadVideo(file);
      setVideo(meta);
      setSelected(new Set());
      setJob(null);
      refreshLibrary();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  }, []);

  const handleAnalyze = useCallback(async () => {
    if (!video) return;
    setError(null);
    try {
      const { job_id } = await startAnalysis(video.id);
      pollCtrl.current?.abort();
      const ctrl = new AbortController();
      pollCtrl.current = ctrl;
      setJob({ id: job_id, kind: "analyze", status: "queued", stage: "", progress: 0, message: "排队中", result: null, error: null });
      const done = await pollJob(job_id, (j) => setJob({ ...j }), ctrl.signal);
      if (done.status === "failed") {
        setError("分析失败: " + (done.error ?? "未知错误"));
        return;
      }
      const meta = await getVideo(video.id);
      setVideo(meta);
      setSelected(new Set());
      refreshLibrary();
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setJob(null);
    }
  }, [video]);

  const handleExport = useCallback(async () => {
    if (!video || selected.size === 0) return;
    setError(null);
    try {
      const ids = Array.from(selected);
      const { job_id } = await startExport(video.id, ids);
      pollCtrl.current?.abort();
      const ctrl = new AbortController();
      pollCtrl.current = ctrl;
      setJob({ id: job_id, kind: "export", status: "queued", stage: "export", progress: 0, message: "排队中", result: null, error: null });
      const done = await pollJob(job_id, (j) => setJob({ ...j }), ctrl.signal);
      if (done.status === "failed") {
        setError("导出失败: " + (done.error ?? "未知错误"));
        return;
      }
      const meta = await getVideo(video.id);
      setVideo(meta);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setJob(null);
    }
  }, [video, selected]);

  const toggleClip = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const clips = video?.clips ?? [];
  const selectedDuration = clips.filter((c) => selected.has(c.id)).reduce((a, c) => a + c.duration, 0);
  const busy = uploading || job?.status === "running" || job?.status === "queued";

  return (
    <div className="min-h-full flex flex-col">
      {/* header */}
      <header className="border-b border-lime-400/10 bg-black/30 backdrop-blur sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center gap-3">
          <span className="text-3xl">🎾</span>
          <div>
            <h1 className="text-lg font-bold tracking-wide text-lime-300">网球高光自动剪辑</h1>
            <p className="text-xs text-zinc-400">上传比赛视频 · AI 识别得分回合 · 一键导出集锦</p>
          </div>
          {video && (
            <button
              onClick={() => { setVideo(null); setSelected(new Set()); setError(null); }}
              className="ml-auto text-sm text-zinc-400 hover:text-white border border-zinc-700 rounded-lg px-3 py-1.5 transition"
            >
              ← 重新上传
            </button>
          )}
        </div>
      </header>

      <main className="flex-1 max-w-6xl w-full mx-auto px-6 py-8">
        {error && (
          <div className="mb-6 bg-red-500/10 border border-red-500/30 text-red-300 rounded-xl px-4 py-3 text-sm flex items-center gap-3">
            <span>⚠️</span><span>{error}</span>
            <button className="ml-auto hover:text-white" onClick={() => setError(null)}>✕</button>
          </div>
        )}

        {!video && (
          <>
            <UploadZone
              onFile={handleFile}
              uploading={uploading}
              dragOver={dragOver}
              setDragOver={setDragOver}
            />

            {library.length > 0 && (
              <div className="mt-12">
                <h3 className="font-semibold text-zinc-300 mb-4">📚 历史视频</h3>
                <div className="grid gap-3 md:grid-cols-2">
                  {library.map((v) => (
                    <button
                      key={v.id}
                      onClick={() => openVideo(v)}
                      className="text-left bg-zinc-900 border border-zinc-800 rounded-2xl px-5 py-4 hover:border-lime-400/50 transition group"
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-2xl">🎬</span>
                        <div className="min-w-0">
                          <div className="font-medium truncate">{v.filename}</div>
                          <div className="text-xs text-zinc-500 mt-0.5">
                            {v.duration ? fmtTime(v.duration) : ""}
                            {v.clips.length > 0 && (
                              <span className="text-lime-300 ml-2">
                                ✓ 已识别 {v.clips.length} 个回合
                              </span>
                            )}
                            {!v.clips.length && " · 待分析"}
                          </div>
                        </div>
                        <span className="ml-auto text-zinc-600 group-hover:text-lime-300 transition">→</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {video && !video.clips.length && !busy && (
          <div className="text-center py-16">
            <div className="text-5xl mb-4">🎬</div>
            <h2 className="text-xl font-semibold mb-2">{video.filename}</h2>
            <p className="text-zinc-400 mb-6">时长 {fmtTime(video.duration)} · 已上传，等待分析</p>
            <button
              onClick={handleAnalyze}
              className="tennis-green text-black font-bold rounded-xl px-8 py-3 text-lg hover:opacity-90 active:scale-95 transition shadow-lg shadow-lime-400/20"
            >
              🚀 开始 AI 分析
            </button>
            <p className="text-xs text-zinc-500 mt-4">分析速度取决于视频长度，M1 上约 1-2 分钟 / 10 分钟视频</p>
          </div>
        )}

        {video && busy && job && (
          <ProgressPanel job={job} filename={video.filename} />
        )}

        {video && clips.length > 0 && (
          <div>
            <div className="flex flex-wrap items-center gap-4 mb-6">
              <div>
                <h2 className="text-xl font-bold">{video.filename}</h2>
                <p className="text-sm text-zinc-400">
                  共识别 <span className="text-lime-300 font-semibold">{clips.length}</span> 个得分回合 · 已选{" "}
                  <span className="text-lime-300 font-semibold">{selected.size}</span> 个（{fmtTime(selectedDuration)}）
                </p>
              </div>
              <div className="ml-auto flex gap-2">
                <button
                  onClick={() => setSelected(clips.length === selected.size ? new Set() : new Set(clips.map((c) => c.id)))}
                  className="text-sm border border-zinc-700 rounded-lg px-3 py-1.5 hover:border-lime-400/50 transition"
                >
                  {clips.length === selected.size ? "取消全选" : "全选"}
                </button>
                <button
                  onClick={handleExport}
                  disabled={selected.size === 0 || busy}
                  className="tennis-green text-black font-bold rounded-lg px-5 py-1.5 disabled:opacity-40 disabled:cursor-not-allowed hover:opacity-90 active:scale-95 transition"
                >
                  ⬇ 导出集锦（{selected.size}）
                </button>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {clips.map((clip, i) => (
                <ClipCard
                  key={clip.id}
                  clip={clip}
                  index={i}
                  checked={selected.has(clip.id)}
                  onToggle={() => toggleClip(clip.id)}
                  onPreview={() => setPreview(clip)}
                />
              ))}
            </div>

            {video.exports.length > 0 && (
              <div className="mt-10">
                <h3 className="font-semibold mb-3 text-zinc-300">历史导出</h3>
                <div className="space-y-2">
                  {video.exports.map((e) => (
                    <a
                      key={e.id}
                      href={e.url}
                      download
                      className="flex items-center gap-3 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 hover:border-lime-400/40 transition group"
                    >
                      <span className="text-lime-300">🎥</span>
                      <span className="text-sm">集锦 {e.id.slice(0, 6)}（{e.clips.length} 个片段）</span>
                      <span className="ml-auto text-sm text-zinc-500 group-hover:text-lime-300">⬇ 下载</span>
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      <footer className="text-center text-xs text-zinc-600 py-6">
        基于 YOLO 视觉模型 · 本地处理，视频不会离开你的电脑
      </footer>

      {preview && <PreviewModal clip={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

/* ---------------------------------------------------------------- upload */
function UploadZone({ onFile, uploading, dragOver, setDragOver }: {
  onFile: (f: File) => void;
  uploading: boolean;
  dragOver: boolean;
  setDragOver: (b: boolean) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => { e.preventDefault(); setDragOver(false); onFile(e.dataTransfer.files[0]); }}
      className={`cursor-pointer rounded-3xl border-2 border-dashed transition-all p-16 text-center
        ${dragOver ? "border-lime-400 bg-lime-400/10 scale-[1.01]" : "border-zinc-700 bg-zinc-900/40 hover:border-lime-400/50"}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(e) => onFile(e.target.files?.[0] as File)}
      />
      <div className="text-6xl mb-4">{uploading ? "⏳" : "📼"}</div>
      <h2 className="text-2xl font-bold mb-2">{uploading ? "正在上传…" : "拖入网球比赛视频"}</h2>
      <p className="text-zinc-400 mb-6">或点击选择文件 · 支持 MP4 / MOV / MKV，建议 1080p 及以上</p>
      <span className="tennis-green text-black font-bold rounded-xl px-6 py-2.5 inline-block">
        选择视频文件
      </span>
    </div>
  );
}

/* --------------------------------------------------------------- progress */
function ProgressPanel({ job, filename }: { job: Job; filename: string }) {
  const pct = Math.round(job.progress * 100);
  const stageLabel = STAGE_LABELS[job.stage] ?? "处理中";
  return (
    <div className="max-w-xl mx-auto py-16">
      <h2 className="text-xl font-bold mb-1">{filename}</h2>
      <p className="text-zinc-400 mb-8 text-sm">
        {job.kind === "export" ? "正在合并选中片段…" : "AI 正在识别得分回合…"}
      </p>
      <div className="mb-3 flex justify-between text-sm">
        <span className="text-lime-300 font-semibold">{stageLabel}</span>
        <span className="text-zinc-400">{pct}%</span>
      </div>
      <div className="h-3 rounded-full bg-zinc-800 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-lime-400 to-green-400 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-zinc-500 text-xs mt-3">{job.message || "…"}</p>
      {job.status === "failed" && <p className="text-red-400 text-sm mt-4">失败：{job.error}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ card */
function ClipCard({ clip, index, checked, onToggle, onPreview }: {
  clip: Clip;
  index: number;
  checked: boolean;
  onToggle: () => void;
  onPreview: () => void;
}) {
  return (
    <div
      className={`group relative rounded-2xl overflow-hidden border transition-all cursor-pointer bg-zinc-900
        ${checked ? "border-lime-400 shadow-lg shadow-lime-400/10" : "border-zinc-800 hover:border-zinc-600"}`}
      onClick={onPreview}
    >
      <div className="aspect-video bg-zinc-800 relative">
        <img
          src={clip.thumb_url}
          alt={`回合 ${index + 1}`}
          loading="lazy"
          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
        />
        <span className="absolute top-2 right-2 bg-black/70 text-white text-xs font-mono px-2 py-0.5 rounded-md">
          {fmtTime(clip.duration)}
        </span>
        <span className="absolute top-2 left-2 bg-lime-400 text-black text-xs font-bold px-2 py-0.5 rounded-md">
          #{index + 1}
        </span>
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition flex items-center justify-center opacity-0 group-hover:opacity-100">
          <span className="text-3xl">▶</span>
        </div>
      </div>
      <div className="p-3 flex items-center gap-2">
        <button
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
          className={`w-5 h-5 rounded-md border flex items-center justify-center text-xs shrink-0 transition
            ${checked ? "bg-lime-400 border-lime-400 text-black" : "border-zinc-600 text-transparent"}`}
        >
          ✓
        </button>
        <div className="text-sm">
          <div className="font-medium text-zinc-200">
            回合 {index + 1}
            {clip.approx_hits > 0 && (
              <span className="text-zinc-500 font-normal ml-2">约 {clip.approx_hits} 拍</span>
            )}
          </div>
          <div className="text-xs text-zinc-500 font-mono">
            {fmtTime(clip.start)} - {fmtTime(clip.end)}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- modal */
function PreviewModal({ clip, onClose }: { clip: Clip; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div className="max-w-3xl w-full" onClick={(e) => e.stopPropagation()}>
        <video
          src={clip.video_url}
          controls
          autoPlay
          loop
          className="w-full rounded-2xl shadow-2xl max-h-[70vh] bg-black"
        />
        <div className="flex items-center gap-4 mt-4 text-sm text-zinc-300">
          <span>🎾 回合片段</span>
          <span className="text-zinc-500">时长 {fmtTime(clip.duration)}</span>
          {clip.approx_hits > 0 && <span className="text-zinc-500">约 {clip.approx_hits} 拍</span>}
          <span className="text-zinc-500 font-mono">{fmtTime(clip.start)} - {fmtTime(clip.end)}</span>
          <a
            href={clip.video_url}
            download
            className="ml-auto tennis-green text-black font-bold rounded-lg px-4 py-1.5"
          >
            ⬇ 下载片段
          </a>
        </div>
      </div>
    </div>
  );
}
