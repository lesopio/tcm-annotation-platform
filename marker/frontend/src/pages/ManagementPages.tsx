import { FormEvent, useEffect, useState } from "react";
import { FilePlus2, Plus, Tags, UserPlus, UsersRound, X } from "lucide-react";
import { api, Assignment, Book, LabelDefinition, User } from "../api";

const groupNames={region:"区域类型",layout:"版面类型",stratum:"层累标签"};

/** 用户管理独立页：角色收敛为 管理员/标注员 两类（历史角色账号保持兼容展示）。 */
export function UsersManagementPage({token}:{token:string}){
  const [users,setUsers]=useState<User[]>([]),[drawer,setDrawer]=useState(false),[editingUser,setEditingUser]=useState<User|null>(null),[message,setMessage]=useState("");
  async function load(){try{setUsers(await api.users(token));}catch(e){setMessage(e instanceof Error?e.message:String(e));}}
  useEffect(()=>{load();},[token]);
  function showError(err:unknown){setMessage(err instanceof Error?err.message:String(err));}
  return <div className="page-stack"><section className="page-toolbar"><div><span className="eyebrow">TEAM</span><h1>用户管理</h1><p>维护管理员与标注员账号。</p></div><button className="primary-button" onClick={()=>{setEditingUser(null);setDrawer(true)}}><UserPlus size={18}/>新增用户</button></section>{message&&<div className="alert" onClick={()=>setMessage("")}>{message}</div>}
    <UsersPanel users={users} onEdit={user=>{setEditingUser(user);setDrawer(true)}}/>
    {drawer&&<div className="drawer-backdrop" onMouseDown={()=>setDrawer(false)}><aside className="drawer" onMouseDown={e=>e.stopPropagation()}><div className="drawer-head"><div><span className="eyebrow">{editingUser?"EDIT":"CREATE"}</span><h2>{editingUser?"编辑用户":"创建用户"}</h2></div><button className="icon-button" onClick={()=>setDrawer(false)}><X size={20}/></button></div><UserForm token={token} user={editingUser} onDone={()=>{setDrawer(false);setEditingUser(null);load();}} onError={showError}/></aside></div>}
  </div>;
}

export function BookForm({token,onDone,onError}:{token:string;onDone:()=>void;onError:(e:unknown)=>void}){
  const [fileName,setFileName]=useState(""),[submitting,setSubmitting]=useState(false);
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    const form=new FormData(event.currentTarget),file=form.get("file");
    if(!(file instanceof File)||!file.name){onError(new Error("请先选择 PDF 文件"));return;}
    setSubmitting(true);
    try{await api.createBook(token,file,String(form.get("title")??""),String(form.get("prompt")??""));onDone();}
    catch(error){onError(error);}
    finally{setSubmitting(false);}
  }
  return <form className="form-stack" onSubmit={submit}><label>书籍名称（可选）<input name="title" placeholder="留空则使用 PDF 文件名"/></label><label>标注说明<textarea name="prompt" rows={5}/></label><label className="file-drop"><FilePlus2 size={28}/><strong>{fileName||"选择 PDF 文件"}</strong><input name="file" type="file" accept="application/pdf,.pdf" required onChange={event=>setFileName(event.currentTarget.files?.[0]?.name??"")}/></label><button className="primary-button" type="submit" disabled={submitting}>{submitting?"正在上传并生成页面…":"上传并生成页面"}</button></form>;
}

function UserForm({token,user,onDone,onError}:{token:string;user:User|null;onDone:()=>void;onError:(e:unknown)=>void}){return <form className="form-stack" onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget),password=String(f.get("password"));api.saveUser(token,{...user,username:String(f.get("username")),display_name:String(f.get("display_name")),...(password?{password}:{}),role:String(f.get("role")) as User["role"],is_active:true}).then(onDone).catch(onError)}}><label>账号<input name="username" defaultValue={user?.username} disabled={Boolean(user)} required/></label><label>显示名称<input name="display_name" defaultValue={user?.display_name} required/></label><label>{user?"重置密码（留空不修改）":"初始密码"}<input name="password" type="password" minLength={4} required={!user}/></label><label>角色<select name="role" defaultValue={user?["admin","annotator"].includes(user.role)?user.role:"annotator":"annotator"}><option value="annotator">标注员</option><option value="admin">管理员</option></select>{user&&!["admin","annotator"].includes(user.role)&&<small>历史角色账号（{user.role}）保存后将转为标注员。</small>}</label><button className="primary-button"><Plus size={17}/>{user?"保存修改":"创建用户"}</button></form>;}

function UsersPanel({users,onEdit}:{users:User[];onEdit:(user:User)=>void}){const roleNames:Record<string,string>={admin:"管理员",annotator:"标注员",reviewer:"审核员(旧)",expert:"中医专家(旧)",data_engineer:"数据工程(旧)"};return <section className="content-card"><div className="card-heading"><div><span className="eyebrow">TEAM</span><h2>平台用户</h2></div><UsersRound size={21}/></div><div className="data-table"><div className="table-row table-head"><span>用户</span><span>账号</span><span>角色</span><span>状态</span><span>操作</span></div>{users.map(user=><div className="table-row" key={user.id}><span><b>{user.display_name||user.username}</b></span><span>{user.username}</span><span><em className="role-badge">{roleNames[user.role]??user.role}</em></span><span><i className={`status-dot ${user.is_active?"active":"inactive"}`}/>{user.is_active?"启用":"停用"}</span><span><button className="text-button" onClick={()=>onEdit(user)}>编辑</button></span></div>)}</div></section>;}

export function LabelsPanel({token,book,items,setItems,onError}:{token:string;book:Book;items:LabelDefinition[];setItems:(x:LabelDefinition[])=>void;onError:(e:unknown)=>void}){
  const change=(row:LabelDefinition,patch:Partial<LabelDefinition>)=>setItems(items.map(x=>x===row?{...x,...patch}:x));
  const add=(group:LabelDefinition["group"])=>setItems([...items,{id:0,book_id:book.id,group,code:`CUSTOM_${items.filter(x=>x.group===group).length+1}`,name:"自定义标签",color:"#8b5e3c",description:"",sort_order:items.length+1,is_active:true}]);
  return <section className="label-columns">{(["region","layout","stratum"] as const).map(group=><article className="content-card" key={group}><div className="card-heading"><div><span className="eyebrow">LABEL GROUP</span><h2>{groupNames[group]}</h2></div><button className="icon-button" onClick={()=>add(group)}><Plus size={18}/></button></div><div className="label-list">{items.filter(x=>x.group===group).map((row,index)=><div className="label-row" key={`${row.id}-${index}`}><input type="color" value={row.color} onChange={e=>change(row,{color:e.target.value})}/><input value={row.code} onChange={e=>change(row,{code:e.target.value.toUpperCase()})}/><input value={row.name} onChange={e=>change(row,{name:e.target.value})}/><input type="checkbox" checked={row.is_active} onChange={e=>change(row,{is_active:e.target.checked})}/></div>)}</div></article>)}<button className="primary-button floating-save" onClick={()=>api.saveBookLabels(token,book.id,items).then(setItems).catch(onError)}><Tags size={17}/>保存标签体系</button></section>;
}

export function AssignmentsPanel({token,book,users,assignments,onReload,onError}:{token:string;book:Book;users:User[];assignments:Assignment[];onReload:()=>void;onError:(e:unknown)=>void}){
  return <section className="split-panels"><form className="content-card form-stack" onSubmit={(e:FormEvent<HTMLFormElement>)=>{e.preventDefault();const f=new FormData(e.currentTarget),rows=users.filter(x=>x.role==="annotator").map(x=>{const match=String(f.get(`range_${x.id}`)||"").match(/^(\d+)\s*-\s*(\d+)$/);return match?{user_id:x.id,start_page:Number(match[1]),end_page:Number(match[2])}:null}).filter(Boolean) as {user_id:number;start_page:number;end_page:number}[];api.saveAssignments(token,book.id,rows).then(onReload).catch(onError)}}><div className="card-heading"><div><span className="eyebrow">ASSIGN</span><h2>按页码分配</h2></div></div>{users.filter(x=>x.role==="annotator").map(user=><label key={user.id}>{user.display_name||user.username}<input name={`range_${user.id}`} placeholder={`例如 1-${book.page_count}`}/></label>)}<button className="primary-button">保存分配</button></form><section className="content-card"><div className="card-heading"><div><span className="eyebrow">PAGES</span><h2>已分配页面</h2></div></div><div className="assignment-chips">{assignments.map(item=><span key={item.id}><b>{item.page_no}</b>{item.username}</span>)}</div></section></section>;
}
