import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, FilePlus2, RefreshCw, ScanText, Settings2, Trash2, X } from "lucide-react";
import { api, Book, User } from "../api";
import { BookForm } from "./ManagementPages";

/** 项目一级：书籍管理（上传 / 进入二级 / 快捷预处理 / 删除）。 */
export default function ProjectsWorkspacePage({ token, me }: { token: string; me: User }) {
  const navigate = useNavigate();
  const [books, setBooks] = useState<Book[]>([]), [drawer, setDrawer] = useState(false), [message, setMessage] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  async function load() { try { setBooks(await api.books(token)); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } }
  useEffect(() => { load(); }, [token]);
  useEffect(() => {
    if (!books.some(book => ["pending", "recognizing", "uploading"].includes(book.status))) return;
    const timer = window.setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [books]);
  function showError(err: unknown) { setError(err instanceof Error ? err.message : String(err)); }
  async function removeBook(book: Book) {
    let assignmentCount = 0;
    try { assignmentCount = (await api.bookAssignments(token, book.id)).length; } catch { /* 忽略，删除确认仍可继续 */ }
    if (!window.confirm(`确定永久删除《${book.title}》吗？\n共 ${book.page_count} 页、${assignmentCount} 个标注任务。\n页面图片、标注数据、语义数据与图谱将一并删除，不可恢复。`)) return;
    setBusy(true);
    try { await api.deleteBook(token, book.id); setMessage(`《${book.title}》及其全部数据已删除`); await load(); }
    catch (e) { showError(e); }
    finally { setBusy(false); }
  }
  return <div className="page-stack">
    <section className="page-toolbar"><div><span className="eyebrow">PROJECTS</span><h1>书籍管理</h1><p>上传古籍 PDF、进入单书处理台，或删除不需要的书籍。</p></div><div className="toolbar-actions"><button className="secondary-button" onClick={load}><RefreshCw size={17}/>刷新</button><button className="primary-button" onClick={()=>setDrawer(true)}><FilePlus2 size={18}/>上传书籍</button></div></section>
    {error && <div className="alert error" onClick={()=>setError("")}>{error}</div>}{message && <div className="alert settings-success" onClick={()=>setMessage("")}>{message}</div>}
    <section className="content-card"><div className="card-heading"><div><span className="eyebrow">LIBRARY</span><h2>古籍任务库</h2></div><BookOpen size={21}/></div>
      <div className="data-table books-table"><div className="table-row table-head"><span>书籍</span><span>页面</span><span>状态</span><span>操作</span></div>
        {books.map(book => <div className="table-row" key={book.id}>
          <span className="title-cell"><BookOpen size={18}/><b>{book.title}</b></span>
          <span>{book.page_count}</span>
          <span><i className={`status-dot ${book.status}`}/>{{pending:"生成页面中",recognizing:"识别中",ready:"就绪",failed:"失败"}[book.status] ?? book.status}</span>
          <span className="book-actions">
            <button className="text-button" onClick={()=>navigate(`/projects/${book.id}`)}><Settings2 size={15}/>进入处理台</button>
            <button className="text-button" onClick={()=>navigate(`/preprocess-preview?book=${book.id}`)}><ScanText size={15}/>预处理预览</button>
            <button className="text-button danger-text" disabled={busy} onClick={()=>removeBook(book).catch(showError)}><Trash2 size={15}/>删除</button>
          </span>
        </div>)}
        {!books.length && <div className="empty-state"><BookOpen size={34}/><strong>还没有书籍</strong><span>点击右上角"上传书籍"导入第一本古籍 PDF。</span></div>}
      </div>
    </section>
    {drawer && <div className="drawer-backdrop" onMouseDown={()=>setDrawer(false)}><aside className="drawer" onMouseDown={e=>e.stopPropagation()}><div className="drawer-head"><div><span className="eyebrow">UPLOAD</span><h2>上传古籍</h2></div><button className="icon-button" onClick={()=>setDrawer(false)}><X size={20}/></button></div><BookForm token={token} onDone={()=>{setDrawer(false);setMessage("书籍已上传，正在后台生成页面");load();}} onError={showError}/></aside></div>}
  </div>;
}
