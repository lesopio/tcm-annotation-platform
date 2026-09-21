import { useEffect, useState } from "react";
import { Ban, CheckCircle2, ChevronDown, ChevronRight, Clock3, ListTodo, RefreshCw, RotateCcw, TriangleAlert } from "lucide-react";
import { api, PlatformJob, RecognitionBatch } from "../api";

const labels:Record<string,string>={ocr_preview:"OCR 预览",semantic_preannotation:"语义预标注",graph_build:"图谱构建",export:"数据导出",batch_ocr:"批量预处理",page_preprocess:"单页预处理"};
const pageStatus:Record<string,string>={queued:"排队中",running:"识别中",done:"已完成",cached:"命中缓存",failed:"失败",cancelled:"已取消"};
const batchStatus:Record<string,string>={idle:"未开始",pending:"等待中",running:"运行中",done:"已完成",partial:"部分完成",failed:"失败",cancelled:"已取消"};

export default function TaskCenterPage({token,embedded}:{token:string;embedded?:boolean}){
  const [jobs,setJobs]=useState<PlatformJob[]>([]),[error,setError]=useState("");
  const [detail, setDetail] = useState<{ jobId: number; data: RecognitionBatch | null; error: string; loading: boolean } | null>(null);
  const load=()=>api.platformJobs(token).then(setJobs).catch(e=>setError(e.message));
  useEffect(()=>{load();const id=setInterval(load,5000);return()=>clearInterval(id);},[token]);
  async function cancel(id:number){try{await api.cancelPlatformJob(token,id);load();}catch(e){setError(e instanceof Error?e.message:"取消失败");}}
  async function retry(id:number){try{await api.retryPlatformJob(token,id);load();}catch(e){setError(e instanceof Error?e.message:"重试失败");}}
  async function toggleDetail(job:PlatformJob){
    if(detail?.jobId===job.id){setDetail(null);return;}
    const recognitionJobId=Number((job.payload as Record<string,unknown>).recognition_job_id);
    if(!recognitionJobId){setError("该任务没有关联的识别批次");return;}
    setDetail({jobId:job.id,data:null,error:"",loading:true});
    try{setDetail({jobId:job.id,data:await api.recognitionJobDetail(token,recognitionJobId),error:"",loading:false});}
    catch(e){setDetail({jobId:job.id,data:null,error:e instanceof Error?e.message:"加载失败",loading:false});}
  }
  return <div className={embedded?"workspace-stack":"page-stack"}><div className="page-toolbar">{!embedded&&<div><span className="eyebrow">JOB CENTER</span><h1>任务中心</h1><p>统一查看 OCR、语义预标注、知识图谱和导出任务，批量预处理可展开每页详情。</p></div>}<button className="secondary-button" onClick={load}><RefreshCw size={17}/>刷新</button></div>{error&&<div className="alert error" onClick={()=>setError("")}>{error}</div>}
    <section className="content-card"><div className="card-heading"><div><h2>任务队列</h2><small>运行中任务每 5 秒自动刷新</small></div><ListTodo size={21}/></div>
      <div className="data-table"><div className="table-row table-head"><span>任务</span><span>范围</span><span>状态</span><span>进度</span><span>创建者</span><span>操作</span></div>{jobs.map(job=><div key={job.id} className="batch-job-block">
        <div className="table-row"><span><strong>#{job.id} {labels[job.job_type]??job.job_type}</strong><small>{job.model||"本地任务"}</small></span><span>{job.book_title||"—"}<small>{job.page_id?`页面 ID ${job.page_id}`:"整书/全局"}</small></span><span className={`job-status ${job.status}`}>{job.status==="succeeded"?<CheckCircle2 size={15}/>:job.status==="failed"?<TriangleAlert size={15}/>:<Clock3 size={15}/>}{{queued:"等待",running:"运行中",succeeded:"已完成",failed:"失败",cancelled:"已取消"}[job.status]}</span><span><progress max={100} value={job.progress}/><small>{job.progress}% · 尝试 {job.attempts} 次</small></span><span>{job.creator||job.created_by}<small>{new Date(job.created_at).toLocaleString()}</small></span><span className="job-actions-cell">{["batch_ocr","page_preprocess"].includes(job.job_type)&&<button className="text-button" onClick={()=>toggleDetail(job)}>{detail?.jobId===job.id?<ChevronDown size={15}/>:<ChevronRight size={15}/>}批次详情</button>}{job.status==="queued"&&<button className="icon-button" onClick={()=>cancel(job.id)} aria-label="取消任务"><Ban size={17}/></button>}{job.status==="failed"&&<button className="icon-button" onClick={()=>retry(job.id)} aria-label="重试任务"><RotateCcw size={17}/></button>}{job.error&&<small className="danger-text" title={job.error}>{job.error}</small>}</span></div>
        {detail?.jobId===job.id&&<div className="batch-detail">
          {detail.loading&&<p className="muted">正在加载批次详情…</p>}
          {detail.error&&<p className="danger-text">{detail.error}</p>}
          {detail.data&&<><p className="muted">批次 #{detail.data.id} · {batchStatus[detail.data.status]??detail.data.status} · {detail.data.current_page}/{detail.data.total_pages} 页{detail.data.error?` · ${detail.data.error}`:""}</p>
          <div className="data-table"><div className="table-row table-head"><span>页码</span><span>状态</span><span>尝试</span><span>错误</span></div>
            {(detail.data.pages??[]).map(page=><div className="table-row" key={page.id}><span>第 {page.page_no ?? "?"} 页</span><span><i className={`status-dot ${page.status}`}/>{pageStatus[page.status]??page.status}</span><span>{page.attempts}</span><span className="danger-text" title={page.error}>{page.error?.slice(0, 50) || "—"}</span></div>)}
          </div></>}
        </div>}
      </div>)}{!jobs.length&&<div className="empty-state"><ListTodo size={32}/><p>还没有平台任务</p></div>}</div>
    </section></div>;
}
