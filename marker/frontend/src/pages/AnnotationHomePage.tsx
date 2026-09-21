import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, ClipboardCheck, PenLine } from "lucide-react";
import { api, Assignment, User } from "../api";
import { useWorkspace } from "../workspaceContext";
import TasksPage from "./TasksPage";

export default function AnnotationHomePage({ token, me }: { token: string; me: User }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const stepParam = Number(searchParams.get("step")) || 0;
  const { setAssignmentId } = useWorkspace();
  const [next, setNext] = useState<Assignment | null>(null), [error, setError] = useState("");
  const reviewer = me.role === "reviewer";
  useEffect(() => {
    let alive = true;
    (reviewer ? api.reviewAssignments(token) : api.myAssignments(token))
      .then(rows => { if (!alive) return; const actionable = rows.find(x => reviewer ? x.status === "submitted" : ["assigned", "returned", "in_progress"].includes(x.status)); setNext(actionable ?? null); })
      .catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [token, me.role]);
  const open = (id: number) => { setAssignmentId(id); navigate(`/work/${id}${stepParam ? `?step=${stepParam}` : ""}`); };
  const statusNames: Record<string, string> = { assigned: "待开始", in_progress: "进行中", submitted: "待审核", returned: "已打回", approved: "已通过" };
  return <div className="page-stack">
    {error && <div className="alert error">{error}</div>}
    <section className="content-card annotation-next">
      <div className="next-info">{reviewer ? <ClipboardCheck size={26} /> : <PenLine size={26} />}<div><span className="eyebrow">NEXT {reviewer ? "REVIEW" : "TASK"}</span><h2>{reviewer ? "下一项待审核" : "我的下一项任务"}</h2>{next ? <p>书籍 #{next.book_id} · 第 {next.page_no} 页 · {statusNames[next.status] ?? next.status} · 数据版本 v{next.version}</p> : <p>{reviewer ? "当前没有待审核任务。" : "当前没有分配给你的任务，新任务出现后会显示在这里。"}</p>}</div></div>
      {next && <button className="primary-button" onClick={() => open(next.id)}>{reviewer ? "继续审核" : "继续标注"}<ArrowRight size={17} /></button>}
    </section>
    <TasksPage token={token} me={me} onOpen={open} embedded view={reviewer ? "review" : "mine"} />
  </div>;
}
