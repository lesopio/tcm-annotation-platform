import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, BookOpen, Download, GitBranch, Play, Save, Send, Tags } from "lucide-react";
import { api, Assignment, Book, BookWorkflowRun, LabelDefinition, User, WorkflowTemplate } from "../api";
import { useWorkspaceTab, WorkspaceTab } from "../workspaceContext";
import { AssignmentsPanel, LabelsPanel } from "./ManagementPages";
import GuidelineCenterPage from "./GuidelineCenterPage";
import WorkflowDesigner from "./WorkflowDesigner";

const tabs: WorkspaceTab[] = [
  { key: "workflow", label: "工作流与任务发布", roles: ["admin"] },
  { key: "standards", label: "标签与规范", roles: ["admin"] },
  { key: "export", label: "数据导出", roles: ["admin"] },
];
/** 项目二级：单书处理台。 */
export default function BookDetailPage({ token, me }: { token: string; me: User }) {
  const { bookId } = useParams();
  const navigate = useNavigate();
  const id = Number(bookId);
  const [book, setBook] = useState<Book | null>(null), [error, setError] = useState("");
  const { tab, setTab } = useWorkspaceTab(`book-${id}`, me.role, tabs, "workflow");
  useEffect(() => { api.books(token).then(rows => { const found = rows.find(item => item.id === id); if (!found) { setError("书籍不存在或已被删除"); return; } setBook(found); }).catch(e => setError(e.message)); }, [token, id]);
  if (error) return <div className="page-stack"><div className="alert error">{error}</div><button className="secondary-button" onClick={()=>navigate("/projects")}><ArrowLeft size={16}/>返回书籍管理</button></div>;
  if (!book) return <div className="page-stack"><div className="empty-state"><BookOpen size={32}/><strong>正在载入书籍…</strong></div></div>;
  return <div className="page-stack">
    <section className="page-toolbar book-detail-head"><div><span className="eyebrow">BOOK #{book.id}</span><h1>{book.title}</h1><p>{book.page_count} 页 · {{pending:"生成页面中",recognizing:"识别中",ready:"就绪",failed:"失败"}[book.status] ?? book.status}</p></div><button className="secondary-button" onClick={()=>navigate("/projects")}><ArrowLeft size={17}/>返回书籍管理</button></section>
    <section className="workspace-tabs">{tabs.map(item => <button key={item.key} className={tab === item.key ? "active" : ""} onClick={() => setTab(item.key)}>{item.label}</button>)}</section>
    {tab === "workflow" && <WorkflowPanel token={token} book={book} />}
    {tab === "standards" && <StandardsPanel token={token} book={book} />}
    {tab === "export" && <ExportPanel token={token} book={book} />}
  </div>;
}

function WorkflowPanel({ token, book }: { token: string; book: Book }) {
  const [run, setRun] = useState<BookWorkflowRun | null>(null), [templates, setTemplates] = useState<WorkflowTemplate[]>([]), [versionId, setVersionId] = useState(0), [users, setUsers] = useState<User[]>([]), [assignments, setAssignments] = useState<Assignment[]>([]), [message, setMessage] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false), [designer, setDesigner] = useState(false);
  async function load() {
    try {
      const [templateResult, userRows] = await Promise.all([api.workflowTemplates(token), api.users(token)]);
      setTemplates(templateResult.items); setUsers(userRows);
      const published = templateResult.items.flatMap(x => x.published ? [{ id: x.published.id, label: `${x.name} v${x.published.version}` }] : []);
      setRun(await api.bookWorkflow(token, book.id).catch(() => null));
      setVersionId(current => current || published[0]?.id || 0);
      setAssignments(await api.bookAssignments(token, book.id).catch(() => []));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  useEffect(() => { load(); }, [token, book.id]);
  const published = templates.flatMap(x => x.published ? [{ id: x.published.id, label: `${x.name} v${x.published.version}` }] : []);
  async function bindOrUpgrade() {
    setBusy(true); setError(""); setMessage("");
    try {
      if (run) { const check = await api.checkWorkflowUpgrade(token, book.id, versionId); if (!check.ok) throw new Error(check.errors.join("；")); await api.upgradeBookWorkflow(token, book.id, versionId); }
      else await api.bindBookWorkflow(token, book.id, versionId);
      setMessage(run ? "工作流已升级" : "工作流已绑定"); await load();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  function showError(e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
  return <div className="workspace-stack">
    {error && <div className="alert error" onClick={()=>setError("")}>{error}</div>}{message && <div className="alert settings-success" onClick={()=>setMessage("")}>{message}</div>}
    <section className="content-card"><div className="card-heading"><div><span className="eyebrow">WORKFLOW</span><h2>工作流配置</h2></div><GitBranch size={21}/></div>
      <div className="semantic-picker">
        <label>流程版本<select value={versionId} onChange={e => setVersionId(Number(e.target.value))}>{published.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}</select></label>
        <button className="primary-button" disabled={busy || !versionId} onClick={bindOrUpgrade}><Send size={16}/>{run ? "检查并升级" : "绑定本书"}</button>
        <span className="muted">{run ? `当前版本 #${run.workflow_version_id}` : "尚未绑定工作流"}</span>
        <button className="secondary-button" onClick={() => setDesigner(!designer)}><Play size={16}/>{designer ? "收起模板设计器" : "编辑流程模板"}</button>
      </div>
      {run && <div className="data-table"><div className="table-row table-head"><span>节点</span><span>角色</span><span>进度</span><span>状态</span></div>
        {run.nodes.map(node => <div className="table-row" key={node.id}><span>{node.label}</span><span>{node.role}</span><span>{node.completed_pages}/{node.total_pages}</span><span><i className={`status-dot ${node.status}`}/>{node.status}</span></div>)}
      </div>}
    </section>
    {designer && <WorkflowDesigner token={token}/>}
    <div><div className="section-label"><Tags size={17}/><strong>人员任务发布</strong></div>
      <AssignmentsPanel token={token} book={book} users={users} assignments={assignments} onReload={()=>{api.bookAssignments(token, book.id).then(setAssignments).catch(showError); load();}} onError={showError}/>
    </div>
  </div>;
}

function StandardsPanel({ token, book }: { token: string; book: Book }) {
  const [labels, setLabels] = useState<LabelDefinition[]>([]), [error, setError] = useState("");
  useEffect(() => { api.bookLabels(token, book.id).then(setLabels).catch(e => setError(e.message)); }, [token, book.id]);
  function showError(e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
  return <div className="workspace-stack">
    {error && <div className="alert error" onClick={()=>setError("")}>{error}</div>}
    <section className="content-card"><div className="card-heading"><div><span className="eyebrow">LABELS</span><h2>{book.title} · 标签体系</h2></div></div>
      <LabelsPanel token={token} book={book} items={labels} setItems={setLabels} onError={showError}/>
    </section>
    <section className="content-card"><div className="card-heading"><div><span className="eyebrow">GUIDELINES</span><h2>标注规范</h2></div></div>
      <small className="muted block-note">标注规范为平台全局内容，各书共用。</small>
      <GuidelineCenterPage token={token} embedded/>
    </section>
  </div>;
}

function ExportPanel({ token, book }: { token: string; book: Book }) {
  const [error, setError] = useState("");
  function showError(e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
  return <div className="workspace-stack">
    {error && <div className="alert error" onClick={()=>setError("")}>{error}</div>}
    <section className="content-card"><div className="card-heading"><div><span className="eyebrow">EXPORT</span><h2>{book.title} · 数据导出</h2></div><Download size={21}/></div>
      <div className="semantic-picker">
        <button className="secondary-button" onClick={()=>api.exportFinal(token, book.id).catch(showError)}><Save size={16}/>导出 v2 页面数据包</button>
        <button className="secondary-button" onClick={()=>api.exportSemantic(token, book.id).catch(showError)}><Download size={16}/>导出 v3 语义与图谱</button>
      </div>
      <small className="muted block-note">页面数据包含已审核页面标注；语义包包含文本单元、实体、关系与医案。</small>
    </section>
  </div>;
}
