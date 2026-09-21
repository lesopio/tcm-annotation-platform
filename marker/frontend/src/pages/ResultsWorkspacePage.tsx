import { BarChart3 } from "lucide-react";
import { Role, User } from "../api";
import { useWorkspaceBook, useWorkspaceTab, WorkspaceTab } from "../workspaceContext";
import QualityCenterPage from "./QualityCenterPage";
import KnowledgeGraphPage from "./KnowledgeGraphPage";
import ResearchCenterPage from "./ResearchCenterPage";

const qualityRoles: Role[] = ["admin", "reviewer", "expert", "data_engineer"];
const tabs: WorkspaceTab[] = [
  { key: "quality", label: "质量与裁决", roles: qualityRoles },
  { key: "graph", label: "知识图谱", roles: ["admin", "annotator", "reviewer", "expert", "data_engineer"] },
  { key: "research", label: "研究检索", roles: ["admin", "annotator", "reviewer", "expert", "data_engineer"] },
];
export default function ResultsWorkspacePage({ token, me }: { token: string; me: User }) {
  const { tab, setTab } = useWorkspaceTab("results", me.role, tabs, qualityRoles.includes(me.role) ? "quality" : "graph");
  const { books, bookId, selectBook } = useWorkspaceBook(token);
  return <div className="page-stack">
    <section className="workspace-tabs">{tabs.filter(item => item.roles.includes(me.role)).map(item => <button key={item.key} className={tab === item.key ? "active" : ""} onClick={() => setTab(item.key)}>{item.label}</button>)}</section>
    <section className="workspace-bookbar"><BarChart3 size={17} /><label>当前书籍<select value={bookId} onChange={e => selectBook(Number(e.target.value))}>{books.map(x => <option key={x.id} value={x.id}>{x.title}</option>)}</select></label></section>
    {tab === "quality" && <QualityCenterPage token={token} embedded bookId={bookId} onBookChange={selectBook} />}
    {tab === "graph" && <KnowledgeGraphPage token={token} embedded bookId={bookId} onBookChange={selectBook} />}
    {tab === "research" && <ResearchCenterPage token={token} embedded bookId={bookId} onBookChange={selectBook} />}
  </div>;
}
