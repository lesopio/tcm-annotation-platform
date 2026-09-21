import { useEffect, useRef, useState } from "react";
import { CheckCircle2, LoaderCircle, TriangleAlert, X } from "lucide-react";
import { api, PlatformJob } from "../api";

export type ToastJob = { id: number; title: string } | null;

/** 左下角进度通知：轮询平台任务，展示进度条与阶段日志，失败/完成后自动消失。 */
export default function ProgressToast({ token, job, onDone }: { token: string; job: ToastJob; onDone?: (job: PlatformJob) => void }) {
  const [detail, setDetail] = useState<PlatformJob | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  const closeTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!job) { setDetail(null); return; }
    setDetail(null);
    let stopped = false;
    const poll = async () => {
      try {
        const row = await api.platformJobDetail(token, job.id);
        if (stopped) return;
        setDetail(row);
        if (["succeeded", "failed", "cancelled"].includes(row.status)) {
          onDone?.(row);
          closeTimer.current = window.setTimeout(() => { if (!stopped) setDetail(null); }, row.status === "succeeded" ? 3000 : 8000);
          return;
        }
      } catch { /* 轮询失败静默重试 */ }
      if (!stopped) window.setTimeout(poll, 1000);
    };
    poll();
    return () => { stopped = true; if (closeTimer.current) clearTimeout(closeTimer.current); };
  }, [token, job?.id]);

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [detail]);

  if (!job || !detail) return null;
  const result = detail.result ?? {};
  const logs: string[] = Array.isArray(result.logs) ? (result.logs as string[]) : [];
  const stage = typeof result.stage === "string" ? result.stage : "";
  const done = detail.status === "succeeded", failed = detail.status === "failed" || detail.status === "cancelled";
  return <div className={`toast-progress${done ? " done" : ""}${failed ? " failed" : ""}`}>
    <div className="toast-head">
      <span className="toast-icon">{done ? <CheckCircle2 size={17}/> : failed ? <TriangleAlert size={17}/> : <LoaderCircle className="spin" size={17}/>}</span>
      <strong>{job.title}</strong>
      <small>{done ? "已完成" : failed ? "失败" : detail.status === "running" ? "运行中" : "排队中"}</small>
      <button className="toast-close" aria-label="关闭" onClick={() => setDetail(null)}><X size={14}/></button>
    </div>
    <div className="toast-bar"><progress max={100} value={detail.progress}/><span>{detail.progress}%</span></div>
    {stage && <div className="toast-stage">{stage}</div>}
    {logs.length > 0 && <div className="toast-logs" ref={logRef}>{logs.map((line, index) => <span key={index}>{line}</span>)}</div>}
    {failed && detail.error && <div className="toast-error">{detail.error}</div>}
  </div>;
}
