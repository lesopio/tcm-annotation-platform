import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, BookOpen, Cloud, Crosshair, Eraser, Hand, ListOrdered, Maximize, Minus, Play, Plus, RefreshCw, RotateCw, Save, ScanText, SlidersHorizontal, SquareDashed } from "lucide-react";
import AuthenticatedImage from "../components/AuthenticatedImage";
import ProgressToast, { ToastJob } from "../components/ProgressToast";
import ProofreadCanvas, { CanvasHandle, ProofBox } from "../components/ProofreadCanvas";
import { api, Book, BookPage, RecognitionLatest, User } from "../api";

const REGION_TYPE_NAMES: Record<string, string> = { text: "正文", header: "题头", table: "表格", image: "图像", seal: "印章" };
type Dialog = null | "clear" | "save" | "batch";

/** 管理员全屏预处理预览：识典风格只读查看 + 处理当前页 / 清空痕迹 / 保存 / 批量预处理。 */
export default function PreprocessPreviewPage({ token }: { token: string; me: User }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const canvasRef = useRef<CanvasHandle | null>(null);
  const [books, setBooks] = useState<Book[]>([]), [bookId, setBookId] = useState(Number(params.get("book")) || 0);
  const [pages, setPages] = useState<BookPage[]>([]), [pageId, setPageId] = useState(Number(params.get("page")) || 0);
  const [data, setData] = useState<RecognitionLatest | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState(""), [missing, setMissing] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [showRegions, setShowRegions] = useState(false), [showColumns, setShowColumns] = useState(true), [showChars, setShowChars] = useState(true), [showNumbers, setShowNumbers] = useState(true);
  const [brightnessLocal, setBrightnessLocal] = useState(100), [brightness, setBrightness] = useState(100), [rotation, setRotation] = useState(0), [zoomPercent, setZoomPercent] = useState(32);
  const [dialog, setDialog] = useState<Dialog>(null), [busy, setBusy] = useState(""), [notice, setNotice] = useState(""), [toastJob, setToastJob] = useState<ToastJob>(null);
  const [batchBook, setBatchBook] = useState(0), [batchStart, setBatchStart] = useState(1), [batchEnd, setBatchEnd] = useState(1);

  useEffect(() => { api.books(token).then(rows => { setBooks(rows); setBookId(current => current || rows[0]?.id || 0); }).catch(e => setError(e.message)); }, [token]);
  useEffect(() => { const timer = window.setTimeout(() => setBrightness(brightnessLocal), 140); return () => clearTimeout(timer); }, [brightnessLocal]);
  useEffect(() => {
    if (!bookId) return;
    setLoading(true);
    api.bookPages(token, bookId).then(rows => { setPages(rows); setPageId(current => (rows.some(page => page.id === current) ? current : rows[0]?.id ?? 0)); }).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, [token, bookId]);
  useEffect(() => { setParams(prev => { const next = new URLSearchParams(prev); next.set("book", String(bookId || "")); next.set("page", String(pageId || "")); return next; }, { replace: true }); }, [bookId, pageId]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!pageId) return;
    setData(null); setSelectedKey(null); setMissing(false); setLoading(true);
    api.recognitionLatest(token, pageId).then(setData).catch(e => {
      const message = e instanceof Error ? e.message : String(e);
      if (message.includes("尚无识别结果")) setMissing(true); else setError(message);
    }).finally(() => setLoading(false));
  }, [token, pageId]);
  useEffect(() => { const timer = setTimeout(() => canvasRef.current?.fit(), 400); return () => clearTimeout(timer); }, [pageId, data]);
  useEffect(() => { const book = books.find(item => item.id === batchBook); setBatchStart(1); setBatchEnd(book?.page_count ?? 1); }, [batchBook]);

  const page = pages.find(item => item.id === pageId) ?? null;
  const book = books.find(item => item.id === bookId) ?? null;
  const result = data?.result;
  const regionBoxes: ProofBox[] = result ? result.regions.map(x => ({ key: `region:${x.order_no}`, kind: "region", order: x.order_no, bbox: x.bbox })) : [];
  const columnBoxes: ProofBox[] = result ? result.lines.map(x => ({ key: `line:${x.order_no}`, kind: "line", order: x.order_no, bbox: x.bbox, text: x.ocr_text })) : [];
  const charBoxes: ProofBox[] = result ? result.chars.map(x => ({ key: `char:${x.order_no}`, kind: "char", order: x.order_no, bbox: x.bbox, text: x.raw_text })) : [];
  const resplitCount = result ? result.lines.filter(x => x.needs_char_split).length : 0;

  function reloadLatest() {
    if (!pageId) return;
    setData(null); setMissing(false); setLoading(true);
    api.recognitionLatest(token, pageId).then(setData).catch(e => { const message = e instanceof Error ? e.message : String(e); if (message.includes("尚无识别结果")) setMissing(true); else setError(message); }).finally(() => setLoading(false));
  }
  async function run(action: () => Promise<void>, label: string) { if (busy) return; setBusy(label); setNotice(""); try { await action(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); } }

  async function processCurrent() {
    if (!pageId) return;
    await run(async () => {
      const started = await api.preprocessPage(token, pageId);
      setToastJob({ id: started.platform_job_id, title: `单页预处理 · 第 ${page?.page_no ?? "?"} 页` });
    }, "process");
  }
  async function clearTraces() {
    setDialog(null);
    await run(async () => {
      const counts = await api.clearPageRecognition(token, pageId);
      setNotice(`已清除：${counts.regions} 区域 · ${counts.lines} 列 · ${counts.chars} 字 · ${counts.raw_files} 份识别原文 · ${counts.jobs} 条任务记录`);
      reloadLatest();
    }, "clear");
  }
  async function saveToTasks() {
    setDialog(null);
    await run(async () => {
      const saved = await api.applyPageRecognition(token, pageId);
      setNotice(`已写入 ${saved.applied} 个标注任务（覆盖 ${saved.replaced} 个）：${saved.lines} 列 · ${saved.chars} 字`);
    }, "save");
  }
  async function startBatch() {
    setDialog(null);
    await run(async () => {
      const batch = await api.startRecognition(token, batchBook, batchStart, batchEnd);
      const title = `批量预处理 · ${books.find(x => x.id === batchBook)?.title ?? ""} 第 ${batchStart}-${batchEnd} 页`;
      if (batch.platform_job_id) setToastJob({ id: batch.platform_job_id, title });
      else setNotice("批次已发起");
    }, "batch");
  }

  return <main className="annotation-app proofread-app"><header className="proof-header">
    <div className="proof-header-left"><button className="icon-button" title="返回" onClick={() => navigate(bookId ? `/projects/${bookId}?tab=workflow` : "/projects")}><ArrowLeft size={19}/></button>
      <div className="proof-title"><strong>标注预处理预览{book ? ` · ${book.title}` : ""}</strong><small>{page ? `第 ${page.page_no} 页 · ${page.width}×${page.height}` : "选择书页后查看"} · 只读</small></div></div>
    <div className="proof-flow">
      <label className="proof-page-select"><span className="proof-tool-label">书籍</span>
        <select value={bookId} onChange={e => setBookId(Number(e.target.value))}>{books.map(item => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label>
      <label className="proof-page-select"><span className="proof-tool-label">页码</span>
        <select value={pageId} onChange={e => setPageId(Number(e.target.value))}>{pages.map(item => <option value={item.id} key={item.id}>第 {item.page_no} 页</option>)}</select></label>
    </div>
    <div className="proof-header-right">
      <button className="secondary-button" onClick={reloadLatest} disabled={!pageId} title="刷新预览"><RefreshCw size={15}/></button>
      <button className="primary-button" disabled={!pageId || !!busy} onClick={processCurrent}><Play size={16}/>处理当前页</button>
      <button className="secondary-button" disabled={!pageId || !!busy} onClick={() => setDialog("clear")}><Eraser size={15}/>清空痕迹</button>
      <button className="secondary-button" disabled={!pageId || !!busy || missing} onClick={() => setDialog("save")}><Save size={15}/>保存</button>
      <button className="proof-tool icon" title="批量预处理" onClick={() => { setBatchBook(bookId); setDialog("batch"); }}><SlidersHorizontal size={16}/></button>
    </div>
  </header>
    {error && <div className="annotation-alert" onClick={() => setError("")}>{error}</div>}
    {notice && <div className="proof-notice" onClick={() => setNotice("")}>{notice}</div>}
    <section className="proof-body">
      <div className="proof-toolbar">
        <div className="proof-tool-group"><span className="proof-tool-label">图片深浅</span><input type="range" min={50} max={150} value={brightnessLocal} onChange={e => setBrightnessLocal(Number(e.target.value))}/></div>
        <div className="proof-tool-group">
          <button className="proof-tool icon" title="缩小" onClick={() => canvasRef.current?.zoomBy(0.85)}><Minus size={16}/></button>
          <span className="proof-zoom-value">{zoomPercent}%</span>
          <button className="proof-tool icon" title="放大" onClick={() => canvasRef.current?.zoomBy(1.18)}><Plus size={16}/></button>
        </div>
        <div className="proof-tool-group">
          <button className={`proof-tool toggle${showRegions ? " on-orange" : ""}`} onClick={() => setShowRegions(!showRegions)}><SquareDashed size={15}/>区域框</button>
          <button className={`proof-tool toggle${showColumns ? " on-green" : ""}`} onClick={() => setShowColumns(!showColumns)}><SquareDashed size={15}/>列框</button>
          <button className={`proof-tool toggle${showChars ? " on-blue" : ""}`} onClick={() => setShowChars(!showChars)}><Crosshair size={15}/>字框</button>
          <button className={`proof-tool toggle${showNumbers ? " on-ink" : ""}`} onClick={() => setShowNumbers(!showNumbers)}><ListOrdered size={15}/>展示序号</button>
        </div>
        <div className="proof-tool-group"><button className="proof-tool" title="旋转 90°" onClick={() => setRotation((rotation + 90) % 360)}><RotateCw size={16}/>旋转{rotation}°</button></div>
      </div>
      <div className="proof-main">
        <div className="proof-canvas-wrap">
          <div className="proof-rail-buttons">
            <button className="proof-rail-button active" title="平移（拖动画布）"><Hand size={17}/></button>
            <button className="proof-rail-button" title="放大" onClick={() => canvasRef.current?.zoomBy(1.18)}><Plus size={17}/></button>
            <button className="proof-rail-button" title="缩小" onClick={() => canvasRef.current?.zoomBy(0.85)}><Minus size={17}/></button>
            <button className="proof-rail-button" title="适应画布" onClick={() => canvasRef.current?.fit()}><Maximize size={16}/></button>
          </div>
          {page && !loading && <ProofreadCanvas ref={canvasRef} token={token} page={page} regions={regionBoxes} columns={columnBoxes} chars={charBoxes}
            showRegions={showRegions} showColumns={showColumns} showChars={showChars} showNumbers={showNumbers}
            selectedKey={selectedKey} currentKey={null} brightness={brightness / 100} rotation={rotation}
            drawMode={false} createKind="region" readOnly
            onView={setZoomPercent} onSelect={setSelectedKey} onCreate={() => {}} onUpdate={() => {}}/>}
          {loading && <div className="proof-preview-empty"><Cloud size={30} className="spin"/><strong>正在载入识别结果…</strong></div>}
          {!loading && missing && <div className="proof-preview-empty"><ScanText size={30}/><strong>该页尚无识别结果</strong><span>点击右上角"处理当前页"对该页发起三段处理（版面识别 → 列切分 → 字格对应）</span><button className="primary-button" disabled={!!busy} onClick={processCurrent}><Play size={15}/>处理当前页</button></div>}
        </div>
        <aside className="proof-panel">
          <div className="proof-panel-head"><span className="proof-step-no"><ScanText size={17}/></span><div><h2>识别结果检查</h2><p>最近一次识别的区域（橙）、列框（绿）与字框（蓝），只读预览。</p></div></div>
          {page && <div className="proof-thumbnail">
            <AuthenticatedImage src={`${api.base}/api/book-pages/${page.id}/image`} token={token} alt={`第 ${page.page_no} 页`}/>
            <div className="proof-thumbnail-overlay">
              {showRegions && regionBoxes.map(box => <span key={box.key} className="thumb-region" style={{ left: `${box.bbox[0] / page.width * 100}%`, top: `${box.bbox[1] / page.height * 100}%`, width: `${(box.bbox[2] - box.bbox[0]) / page.width * 100}%`, height: `${(box.bbox[3] - box.bbox[1]) / page.height * 100}%` }} onClick={() => setSelectedKey(box.key)}/>)}
              {showColumns && columnBoxes.map(box => <span key={box.key} className="thumb-column" style={{ left: `${box.bbox[0] / page.width * 100}%`, top: `${box.bbox[1] / page.height * 100}%`, width: `${(box.bbox[2] - box.bbox[0]) / page.width * 100}%`, height: `${(box.bbox[3] - box.bbox[1]) / page.height * 100}%` }} onClick={() => setSelectedKey(box.key)}/>)}
              {showChars && charBoxes.map(box => <span key={box.key} className="thumb-char" style={{ left: `${box.bbox[0] / page.width * 100}%`, top: `${box.bbox[1] / page.height * 100}%`, width: `${(box.bbox[2] - box.bbox[0]) / page.width * 100}%`, height: `${(box.bbox[3] - box.bbox[1]) / page.height * 100}%` }} onClick={() => setSelectedKey(box.key)}/>)}
            </div>
          </div>}
          <div className="proof-stats">{result ? `${result.regions.length} 区域 · ${result.lines.length} 列 · ${result.chars.length} 字${resplitCount > 0 ? ` · ${resplitCount} 列待重切` : ""}` : "暂无数据"}</div>
          {result && result.warnings.length > 0 && <div className="proof-warnings">{result.warnings.slice(0, 8).map((warning, index) => <span key={index}>· {warning}</span>)}{result.warnings.length > 8 && <span>… 共 {result.warnings.length} 条</span>}</div>}
          {result && <div className="proof-list">
            {result.regions.map(region => (
              <div key={`region:${region.order_no}`} className={`proof-row${selectedKey === `region:${region.order_no}` ? " selected" : ""}`} onClick={() => setSelectedKey(`region:${region.order_no}`)}>
                <span className="proof-row-no">{region.order_no}</span>
                <span className="proof-row-text">{REGION_TYPE_NAMES[region.region_type] ?? region.region_type}</span>
                <button className="proof-row-locate" title="定位" onClick={(e) => { e.stopPropagation(); canvasRef.current?.focusBox(region.bbox); }}><Crosshair size={14}/></button>
              </div>
            ))}
            {result.lines.map(line => (
              <div key={`line:${line.order_no}`} className={`proof-row${selectedKey === `line:${line.order_no}` ? " selected" : ""}`} onClick={() => setSelectedKey(`line:${line.order_no}`)}>
                <span className="proof-row-no col">{line.order_no}</span>
                <span className="proof-row-text" title={line.ocr_text}>{line.ocr_text || "（该列无文本）"}</span>
                {line.needs_char_split && <span className="proof-row-flag">待重切</span>}
                <button className="proof-row-locate" title="定位" onClick={(e) => { e.stopPropagation(); canvasRef.current?.focusBox(line.bbox); }}><Crosshair size={14}/></button>
              </div>
            ))}
          </div>}
          <div className="proof-panel-foot">
            <div className="proof-task-info">
              <span>{data ? `批次 #${data.job.batch_id} · ${data.job.model} · 尝试 ${data.job.attempts} 次` : "—"}</span>
              <span>{data ? `识别时间 ${new Date(data.job.updated_at).toLocaleString("zh-CN")}` : ""}</span>
            </div>
            <div className="proof-actions"><button className="primary-button wide" onClick={() => navigate(bookId ? `/projects/${bookId}?tab=workflow` : "/projects")}><BookOpen size={15}/>返回书籍处理台</button></div>
          </div>
        </aside>
      </div>
      <div className="proof-shortcut-hint">只读预览 · 滚轮缩放 · 拖拽平移 · 点击框选中 · 列表"定位"跳转到画布</div>
    </section>

    {dialog === "clear" && <div className="modal-backdrop" onClick={() => setDialog(null)}><div className="modal-card" onClick={e => e.stopPropagation()}>
      <div className="modal-title"><Eraser size={18}/>清空痕迹</div>
      <p>将清除第 {page?.page_no ?? "?"} 页的：<strong>标注任务中的区域/列/字、识别原文文件、预处理任务记录</strong>（语义标注数据保留，任务回到待开始）。此操作不可撤销，继续吗？</p>
      <div className="modal-actions"><button className="secondary-button" onClick={() => setDialog(null)}>取消</button><button className="danger-button" disabled={!!busy} onClick={clearTraces}>{busy === "clear" ? "清除中…" : "确认清空"}</button></div>
    </div></div>}
    {dialog === "save" && <div className="modal-card-host"><div className="modal-backdrop" onClick={() => setDialog(null)}/><div className="modal-card">
      <div className="modal-title"><Save size={18}/>保存到标注任务</div>
      <p>把当前预览的识别结果（{result?.lines.length ?? 0} 列 · {result?.chars.length ?? 0} 字）写入该页全部标注任务：无数据的播种，已有数据的覆盖。继续吗？</p>
      <div className="modal-actions"><button className="secondary-button" onClick={() => setDialog(null)}>取消</button><button className="primary-button" disabled={!!busy} onClick={saveToTasks}>{busy === "save" ? "写入中…" : "确认保存"}</button></div>
    </div></div>}
    {dialog === "batch" && <div className="modal-card-host"><div className="modal-backdrop" onClick={() => setDialog(null)}/><div className="modal-card">
      <div className="modal-title"><SlidersHorizontal size={18}/>批量预处理</div>
      <div className="modal-form">
        <label>书籍<select value={batchBook} onChange={e => setBatchBook(Number(e.target.value))}>{books.map(item => <option value={item.id} key={item.id}>{item.title}（{item.page_count} 页）</option>)}</select></label>
        <div className="modal-form-row">
          <label>起始页<input type="number" min={1} max={books.find(x => x.id === batchBook)?.page_count ?? 1} value={batchStart} onChange={e => setBatchStart(Number(e.target.value))}/></label>
          <label>结束页<input type="number" min={1} max={books.find(x => x.id === batchBook)?.page_count ?? 1} value={batchEnd} onChange={e => setBatchEnd(Number(e.target.value))}/></label>
        </div>
        <small>提示：已识别且内容未变的页面会命中缓存快速完成；批量任务同时出现在任务中心。</small>
      </div>
      <div className="modal-actions"><button className="secondary-button" onClick={() => setDialog(null)}>取消</button><button className="primary-button" disabled={!!busy || !batchBook || batchStart > batchEnd} onClick={startBatch}>{busy === "batch" ? "发起中…" : "开始批量处理"}</button></div>
    </div></div>}

    <ProgressToast token={token} job={toastJob} onDone={() => reloadLatest()}/>
    <div className="narrow-warning">预处理预览需要至少 1280px 的屏幕宽度，请放大窗口后继续。</div></main>;
}
