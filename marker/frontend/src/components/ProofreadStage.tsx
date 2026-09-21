import { useEffect, useMemo, useRef, useState } from "react";
import { Check, CheckCircle2, Crosshair, Eraser, Hand, ListOrdered, LoaderCircle, Maximize, Minus, Plus, Redo2, RotateCw, Search, SquareDashed, Trash2, Undo2 } from "lucide-react";
import AuthenticatedImage from "./AuthenticatedImage";
import ProofreadCanvas, { CanvasHandle, ProofBox } from "./ProofreadCanvas";
import { api, Assignment, CharacterEntry, Region, TextChar, TextLine, User, Workflow } from "../api";

const REGION_TYPES: { value: string; name: string }[] = [
  { value: "text", name: "正文" }, { value: "header", name: "题头" }, { value: "table", name: "表格" }, { value: "image", name: "图像" }, { value: "seal", name: "印章" },
];
const contains = (outer: [number, number, number, number], inner: [number, number, number, number]) => {
  const x = (inner[0] + inner[2]) / 2, y = (inner[1] + inner[3]) / 2;
  return x >= outer[0] && x <= outer[2] && y >= outer[1] && y <= outer[3];
};
type Snapshot = Pick<Workflow, "regions" | "lines" | "chars">;

type Props = {
  token: string;
  me: User;
  workflow: Workflow;
  step: 1 | 2 | 3;
  readOnly: boolean;
  dirty: boolean;
  resetToken: number;
  onChange: (fn: (value: Workflow) => Workflow) => void;
  onSave: () => Promise<unknown>;
  onComplete: () => Promise<void>;
  onReview: (action: "approve" | "return", comment: string) => Promise<void>;
  onAbandon: () => Promise<void>;
  onResetOcr: (mode: "all" | "columns") => Promise<void>;
  onSwitchAssignment: (id: number) => void;
  assignments: Assignment[];
};

const stepTitles = ["区域调整", "字框检查", "文字校对"];

export default function ProofreadStage({ token, me, workflow, step, readOnly, dirty, resetToken, onChange, onSave, onComplete, onReview, onAbandon, onResetOcr, onSwitchAssignment, assignments }: Props) {
  const canvasRef = useRef<CanvasHandle | null>(null);
  const undoStack = useRef<Snapshot[]>([]);
  const redoStack = useRef<Snapshot[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [currentKey, setCurrentKey] = useState<string | null>(null);
  const [drawMode, setDrawMode] = useState(false);
  const [showRegions, setShowRegions] = useState(step === 1);
  const [showColumns, setShowColumns] = useState(step !== 1);
  const [showChars, setShowChars] = useState(step !== 1);
  const [showNumbers, setShowNumbers] = useState(true);
  const [brightnessLocal, setBrightnessLocal] = useState(100);
  const [brightness, setBrightness] = useState(100);
  const [rotation, setRotation] = useState(0);
  const [zoomPercent, setZoomPercent] = useState(32);
  const [busy, setBusy] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CharacterEntry[]>([]);
  const [reviewComment, setReviewComment] = useState("");

  useEffect(() => { setShowRegions(step === 1); setShowColumns(step !== 1); setShowChars(step !== 1); setDrawMode(false); }, [step]);
  useEffect(() => { const timer = window.setTimeout(() => setBrightness(brightnessLocal), 140); return () => clearTimeout(timer); }, [brightnessLocal]);
  useEffect(() => { undoStack.current = []; redoStack.current = []; setSelectedKey(null); setCurrentKey(null); }, [resetToken]);
  useEffect(() => { if (step === 3 && !currentKey && workflow.chars.length) setCurrentKey(charKey(workflow.chars.find(x => x.status === "unchecked") ?? workflow.chars[0], 0)); }, [step, currentKey, workflow.chars]);
  useEffect(() => { const timer = setTimeout(() => canvasRef.current?.fit(), 400); return () => clearTimeout(timer); }, [workflow.page.id]);

  function charKey(char: TextChar, index: number) { return `char:${char.id ?? `n${index}`}`; }
  function rowIndexOf(kind: "region" | "line" | "char", key: string, value: Workflow) {
    const list = kind === "region" ? value.regions : kind === "line" ? value.lines : value.chars;
    return list.findIndex((x, i) => `${kind}:${x.id ?? `n${i}`}` === key);
  }
  function mutate(fn: (value: Workflow) => Workflow) {
    undoStack.current.push({ regions: workflow.regions, lines: workflow.lines, chars: workflow.chars });
    if (undoStack.current.length > 50) undoStack.current.shift();
    redoStack.current = [];
    onChange(fn);
  }
  function undo() {
    const snapshot = undoStack.current.pop();
    if (!snapshot) return;
    redoStack.current.push({ regions: workflow.regions, lines: workflow.lines, chars: workflow.chars });
    onChange((value) => ({ ...value, ...snapshot }));
    setSelectedKey(null);
  }
  function redo() {
    const snapshot = redoStack.current.pop();
    if (!snapshot) return;
    undoStack.current.push({ regions: workflow.regions, lines: workflow.lines, chars: workflow.chars });
    onChange((value) => ({ ...value, ...snapshot }));
    setSelectedKey(null);
  }

  const regionBoxes: ProofBox[] = useMemo(() => workflow.regions.map((x, i) => ({ key: `region:${x.id ?? `n${i}`}`, kind: "region", order: x.order_no, bbox: x.bbox })), [workflow.regions]);
  const columnBoxes: ProofBox[] = useMemo(() => workflow.lines.map((x, i) => ({ key: `line:${x.id ?? `n${i}`}`, kind: "line", order: x.order_no, bbox: x.bbox, text: x.ocr_text })), [workflow.lines]);
  const charBoxes: ProofBox[] = useMemo(() => workflow.chars.map((x, i) => ({ key: charKey(x, i), kind: "char", order: x.order_no, bbox: x.bbox, text: x.corrected_text || x.raw_text })), [workflow.chars]);

  const selectedCharIndex = workflow.chars.findIndex((x, i) => charKey(x, i) === selectedKey);
  const selectedChar = selectedCharIndex >= 0 ? workflow.chars[selectedCharIndex] : null;
  const currentCharIndex = workflow.chars.findIndex((x, i) => charKey(x, i) === currentKey);
  const currentChar = currentCharIndex >= 0 ? workflow.chars[currentCharIndex] : null;

  function patchChar(char: TextChar, patch: Partial<TextChar>) { mutate((value) => ({ ...value, chars: value.chars.map(x => x === char ? { ...x, ...patch } : x) })); }
  function moveCurrent(delta: number) {
    if (!workflow.chars.length) return;
    const next = Math.min(workflow.chars.length - 1, Math.max(0, currentCharIndex + delta));
    const key = charKey(workflow.chars[next], next);
    setCurrentKey(key);
    setSelectedKey(key);
  }
  async function search() { setResults(await api.searchCharacters(token, workflow.book.id, query)); }

  function createBox(bbox: [number, number, number, number]) {
    if (step === 1) {
      mutate((value) => ({ ...value, regions: [...value.regions, { region_type: "text", order_no: value.regions.length + 1, bbox, confirmed: false } as Region] }));
    } else if (step === 2) {
      const parent = workflow.regions.find(x => contains(x.bbox, bbox));
      if (!parent?.id) { window.alert("请先在区域调整中保存区域（新列需落在某个区域内）"); return; }
      mutate((value) => ({ ...value, lines: [...value.lines, { region_id: parent.id, order_no: value.lines.length + 1, bbox, char_size: 0, confirmed: false, needs_char_split: false, ocr_text: "" } as TextLine] }));
    } else {
      const parent = workflow.lines.find(x => contains(x.bbox, bbox));
      if (!parent?.id) { window.alert("请先在字框和列框中保存列（新字框需落在某个列框内）"); return; }
      mutate((value) => ({ ...value, chars: [...value.chars, { line_id: parent.id, order_no: value.chars.length + 1, bbox, raw_text: "", corrected_text: "", candidates: ["□"], confidence: 0, status: "unchecked" } as TextChar] }));
    }
  }
  function updateBox(key: string, bbox: [number, number, number, number]) {
    const kind = key.split(":")[0] as "region" | "line" | "char";
    mutate((value) => {
      const index = rowIndexOf(kind, key, value);
      if (index < 0) return value;
      const list = [...(kind === "region" ? value.regions : kind === "line" ? value.lines : value.chars)];
      list[index] = { ...list[index], bbox };
      return { ...value, regions: kind === "region" ? (list as Region[]) : value.regions, lines: kind === "line" ? (list as TextLine[]) : value.lines, chars: kind === "char" ? (list as TextChar[]) : value.chars };
    });
  }
  function removeSelected() {
    if (!selectedKey) return;
    const kind = selectedKey.split(":")[0] as "region" | "line" | "char";
    mutate((value) => {
      const index = rowIndexOf(kind, selectedKey, value);
      if (index < 0) return value;
      const list = [...(kind === "region" ? value.regions : kind === "line" ? value.lines : value.chars)];
      list.splice(index, 1);
      return { ...value, regions: kind === "region" ? (list as Region[]) : value.regions, lines: kind === "line" ? (list as TextLine[]) : value.lines, chars: kind === "char" ? (list as TextChar[]) : value.chars };
    });
    if (selectedKey === currentKey) setCurrentKey(null);
    setSelectedKey(null);
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const typing = event.target instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName);
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); event.shiftKey ? redo() : undo(); return; }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") { event.preventDefault(); redo(); return; }
      if (typing) return;
      if ((event.key === "Delete" || event.key === "Backspace") && selectedKey) { event.preventDefault(); removeSelected(); }
      if (step === 3 && event.key === "ArrowLeft") { event.preventDefault(); moveCurrent(-1); }
      if (step === 3 && event.key === "ArrowRight") { event.preventDefault(); moveCurrent(1); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function guard(run: () => Promise<void>, label: string) { if (busy) return; setBusy(label); try { await run(); } catch (error) { window.alert(error instanceof Error ? error.message : String(error)); } finally { setBusy(""); } }

  const currentColumn = workflow.lines.find(x => currentChar && (x.id === currentChar.line_id)) ?? null;
  const stripChars = currentColumn ? workflow.chars.map((x, i) => ({ char: x, key: charKey(x, i) })).filter(x => x.char.line_id === currentColumn.id).sort((a, b) => a.char.order_no - b.char.order_no) : [];
  const resplitCount = workflow.lines.filter(x => x.needs_char_split).length;

  return (
    <section className="proof-body">
      <div className="proof-toolbar">
        <div className="proof-tool-group">
          <button className="proof-tool" title="撤销 (Ctrl+Z)" onClick={undo} disabled={!undoStack.current.length}><Undo2 size={17}/>撤销</button>
          <button className="proof-tool" title="重做 (Ctrl+Shift+Z)" onClick={redo} disabled={!redoStack.current.length}><Redo2 size={17}/>重做</button>
        </div>
        <div className="proof-tool-group">
          <span className="proof-tool-label">图片深浅</span>
          <input type="range" min={50} max={150} value={brightnessLocal} onChange={(e) => setBrightnessLocal(Number(e.target.value))}/>
        </div>
        <div className="proof-tool-group">
          <button className="proof-tool icon" title="缩小" onClick={() => canvasRef.current?.zoomBy(0.85)}><Minus size={16}/></button>
          <span className="proof-zoom-value">{zoomPercent}%</span>
          <button className="proof-tool icon" title="放大" onClick={() => canvasRef.current?.zoomBy(1.18)}><Plus size={16}/></button>
        </div>
        <div className="proof-tool-group">
          <button className={`proof-tool toggle${showColumns ? " on-green" : ""}`} onClick={() => setShowColumns(!showColumns)}><SquareDashed size={15}/>列框</button>
          <button className={`proof-tool toggle${showChars ? " on-blue" : ""}`} onClick={() => setShowChars(!showChars)}><Crosshair size={15}/>字框</button>
          <button className={`proof-tool toggle${showNumbers ? " on-ink" : ""}`} onClick={() => setShowNumbers(!showNumbers)}><ListOrdered size={15}/>展示序号</button>
        </div>
        <div className="proof-tool-group">
          <button className={`proof-tool toggle${drawMode ? " on-orange" : ""}`} onClick={() => setDrawMode(!drawMode)} title="开启后在画布拖拽新增框">{step === 1 ? "增加区域" : step === 2 ? "增加列框" : "增加字框"}</button>
          <button className="proof-tool" title="旋转 90°" onClick={() => setRotation((rotation + 90) % 360)}><RotateCw size={16}/>旋转{rotation}°</button>
          <button className="proof-tool" onClick={() => { if (window.confirm("OCR 重置将把区域、列与字全部还原为最近一次识别结果（不可撤销），继续吗？")) guard(() => onResetOcr("all"), "reset"); }}><Eraser size={15}/>OCR重置</button>
        </div>
        <div className="proof-tool-group proof-page-select">
          <span className="proof-tool-label">选页</span>
          <select value={workflow.assignment.id} onChange={(e) => onSwitchAssignment(Number(e.target.value))}>
            {assignments.map(x => <option value={x.id} key={x.id}>第 {x.page_no} 页 · {x.status === "in_progress" ? "进行中" : x.status === "assigned" ? "待开始" : x.status === "returned" ? "已打回" : x.status}</option>)}
          </select>
        </div>
        {busy && <span className="proof-busy"><LoaderCircle className="spin" size={15}/>{busy === "reset" ? "正在重置…" : "处理中…"}</span>}
      </div>
      <div className="proof-main">
        <div className="proof-canvas-wrap">
          <div className="proof-rail-buttons">
            <button className={`proof-rail-button${drawMode ? "" : " active"}`} title="平移（拖动画布）" onClick={() => setDrawMode(false)}><Hand size={17}/></button>
            <button className="proof-rail-button" title="放大" onClick={() => canvasRef.current?.zoomBy(1.18)}><Plus size={17}/></button>
            <button className="proof-rail-button" title="缩小" onClick={() => canvasRef.current?.zoomBy(0.85)}><Minus size={17}/></button>
            <button className="proof-rail-button" title="适应画布" onClick={() => canvasRef.current?.fit()}><Maximize size={16}/></button>
          </div>
          <ProofreadCanvas ref={canvasRef} token={token} page={workflow.page} regions={regionBoxes} columns={columnBoxes} chars={charBoxes}
            showRegions={showRegions} showColumns={showColumns} showChars={showChars} showNumbers={showNumbers}
            selectedKey={selectedKey} currentKey={step === 3 ? currentKey : null} brightness={brightness / 100} rotation={rotation}
            drawMode={drawMode} createKind={step === 1 ? "region" : step === 2 ? "line" : "char"} readOnly={readOnly}
            onView={setZoomPercent} onSelect={setSelectedKey} onCreate={createBox} onUpdate={updateBox}/>
          {rotation !== 0 && <div className="proof-rotate-hint">旋转视图下暂不能新建/拖动框</div>}
          {step === 3 && stripChars.length > 0 && (
            <div className="proof-char-strip">
              <div className="strip-column-info">第 {currentColumn?.order_no} 列 · {stripChars.length} 字</div>
              <div className="strip-cells">
                {stripChars.map(({ char, key }) => (
                  <button key={key} className={`strip-cell${key === currentKey ? " current" : ""}${char.status === "confirmed" ? " done" : ""}`}
                    onClick={() => { setCurrentKey(key); setSelectedKey(key); }}>{char.corrected_text || char.raw_text || "□"}</button>
                ))}
              </div>
            </div>
          )}
        </div>
        <aside className="proof-panel">
          <div className="proof-panel-head"><span className="proof-step-no">{step}</span><div><h2>{stepTitles[step - 1]}</h2><p>{step === 1 ? "框选文字、图像、表格、印章等区域并调整类型。" : step === 2 ? "核对绿色列框与蓝色字框，可增删、拖拽微调。" : "逐字核对识别结果，方向键切换，点击字格跳转。"}</p></div></div>
          <div className="proof-thumbnail">
            <AuthenticatedImage src={`${api.base}/api/book-pages/${workflow.page.id}/image`} token={token} alt={`第 ${workflow.page.page_no} 页`}/>
            <div className="proof-thumbnail-overlay">
              {showRegions && regionBoxes.map(box => <span key={box.key} className="thumb-region" style={{ left: `${box.bbox[0] / workflow.page.width * 100}%`, top: `${box.bbox[1] / workflow.page.height * 100}%`, width: `${(box.bbox[2] - box.bbox[0]) / workflow.page.width * 100}%`, height: `${(box.bbox[3] - box.bbox[1]) / workflow.page.height * 100}%` }} onClick={() => setSelectedKey(box.key)}/>)}
              {showColumns && columnBoxes.map(box => <span key={box.key} className="thumb-column" style={{ left: `${box.bbox[0] / workflow.page.width * 100}%`, top: `${box.bbox[1] / workflow.page.height * 100}%`, width: `${(box.bbox[2] - box.bbox[0]) / workflow.page.width * 100}%`, height: `${(box.bbox[3] - box.bbox[1]) / workflow.page.height * 100}%` }} onClick={() => setSelectedKey(box.key)}/>)}
              {showChars && charBoxes.map(box => <span key={box.key} className="thumb-char" style={{ left: `${box.bbox[0] / workflow.page.width * 100}%`, top: `${box.bbox[1] / workflow.page.height * 100}%`, width: `${(box.bbox[2] - box.bbox[0]) / workflow.page.width * 100}%`, height: `${(box.bbox[3] - box.bbox[1]) / workflow.page.height * 100}%` }} onClick={() => setSelectedKey(box.key)}/>)}
            </div>
          </div>
          <div className="proof-stats">{workflow.regions.length} 区域 · {workflow.lines.length} 列 · {workflow.chars.length} 字{resplitCount > 0 ? ` · ${resplitCount} 列待重切` : ""}</div>
          {step === 1 && (
            <div className="proof-list">
              {workflow.regions.map((region, index) => { const key = `region:${region.id ?? `n${index}`}`; return (
                <div key={key} className={`proof-row${selectedKey === key ? " selected" : ""}`} onClick={() => setSelectedKey(key)}>
                  <span className="proof-row-no">{region.order_no}</span>
                  <select value={region.region_type} disabled={readOnly} onClick={(e) => e.stopPropagation()} onChange={(e) => mutate((value) => ({ ...value, regions: value.regions.map(x => x === region ? { ...x, region_type: e.target.value } : x) }))}>
                    {REGION_TYPES.map(type => <option value={type.value} key={type.value}>{type.name}</option>)}
                  </select>
                  <button className="proof-row-locate" title="定位" onClick={(e) => { e.stopPropagation(); canvasRef.current?.focusBox(region.bbox); }}><Crosshair size={14}/></button>
                </div>); })}
            </div>
          )}
          {step === 2 && (
            <div className="proof-list">
              {workflow.lines.map((line, index) => { const key = `line:${line.id ?? `n${index}`}`; return (
                <div key={key} className={`proof-row${selectedKey === key ? " selected" : ""}`} onClick={() => setSelectedKey(key)}>
                  <span className="proof-row-no col">{line.order_no}</span>
                  <input value={line.ocr_text} readOnly={readOnly} placeholder="（该列无文本）" onClick={(e) => e.stopPropagation()} onChange={(e) => mutate((value) => ({ ...value, lines: value.lines.map(x => x === line ? { ...x, ocr_text: e.target.value } : x) }))}/>
                  {line.needs_char_split && <span className="proof-row-flag">待重切</span>}
                  <button className="proof-row-locate" title="定位" onClick={(e) => { e.stopPropagation(); canvasRef.current?.focusBox(line.bbox); }}><Crosshair size={14}/></button>
                </div>); })}
            </div>
          )}
          {step === 3 && (currentChar ? (
            <div className="proof-char-card">
              <div className="proof-char-main">
                <b className="proof-char-glyph">{currentChar.corrected_text || currentChar.raw_text || "□"}</b>
                <div className="proof-char-meta">
                  <span>识别原文 <strong>{currentChar.raw_text || "□"}</strong></span>
                  <span>第 {currentChar.order_no} 字 · {currentChar.status === "confirmed" ? "已确认" : currentChar.status === "unclear" ? "无法辨识" : currentChar.status === "missing" ? "缺字" : "未核"}</span>
                </div>
                <div className="proof-char-nav">
                  <button onClick={() => moveCurrent(-1)}>上一字</button>
                  <button onClick={() => canvasRef.current?.focusBox(currentChar.bbox)}>定位</button>
                  <button onClick={() => moveCurrent(1)}>下一字</button>
                </div>
              </div>
              <label className="proof-char-input">校对字<input className="cjk-input" value={currentChar.corrected_text} readOnly={readOnly} onChange={(e) => patchChar(currentChar, { corrected_text: e.target.value })} autoFocus/></label>
              {currentChar.candidates.length > 0 && <div className="candidate-row">{currentChar.candidates.map(x => <button key={x} onClick={() => patchChar(currentChar, { corrected_text: x, status: "confirmed" })}>{x}</button>)}</div>}
              <div className="char-actions">
                <button onClick={() => patchChar(currentChar, { status: "confirmed" })}><CheckCircle2 size={15}/>清晰</button>
                <button onClick={() => patchChar(currentChar, { status: "unclear" })}>模糊</button>
                <button onClick={() => patchChar(currentChar, { status: "missing", corrected_text: "□" })}>缺字</button>
              </div>
              <div className="char-search">
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="字符 / U+码点 / IDS / 读音"/>
                <button onClick={() => guard(async () => { setResults(await api.searchCharacters(token, workflow.book.id, query)); }, "search")}><Search size={16}/></button>
              </div>
              <div className="glyph-grid">{results.map(x => <button key={`${x.id}-${x.unicode_codepoint}`} onClick={() => patchChar(currentChar, { corrected_text: x.character, custom_char_id: x.id, status: "confirmed" })}><b>{x.character || x.ids}</b><small>{x.unicode_codepoint}</small></button>)}</div>
            </div>
          ) : <div className="empty-state small"><Search size={24}/><span>本页暂无字框，请先完成字框和列框步骤</span></div>)}
          <div className="proof-panel-foot">
            {step === 2 && (
              <div className="proof-links">
                <button className="text-button" onClick={() => { if (window.confirm("将按最近一次识别结果重新生成列与字（保留当前区域），继续吗？")) guard(() => onResetOcr("columns"), "reset"); }}>自动重新分列和排序</button>
              </div>
            )}
            <div className="proof-task-info">
              <span>任务 #{workflow.assignment.id} · 第 {workflow.page.page_no}/{workflow.book.page_count} 页</span>
              <span>状态 {workflow.assignment.status === "in_progress" ? "进行中" : workflow.assignment.status === "returned" ? "已打回" : workflow.assignment.status} · 数据 v{workflow.assignment.version}</span>
            </div>
            <div className="proof-actions">
              <button className="secondary-button" disabled={!dirty || readOnly} onClick={() => guard(async () => { await onAbandon(); }, "abandon")} title="放弃未保存的修改，恢复到已保存版本"><Trash2 size={15}/>放弃</button>
              <button className="secondary-button" disabled={!dirty || readOnly} onClick={() => onSave().catch((error) => window.alert(error instanceof Error ? error.message : String(error)))}>保存</button>
              {me.role === "reviewer" || me.role === "admin" ? (
                <div className="review-box"><textarea value={reviewComment} onChange={(e) => setReviewComment(e.target.value)} placeholder="审核意见"/>
                  <button className="secondary-button" onClick={() => onReview("return", reviewComment).catch((error) => window.alert(error instanceof Error ? error.message : String(error)))}>打回</button>
                  <button className="primary-button" onClick={() => onReview("approve", reviewComment).catch((error) => window.alert(error instanceof Error ? error.message : String(error)))}><Check size={15}/>通过</button></div>
              ) : <button className="primary-button wide" disabled={!!busy} onClick={() => guard(() => onComplete(), "complete")}><Check size={16}/>完成任务</button>}
            </div>
          </div>
        </aside>
      </div>
      <div className="proof-shortcut-hint">{readOnly ? "只读模式" : "Ctrl+Z 撤销 · Delete 删除选中框 · 滚轮缩放 · 拖拽平移 · 右键（或开启增加字框后左键）拖拽新建"}</div>
    </section>
  );
}
