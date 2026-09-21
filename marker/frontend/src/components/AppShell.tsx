import { ReactNode, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { BarChart3, BookOpen, ChevronDown, ChevronLeft, ChevronRight, LayoutDashboard, Library, ListTodo, LogOut, Menu, PenLine, ScanText, Settings, UserCog, UserRound } from "lucide-react";
import type { Role, User } from "../api";

type Item = { to: string; label: string; icon: typeof BookOpen; roles: Role[] };
const all: Role[] = ["admin", "annotator", "reviewer", "expert", "data_engineer"];
const adminItems: Item[] = [
  { to: "/dashboard", label: "控制台", icon: LayoutDashboard, roles: ["admin"] },
  { to: "/projects", label: "项目", icon: Library, roles: ["admin"] },
  { to: "/task-center", label: "任务中心", icon: ListTodo, roles: ["admin"] },
  { to: "/preprocess-preview", label: "预处理预览", icon: ScanText, roles: ["admin"] },
  { to: "/settings", label: "设置", icon: Settings, roles: ["admin"] },
];
const memberItems: Item[] = [
  { to: "/dashboard", label: "工作台", icon: LayoutDashboard, roles: all },
  { to: "/annotation", label: "标注", icon: PenLine, roles: all },
  { to: "/results", label: "成果", icon: BarChart3, roles: all },
];
const adminTitles: Record<string, string> = { "/dashboard": "控制台", "/projects": "项目", "/task-center": "任务中心", "/preprocess-preview": "标注预处理预览", "/settings": "系统设置", "/users": "用户管理", "/work": "古籍数据标注" };
const memberTitles: Record<string, string> = { "/dashboard": "工作台", "/annotation": "标注", "/results": "成果", "/work": "古籍数据标注" };
const roleNames: Record<Role, string> = { admin: "管理员", annotator: "标注员", reviewer: "审核员", expert: "中医专家", data_engineer: "数据工程" };

function headingFor(pathname: string, admin: boolean): string {
  const titles = admin ? adminTitles : memberTitles;
  const match = Object.keys(titles).filter(key => pathname === key || pathname.startsWith(`${key}/`)).sort((a, b) => b.length - a.length)[0];
  return match ? titles[match] : "古籍数据标注";
}

export default function AppShell({ me, onLogout, children }: { me: User; onLogout: () => void; children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const admin = me.role === "admin";
  const items = admin ? adminItems : memberItems;
  return <div className={collapsed ? "app-frame sidebar-collapsed" : "app-frame"}>
    <aside className="app-sidebar">
      <div className="sidebar-brand"><span className="brand-mark"><BookOpen size={24}/></span><div><strong>古籍标注平台</strong><small>Annotation Workflow · V2</small></div></div>
      <nav className="sidebar-nav">{items.map((item) => { const Icon=item.icon; return <NavLink key={item.to} to={item.to} className={({isActive})=>isActive?"nav-item active":"nav-item"}><Icon size={19}/><span>{item.label}</span></NavLink>; })}</nav>
      <button className="sidebar-collapse icon-button" onClick={()=>setCollapsed(!collapsed)} aria-label={collapsed?"展开侧栏":"收起侧栏"}>{collapsed?<ChevronRight size={18}/>:<ChevronLeft size={18}/>}</button>
    </aside>
    <section className="app-main">
      <header className="app-header"><div className="header-heading"><Menu size={20}/><div><strong>{headingFor(location.pathname, admin)}</strong><small>文字整理 · 语义标注 · 专家审核 · 知识图谱</small></div></div>
        <div className="account-area">
          <button className={`account-trigger${menuOpen?" active":""}`} onClick={()=>setMenuOpen(!menuOpen)} aria-haspopup="menu" aria-expanded={menuOpen}><span className="avatar-icon"><UserRound size={18}/></span><span className="account-name"><strong>{me.display_name||me.username}</strong><small>{roleNames[me.role]}</small></span><ChevronDown size={16}/></button>
          {menuOpen&&<><button className="menu-backdrop" aria-label="关闭账户菜单" onClick={()=>setMenuOpen(false)}/><div className="account-menu" role="menu">
            {admin&&<button role="menuitem" onClick={()=>{setMenuOpen(false);navigate("/users");}}><UserCog size={17}/>用户管理</button>}
            {admin&&<div className="menu-divider"/>}
            <button role="menuitem" className="danger" onClick={()=>{setMenuOpen(false);onLogout();}}><LogOut size={17}/>退出登录</button>
          </div></>}
        </div></header>
      <div className="page-content">{children}</div>
    </section>
  </div>;
}
