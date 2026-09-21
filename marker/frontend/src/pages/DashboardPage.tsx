import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BarChart3, Beaker, BookOpen, CheckCircle2, ClipboardCheck, Clock3, FileStack, GitCompareArrows, ListTodo, Network, PenLine, RotateCcw, ScanText } from "lucide-react";
import { api, DashboardData, PlatformJob, User } from "../api";
import { useWorkspaceTab, WorkspaceTab } from "../workspaceContext";
import TasksPage from "./TasksPage";

const labels:Record<string,string>={books:"书籍",pages:"总页数",ready:"待处理",in_progress:"进行中",submitted:"待审核",approved:"已通过",returned:"已打回",ocr_running:"OCR 批次"};
const icons=[BookOpen,FileStack,Clock3,ScanText,CheckCircle2,RotateCcw];
const tabs: WorkspaceTab[] = [
  { key: "todo", label: "待办标注", roles: ["admin", "annotator", "reviewer", "expert", "data_engineer"] },
  { key: "reviews", label: "待审核", roles: ["reviewer"] },
  { key: "recent", label: "最近记录", roles: ["admin", "annotator", "reviewer", "expert", "data_engineer"] },
];
const jobLabels:Record<string,string>={ocr_preview:"OCR 预览",semantic_preannotation:"语义预标注",graph_build:"图谱构建",export:"数据导出",batch_ocr:"批量预处理"};

export default function DashboardPage(props:{token:string;me:User;onOpen:(id:number)=>void}){
  return props.me.role==="admin" ? <AdminConsole {...props}/> : <PersonalDashboard {...props}/>;
}

function AdminConsole({token,me}:{token:string;me:User}){
  const navigate=useNavigate();
  const [data,setData]=useState<DashboardData|null>(null),[jobs,setJobs]=useState<PlatformJob[]>([]),[error,setError]=useState("");
  useEffect(()=>{api.dashboard(token).then(setData).catch(e=>setError(e.message));},[token]);
  useEffect(()=>{api.platformJobs(token).then(rows=>setJobs(rows.slice(0,5))).catch(()=>setJobs([]));},[token]);
  const keys=["books","pages","ready","submitted","returned","ocr_running"];
  return <div className="page-stack"><section className="welcome-card"><div><span className="eyebrow">控制台</span><h1>{me.display_name||me.username}，欢迎回来</h1><p>书籍管理、预处理、流程发布与平台任务从这里出发。</p></div><div className="paper-seal"><BookOpen size={38}/></div></section>
    {error&&<div className="alert error">{error}</div>}
    <section className="stat-grid">{keys.map((key,index)=>{const Icon=icons[index%icons.length];return <article className="stat-card" key={key}><span className="stat-icon"><Icon size={21}/></span><div><strong>{data?.stats[key]??"—"}</strong><small>{labels[key]}</small></div></article>;})}</section>
    <section className="console-grid">
      <button className="console-card" onClick={()=>navigate("/projects")}><BookOpen size={24}/><strong>项目管理</strong><span>上传、预处理、删除书籍</span></button>
      <button className="console-card" onClick={()=>navigate("/annotation")}><PenLine size={24}/><strong>标注工作台</strong><span>处理任务与审核队列</span></button>
      <button className="console-card" onClick={()=>navigate("/task-center")}><ListTodo size={24}/><strong>任务中心</strong><span>平台任务与批次详情</span></button>
      <button className="console-card" onClick={()=>navigate("/results?tab=quality")}><GitCompareArrows size={24}/><strong>质量与裁决</strong><span>双人盲标与金标准</span></button>
      <button className="console-card" onClick={()=>navigate("/results?tab=graph")}><Network size={24}/><strong>知识图谱</strong><span>实体关系网络与证据</span></button>
      <button className="console-card" onClick={()=>navigate("/results?tab=research")}><Beaker size={24}/><strong>研究检索</strong><span>证据问答与医案检索</span></button>
    </section>
    <section className="content-card"><div className="card-heading"><div><span className="eyebrow">PLATFORM JOBS</span><h2>最近平台任务</h2></div><button className="text-button" onClick={()=>navigate("/task-center")}>查看全部</button></div>
      {jobs.length?<div className="data-table"><div className="table-row table-head"><span>任务</span><span>书籍</span><span>状态</span><span>时间</span></div>
        {jobs.map(job=><div className="table-row" key={job.id}><span><strong>#{job.id} {jobLabels[job.job_type]??job.job_type}</strong></span><span>{job.book_title||"—"}</span><span><i className={`status-dot ${job.status}`}/>{job.status}</span><span>{new Date(job.created_at).toLocaleString()}</span></div>)}
      </div>:<div className="empty-state"><ListTodo size={30}/><p>暂无平台任务</p></div>}
    </section>
  </div>;
}

function PersonalDashboard({token,me,onOpen}:{token:string;me:User;onOpen:(id:number)=>void}){
  const [data,setData]=useState<DashboardData|null>(null),[error,setError]=useState("");
  useEffect(()=>{api.dashboard(token).then(setData).catch(e=>setError(e.message));},[token]);
  const keys=me.role==="reviewer"?["submitted","approved","returned","books","pages","in_progress"]:["ready","in_progress","submitted","approved","returned","pages"];
  const {tab,setTab}=useWorkspaceTab("dashboard",me.role,tabs,me.role==="reviewer"?"reviews":"todo");
  return <div className="page-stack"><section className="welcome-card"><div><span className="eyebrow">今日工作台</span><h1>{me.display_name||me.username}，欢迎回来</h1><p>{me.role==="reviewer"?"逐页核验标注并推动整书流程。":"继续处理已分配页面，系统会自动保存每次修改。"}</p></div><div className="paper-seal"><BookOpen size={38}/></div></section>
    {error&&<div className="alert error">{error}</div>}<section className="stat-grid">{keys.map((key,index)=>{const Icon=icons[index%icons.length];return <article className="stat-card" key={key}><span className="stat-icon"><Icon size={21}/></span><div><strong>{data?.stats[key]??"—"}</strong><small>{labels[key]}</small></div></article>;})}</section>
    <section className="workspace-tabs">{tabs.filter(item=>item.roles.includes(me.role)).map(item=><button key={item.key} className={tab===item.key?"active":""} onClick={()=>setTab(item.key)}>{item.label}</button>)}</section>
    {tab==="todo"&&<TasksPage token={token} me={me} onOpen={onOpen} embedded view="mine"/>}
    {tab==="reviews"&&<TasksPage token={token} me={me} onOpen={onOpen} embedded view="review"/>}
    {tab==="recent"&&<TasksPage token={token} me={me} onOpen={onOpen} embedded archive/>}
  </div>;
}
