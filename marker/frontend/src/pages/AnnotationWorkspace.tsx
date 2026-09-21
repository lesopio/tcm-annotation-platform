import { useEffect, useRef, useState } from "react";
import { ArrowLeft, BookOpen, Check, ChevronLeft, ChevronRight, Cloud, RotateCcw, Save } from "lucide-react";
import AuthenticatedImage from "../components/AuthenticatedImage";
import ProofreadStage from "../components/ProofreadStage";
import SemanticAnnotationPanel from "../components/SemanticPanels";
import { api, Assignment, BookWorkflowRun, User, Workflow } from "../api";

type Step=1|2|3|4|5|6;
const stepNames=["区域调整","字框和列框","校对文字","原文与规范文本","实体与关系","医案与提交"];
const nodeTypesForStep:Record<Step,string[]>={1:["region"],2:["layout"],3:["character"],4:["text_normalize"],5:["entity","relation"],6:["medical_case"]};
export default function AnnotationWorkspace({token,me,assignmentId,onExit,initialStep,onNext,onSwitchAssignment}:{token:string;me:User;assignmentId:number;onExit:()=>void;initialStep?:number;onNext?:(currentId:number)=>void;onSwitchAssignment?:(id:number)=>void}){
  const [workflow,setWorkflow]=useState<Workflow|null>(null),[bookRun,setBookRun]=useState<BookWorkflowRun|null>(null),[step,setStep]=useState<Step>(1),[dirty,setDirty]=useState(false),[saveState,setSaveState]=useState("已保存"),[message,setMessage]=useState(""),[reviewComment,setReviewComment]=useState(""),[resetToken,setResetToken]=useState(0),[pageAssignments,setPageAssignments]=useState<Assignment[]>([]);const saving=useRef(false);
  useEffect(()=>{api.workflow(token,assignmentId).then(data=>{setWorkflow(data);setStep((initialStep&&initialStep>=1&&initialStep<=6?initialStep:Math.min(6,Math.max(1,data.assignment.current_step))) as Step);setResetToken(t=>t+1);api.bookWorkflow(token,data.book.id).then(setBookRun).catch(()=>setBookRun(null));api.myAssignments(token).then(list=>{const mine=list.filter(x=>x.book_id===data.book.id);if(!mine.some(x=>x.id===data.assignment.id))mine.unshift(data.assignment);setPageAssignments(mine);}).catch(()=>setPageAssignments([data.assignment]));}).catch(e=>setMessage(e.message));},[token,assignmentId]);
  useEffect(()=>{if(!dirty||!workflow)return;const timer=window.setTimeout(()=>save(step).catch(showError),1200);return()=>clearTimeout(timer);},[dirty,workflow,step]);
  useEffect(()=>{const before=(event:BeforeUnloadEvent)=>{if(dirty){event.preventDefault();event.returnValue="";}};window.addEventListener("beforeunload",before);return()=>window.removeEventListener("beforeunload",before);},[dirty]);
  function showError(error:unknown){setMessage(error instanceof Error?error.message:String(error));setSaveState("保存失败");}
  function change(fn:(value:Workflow)=>Workflow){setWorkflow(value=>value?fn(value):value);setDirty(true);}
  async function save(next:Step){if(!workflow||saving.current)return workflow;saving.current=true;setSaveState("正在保存");try{const saved=await api.saveWorkflow(token,workflow.assignment.id,{expected_version:workflow.assignment.version,current_step:next,regions:workflow.regions,lines:workflow.lines,chars:workflow.chars,entity_annotations:[]});setWorkflow(saved);setDirty(false);setSaveState("已保存");return saved;}catch(error){showError(error);throw error;}finally{saving.current=false;}}
  async function leave(){if(dirty&&!window.confirm("仍有修改等待保存，确定离开吗？"))return;if(dirty)await save(step).catch(()=>{});onExit();}
  const readOnly=workflow?workflow.assignment.status==="approved"||(me.role==="annotator"&&workflow.assignment.status==="submitted"):false;
  async function reload(){const data=await api.workflow(token,assignmentId);setWorkflow(data);setDirty(false);setSaveState("已保存");setResetToken(t=>t+1);}
  async function resetOcr(mode:"all"|"columns"){if(!workflow)return;const saved=await api.resetAssignmentOcr(token,workflow.assignment.id,mode);setWorkflow(saved);setDirty(false);setSaveState("已保存");setResetToken(t=>t+1);}
  const seedAction=workflow?{label:"从本页 OCR 生成文本单元",run:async()=>{
    const lines=[...workflow.lines].sort((a,b)=>a.order_no-b.order_no);
    const original=lines.map(line=>line.ocr_text||workflow.chars.filter(c=>c.line_id===line.id).sort((a,b)=>a.order_no-b.order_no).map(c=>c.corrected_text||c.raw_text).join("")).filter(Boolean).join("\n");
    if(!original)throw new Error("本页暂无 OCR 文本，请先在文字校对中确认文字或运行 OCR 预标注");
    await api.saveTextUnit(token,{book_id:workflow.book.id,page_id:workflow.page.id,stable_id:`book-${workflow.book.id}-page-${workflow.page.page_no}-unit-1`,order_no:1,source_page:String(workflow.page.page_no),unit_type:"article",text_type:"article",title:`第 ${workflow.page.page_no} 页文本整理`,original_text:original,normalized_text:"",status:"draft"});
  }}:undefined;
  async function completeStage(){if(!workflow)return;await save(step).catch(()=>{});const types=nodeTypesForStep[step];const tasks=bookRun?.nodes.filter(x=>types.includes(x.node_type)).flatMap(x=>x.tasks).filter(x=>x.page_id===workflow.page.id)??[];for(const task of tasks)await api.workflowTaskAction(token,task.id,"complete");if(step<6){setStep((step+1) as Step);api.bookWorkflow(token,workflow.book.id).then(setBookRun).catch(()=>{});}else{const assignment=await api.submitAssignment(token,workflow.assignment.id);setWorkflow({...workflow,assignment});if(onNext)onNext(assignment.id);else onExit();}}
  async function review(action:"approve"|"return"){if(!workflow)return;await save(step).catch(()=>{});await api.reviewAssignment(token,workflow.assignment.id,action,reviewComment);const reviewTask=bookRun?.nodes.flatMap(x=>x.tasks).find(x=>x.page_id===workflow.page.id&&x.assignee_id===me.id&&["ready","active"].includes(x.status));if(reviewTask)await api.workflowTaskAction(token,reviewTask.id,action==="approve"?"approve":"return",reviewComment);onExit();}
  function goStep(next:number){if(next>=1&&next<=6&&!dirty)setStep(next as Step);}
  if(!workflow)return <main className="workspace-loading"><Cloud size={32}/><strong>{message||"正在载入标注任务"}</strong></main>;
  const chipDone=(index:number)=>bookRun?bookRun.nodes.filter(x=>!["start","end"].includes(x.node_type)&&nodeTypesForStep[(index+1) as Step].includes(x.node_type)).every(x=>x.status==="completed"):false;
  return <main className="annotation-app proofread-app"><header className="proof-header">
    <div className="proof-header-left"><button className="icon-button" onClick={()=>leave().catch(showError)} title="返回"><ArrowLeft size={19}/></button><div className="proof-title"><strong>{workflow.book.title}</strong><small>第 {workflow.page.page_no} 页 · {saveState} · {readOnly?"只读":""}</small></div></div>
    <div className="proof-flow">
      {[1,2,3].map(index=><button key={index} className={`proof-flow-chip${step===index?" active":chipDone(index)?" done":""}`} onClick={()=>goStep(index)}><i>{index}</i>{stepNames[index-1]}{chipDone(index)&&<Check size={13}/>}</button>)}
      <button className={`proof-flow-chip semantic${step>=4?" active":chipDone(3)&&chipDone(4)&&chipDone(5)?" done":""}`} onClick={()=>goStep(4)}><i>4</i>语义标注</button>
    </div>
    <div className="proof-header-right">
      <button className="secondary-button" disabled={step<=1} onClick={()=>goStep(step-1)}><ChevronLeft size={15}/>上一步</button>
      <button className="secondary-button" disabled={step>=6} onClick={()=>goStep(step+1)}>下一步<ChevronRight size={15}/></button>
      <button className="primary-button" onClick={()=>save(step).catch(()=>{})} disabled={readOnly}><Save size={16}/>保存</button>
    </div>
  </header>
    {message&&<div className="annotation-alert" onClick={()=>setMessage("")}>{message}</div>}
    {step<=3?(
      <ProofreadStage token={token} me={me} workflow={workflow} step={(step <= 3 ? step : 1) as 1 | 2 | 3} readOnly={readOnly} dirty={dirty} resetToken={resetToken}
        onChange={change} onSave={()=>save(step)} onComplete={completeStage} onReview={(action)=>review(action)} onAbandon={reload} onResetOcr={resetOcr}
        onSwitchAssignment={(id)=>{if(dirty&&!window.confirm("仍有修改等待保存，切换页将先自动保存，继续吗？"))return;save(step).catch(()=>{}).finally(()=>onSwitchAssignment?onSwitchAssignment(id):undefined);}}
        assignments={pageAssignments}/>
    ):(
      <section className="annotation-body semantic-mode"><div className="semantic-stage">
        <section className="content-card semantic-stage-image"><div className="card-heading"><h2>页面原图</h2><BookOpen size={20}/></div><AuthenticatedImage className="semantic-page-image" src={`${api.base}/api/book-pages/${workflow.page.id}/image`} token={token} alt={`第 ${workflow.page.page_no} 页`}/></section>
        <div className="semantic-stage-panel"><div className="step-switch semantic-step-switch">{stepNames.map((name,index)=><button className={step===index+1?"active":""} onClick={()=>goStep(index+1)} key={name}><span>{index+1}</span>{name}</button>)}</div>
          <SemanticAnnotationPanel token={token} bookId={workflow.book.id} pageId={workflow.page.id} pageNo={workflow.page.page_no} assignmentId={workflow.assignment.id} mode={step===4?"text":step===5?"semantic":"case"} seedAction={step===4?seedAction:undefined}/>
          <div className="inspector-footer semantic-footer">{me.role==="reviewer"||me.role==="admin"?<div className="review-box"><textarea value={reviewComment} onChange={e=>setReviewComment(e.target.value)} placeholder="审核意见"/><button className="secondary-button" onClick={()=>review("return").catch(showError)}><RotateCcw size={16}/>打回</button><button className="primary-button" onClick={()=>review("approve").catch(showError)}><Check size={16}/>通过</button></div>:<button className="primary-button wide" onClick={()=>completeStage().catch(showError)}><Check size={17}/>{step===6?"提交本页任务":`完成${stepNames[step-1]}`}</button>}</div>
        </div></div></section>
    )}
    <div className="narrow-warning">标注工作台需要至少 1280px 的屏幕宽度，请放大窗口后继续。</div></main>;
}
