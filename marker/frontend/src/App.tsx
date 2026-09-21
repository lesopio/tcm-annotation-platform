import { ReactNode, useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { LoaderCircle } from "lucide-react";
import { api, User } from "./api";
import AppShell from "./components/AppShell";
import LegacyRedirect from "./components/LegacyRedirect";
import AnnotationWorkspace from "./pages/AnnotationWorkspace";
import AnnotationHomePage from "./pages/AnnotationHomePage";
import BookDetailPage from "./pages/BookDetailPage";
import DashboardPage from "./pages/DashboardPage";
import LoginPage from "./pages/LoginPage";
import PreprocessPreviewPage from "./pages/PreprocessPreviewPage";
import ProjectsWorkspacePage from "./pages/ProjectsWorkspacePage";
import SettingsPage from "./pages/SettingsPage";
import TaskCenterPage from "./pages/TaskCenterPage";
import ResultsWorkspacePage from "./pages/ResultsWorkspacePage";
import { UsersManagementPage } from "./pages/ManagementPages";
import { WorkspaceProvider } from "./workspaceContext";

export default function App(){
  const [token,setToken]=useState(()=>localStorage.getItem("bencao_token")??""),[me,setMe]=useState<User|null>(null),[loading,setLoading]=useState(Boolean(token));
  const navigate=useNavigate();
  useEffect(()=>{if(!token){setLoading(false);return;}setLoading(true);api.me(token).then(setMe).catch(logout).finally(()=>setLoading(false));},[token]);
  async function login(username:string,password:string){const result=await api.login(username,password);localStorage.setItem("bencao_token",result.access_token);setToken(result.access_token);setMe(result.user);navigate("/dashboard");}
  function logout(){localStorage.removeItem("bencao_token");setToken("");setMe(null);navigate("/");}
  if(loading)return <main className="app-loading"><LoaderCircle className="spin" size={32}/><strong>正在载入工作台</strong></main>;
  if(!token||!me)return <Routes><Route path="*" element={<LoginPage onLogin={login}/>}/></Routes>;
  const shell=(element:ReactNode)=><AppShell me={me} onLogout={logout}>{element}</AppShell>;
  const open=(id:number)=>navigate(`/work/${id}`);
  const adminOnly=(element:ReactNode)=>me.role==="admin"?shell(element):<Navigate to="/annotation" replace/>;
  return <WorkspaceProvider><Routes>
    <Route path="/dashboard" element={shell(<DashboardPage token={token} me={me} onOpen={open}/>)}/>
    <Route path="/projects" element={adminOnly(<ProjectsWorkspacePage token={token} me={me}/>)}/>
    <Route path="/projects/:bookId" element={adminOnly(<BookDetailPage token={token} me={me}/>)}/>
    <Route path="/task-center" element={adminOnly(<TaskCenterPage token={token}/>)}/>
    <Route path="/annotation" element={shell(<AnnotationHomePage token={token} me={me}/>)}/>
    <Route path="/results" element={shell(<ResultsWorkspacePage token={token} me={me}/>)}/>
    <Route path="/users" element={adminOnly(<UsersManagementPage token={token}/>)}/>
    <Route path="/settings" element={adminOnly(<SettingsPage token={token}/>)}/>
    <Route path="/work/:assignmentId" element={<WorkspaceRoute token={token} me={me} onExit={()=>navigate(me.role==="reviewer"?"/dashboard?tab=reviews":"/annotation")} onNext={(currentId)=>{api.myAssignments(token).then(list=>{const next=list.find(x=>x.id!==currentId&&["assigned","returned","in_progress"].includes(x.status));navigate(next?`/work/${next.id}`:"/annotation");}).catch(()=>navigate("/annotation"));}} onSwitch={(id)=>navigate(`/work/${id}`)}/>}/>
    <Route path="/preprocess-preview" element={me.role==="admin"?<PreprocessPreviewPage token={token} me={me}/>:<Navigate to="/dashboard" replace/>}/>
    <Route path="/books" element={<LegacyRedirect to="/projects"/>}/>
    <Route path="/ocr-preview" element={<LegacyRedirect to="/projects"/>}/>
    <Route path="/workflows" element={<LegacyRedirect to="/projects"/>}/>
    <Route path="/labels" element={<LegacyRedirect to="/projects"/>}/>
    <Route path="/guidelines" element={<LegacyRedirect to="/projects"/>}/>
    <Route path="/exports" element={<LegacyRedirect to="/projects"/>}/>
    <Route path="/tasks" element={<LegacyRedirect to="/dashboard?tab=todo"/>}/>
    <Route path="/reviews" element={<LegacyRedirect to="/dashboard?tab=reviews"/>}/>
    <Route path="/archive" element={<LegacyRedirect to="/dashboard?tab=recent&status=completed"/>}/>
    <Route path="/semantic" element={<LegacyRedirect to="/annotation?step=4"/>}/>
    <Route path="/quality" element={<LegacyRedirect to="/results?tab=quality"/>}/>
    <Route path="/knowledge-graph" element={<LegacyRedirect to="/results?tab=graph"/>}/>
    <Route path="/research" element={<LegacyRedirect to="/results?tab=research"/>}/>
    <Route path="*" element={<Navigate to="/dashboard" replace/>}/>
  </Routes></WorkspaceProvider>;
}

function WorkspaceRoute({token,me,onExit,onNext,onSwitch}:{token:string;me:User;onExit:()=>void;onNext:(currentId:number)=>void;onSwitch:(id:number)=>void}){const {assignmentId}=useParams();const [searchParams]=useSearchParams();const initialStep=Number(searchParams.get("step"))||undefined;return <AnnotationWorkspace token={token} me={me} assignmentId={Number(assignmentId)} onExit={onExit} initialStep={initialStep} onNext={onNext} onSwitchAssignment={onSwitch}/>}
