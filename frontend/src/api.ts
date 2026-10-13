export interface Clip {
  id: string;
  start: number;
  end: number;
  duration: number;
  approx_hits: number;
  video_url: string;
  thumb_url: string;
}

export interface ExportItem {
  id: string;
  clips: string[];
  url: string;
}

export interface VideoMeta {
  id: string;
  filename: string;
  duration: number;
  status: string;
  clips: Clip[];
  exports: ExportItem[];
  video_url: string;
}

export interface Job {
  id: string;
  kind: "analyze" | "export";
  status: "queued" | "running" | "done" | "failed";
  stage: string;
  progress: number;
  message: string;
  result: { clips?: number } | { url?: string } | null;
  error: string | null;
}

export async function uploadVideo(file: File): Promise<VideoMeta> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/videos", { method: "POST", body: form });
  if (!res.ok) throw new Error("上传失败: " + res.status);
  return res.json();
}

export async function startAnalysis(videoId: string): Promise<{ job_id: string }> {
  const res = await fetch(`/api/videos/${videoId}/analyze`, { method: "POST" });
  if (!res.ok) throw new Error("启动分析失败: " + res.status);
  return res.json();
}

export async function startExport(videoId: string, clipIds: string[]): Promise<{ job_id: string }> {
  const res = await fetch(`/api/videos/${videoId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clip_ids: clipIds }),
  });
  if (!res.ok) throw new Error("启动导出失败: " + res.status);
  return res.json();
}

export async function getJob(jobId: string): Promise<Job> {
  const res = await fetch(`/api/jobs/${jobId}`);
  if (!res.ok) throw new Error("查询任务失败: " + res.status);
  return res.json();
}

export async function getVideo(videoId: string): Promise<VideoMeta> {
  const res = await fetch(`/api/videos/${videoId}`);
  if (!res.ok) throw new Error("查询视频失败: " + res.status);
  return res.json();
}

export async function listVideos(): Promise<VideoMeta[]> {
  const res = await fetch("/api/videos");
  if (!res.ok) throw new Error("查询视频列表失败: " + res.status);
  return res.json();
}

export async function pollJob(jobId: string, onUpdate: (j: Job) => void, signal: AbortSignal): Promise<Job> {
  for (;;) {
    const job = await getJob(jobId);
    onUpdate(job);
    if (job.status === "done") return job;
    if (job.status === "failed") return job;
    await new Promise((r) => setTimeout(r, 700));
    if (signal.aborted) return job;
  }
}
