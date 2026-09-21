import { useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import Konva from "konva";
import { Circle, Group, Image as KonvaImage, Layer, Rect, Stage, Text, Transformer } from "react-konva";
import type { BookPage } from "../api";
import { api } from "../api";

export type ProofBox = {
  key: string;
  kind: "region" | "line" | "char";
  order: number;
  bbox: [number, number, number, number];
  text?: string;
};

export const PROOF_COLORS = { region: "#c2410c", column: "#0aa870", char: "#4483e4", current: "#e02d2d", select: "#111827" };

type DraftRect = { x: number; y: number; width: number; height: number };

export type CanvasHandle = {
  fit: () => void;
  zoomBy: (factor: number) => void;
  focusBox: (bbox: [number, number, number, number]) => void;
};

type Props = {
  token: string;
  page: BookPage;
  regions: ProofBox[];
  columns: ProofBox[];
  chars: ProofBox[];
  showRegions: boolean;
  showColumns: boolean;
  showChars: boolean;
  showNumbers: boolean;
  selectedKey: string | null;
  currentKey: string | null;
  brightness: number;
  rotation: number;
  drawMode: boolean;
  createKind: ProofBox["kind"];
  readOnly: boolean;
  onView?: (zoomPercent: number) => void;
  onSelect: (key: string | null) => void;
  onCreate: (bbox: [number, number, number, number]) => void;
  onUpdate: (key: string, bbox: [number, number, number, number]) => void;
  ref?: React.Ref<CanvasHandle>;
};

const imageCache = new Map<string, HTMLImageElement>();

async function loadImage(src: string, token: string) {
  const cacheKey = `${token.slice(-12)}:${src}`;
  const cached = imageCache.get(cacheKey);
  if (cached?.complete) return Promise.resolve(cached);
  const response = await fetch(src, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error("页面图片加载失败");
  const objectUrl = URL.createObjectURL(await response.blob());
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const img = cached ?? new window.Image();
    img.onload = () => { imageCache.set(cacheKey, img); URL.revokeObjectURL(objectUrl); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(objectUrl); reject(new Error("页面图片加载失败")); };
    if (!cached) { imageCache.set(cacheKey, img); img.src = objectUrl; }
  });
}

export default function ProofreadCanvas({ token, page, regions, columns, chars, showRegions, showColumns, showChars, showNumbers, selectedKey, currentKey, brightness, rotation, drawMode, createKind, readOnly, onView, onSelect, onCreate, onUpdate, ref }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<Konva.Stage | null>(null);
  const transformerRef = useRef<Konva.Transformer | null>(null);
  const imageRef = useRef<Konva.Image | null>(null);
  const shapeRefs = useRef(new Map<string, Konva.Rect>());
  const drawStart = useRef<{ x: number; y: number } | null>(null);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [size, setSize] = useState({ width: 1000, height: 720 });
  const [scale, setScale] = useState(0.32);
  const [position, setPosition] = useState({ x: 60, y: 30 });
  const [draft, setDraft] = useState<DraftRect | null>(null);

  useEffect(() => { onView?.(Math.round(scale * 100)); }, [scale]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver((entries) => setSize({ width: entries[0].contentRect.width, height: entries[0].contentRect.height }));
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadImage(api.base + page.image_url, token).then((img) => { if (!cancelled) setImage(img); }).catch(() => { if (!cancelled) setImage(null); });
    return () => { cancelled = true; };
  }, [page.image_url, token]);

  // 图片深浅：滤镜需 cache 后生效，节流到亮度提交时执行
  useEffect(() => {
    const node = imageRef.current;
    if (!node || !image) return;
    node.filters(brightness === 1 ? [] : [Konva.Filters.Brighten]);
    node.brightness(brightness - 1);
    node.cache({ pixelRatio: 0.5 });
    node.getLayer()?.batchDraw();
  }, [image, brightness]);

  useEffect(() => {
    const node = selectedKey ? shapeRefs.current.get(selectedKey) : null;
    if (node && transformerRef.current && !readOnly) {
      transformerRef.current.nodes([node]);
      transformerRef.current.getLayer()?.batchDraw();
    } else {
      transformerRef.current?.nodes([]);
    }
  }, [selectedKey, regions, columns, chars, readOnly]);

  useImperativeHandle(ref, () => ({
    fit: () => { const fitScale = Math.min((size.width - 40) / page.width, (size.height - 40) / page.height); setScale(fitScale); setPosition({ x: (size.width - page.width * fitScale) / 2, y: (size.height - page.height * fitScale) / 2 }); },
    zoomBy: (factor: number) => zoomAt(factor, stageRef.current?.getPointerPosition() ?? { x: size.width / 2, y: size.height / 2 }),
    focusBox: (bbox: [number, number, number, number]) => {
      const boxWidth = Math.max(40, bbox[2] - bbox[0]), boxHeight = Math.max(40, bbox[3] - bbox[1]);
      const focusScale = Math.min(1.6, Math.max(0.15, Math.min(size.width / (boxWidth * 4), size.height / (boxHeight * 2.5))));
      setScale(focusScale);
      setPosition({ x: size.width / 2 - ((bbox[0] + bbox[2]) / 2) * focusScale, y: size.height / 2 - ((bbox[1] + bbox[3]) / 2) * focusScale });
    },
  }), [size, page.width, page.height]);

  const badge = useMemo(() => Math.max(30, Math.min(170, 30 / scale)), [scale]);
  const smallBadge = useMemo(() => Math.max(20, Math.min(110, 18 / scale)), [scale]);
  const stroke = (weight: number) => Math.max(1, weight / scale);

  function zoomAt(factor: number, pointer: { x: number; y: number }) {
    const nextScale = Math.min(3, Math.max(0.06, scale * factor));
    const anchor = { x: (pointer.x - position.x) / scale, y: (pointer.y - position.y) / scale };
    setScale(nextScale);
    setPosition({ x: pointer.x - anchor.x * nextScale, y: pointer.y - anchor.y * nextScale });
  }

  function pointerInImage() {
    const stage = stageRef.current;
    const pointer = stage?.getPointerPosition();
    if (!stage || !pointer) return null;
    return { x: (pointer.x - position.x) / scale, y: (pointer.y - position.y) / scale };
  }

  function handleWheel(event: Konva.KonvaEventObject<WheelEvent>) {
    event.evt.preventDefault();
    const pointer = stageRef.current?.getPointerPosition();
    if (pointer) zoomAt(event.evt.deltaY > 0 ? 0.9 : 1.1, pointer);
  }

  function beginDraw(event: Konva.KonvaEventObject<MouseEvent>) {
    if (readOnly || rotation !== 0) return;
    const point = pointerInImage();
    if (!point) return;
    event.evt.preventDefault();
    drawStart.current = point;
    onSelect(null);
    setDraft({ x: point.x, y: point.y, width: 0, height: 0 });
  }

  function handleMouseDown(event: Konva.KonvaEventObject<MouseEvent>) {
    if (event.evt.button === 2 || (drawMode && event.evt.button === 0 && event.target === event.target.getStage())) beginDraw(event);
  }

  function handleMouseMove() {
    if (!drawStart.current) return;
    const point = pointerInImage();
    if (!point) return;
    setDraft({ x: drawStart.current.x, y: drawStart.current.y, width: point.x - drawStart.current.x, height: point.y - drawStart.current.y });
  }

  function handleMouseUp(event: Konva.KonvaEventObject<MouseEvent>) {
    if (!draft) return;
    event.evt.preventDefault();
    const bbox: [number, number, number, number] = [
      Math.max(0, Math.min(page.width, draft.x)), Math.max(0, Math.min(page.height, draft.y)),
      Math.max(0, Math.min(page.width, draft.x + draft.width)), Math.max(0, Math.min(page.height, draft.y + draft.height)),
    ];
    if (bbox[2] - bbox[0] >= 3 && bbox[3] - bbox[1] >= 3) onCreate(bbox);
    drawStart.current = null;
    setDraft(null);
  }

  function updateFromNode(key: string, node: Konva.Rect) {
    const scaleX = node.scaleX(), scaleY = node.scaleY();
    node.scaleX(1); node.scaleY(1);
    const x = Math.max(0, node.x()), y = Math.max(0, node.y());
    const width = Math.max(3, node.width() * scaleX), height = Math.max(3, node.height() * scaleY);
    onUpdate(key, [x, y, Math.min(page.width, x + width), Math.min(page.height, y + height)]);
  }

  function renderBox(box: ProofBox) {
    const [x1, y1, x2, y2] = box.bbox;
    const active = box.key === selectedKey;
    const isCurrent = box.key === currentKey;
    const color = box.kind === "region" ? PROOF_COLORS.region : box.kind === "line" ? PROOF_COLORS.column : PROOF_COLORS.char;
    const width = Math.max(4, x2 - x1), height = Math.max(4, y2 - y1);
    const interactive = !readOnly && rotation === 0;
    return (
      <Group key={box.key}>
        <Rect
          ref={(node) => { if (node) shapeRefs.current.set(box.key, node); else shapeRefs.current.delete(box.key); }}
          x={x1} y={y1} width={width} height={height}
          fill={isCurrent ? "rgba(224,45,45,0.14)" : box.kind === "line" ? "rgba(10,168,112,0.08)" : box.kind === "region" ? "rgba(194,65,12,0.07)" : "rgba(68,131,228,0.05)"}
          stroke={isCurrent ? PROOF_COLORS.current : active ? PROOF_COLORS.select : color}
          strokeWidth={isCurrent ? stroke(5) : active ? stroke(6) : stroke(box.kind === "char" ? 1.5 : 3)}
          draggable={interactive}
          onClick={(event) => { event.cancelBubble = true; onSelect(box.key); }}
          onDragEnd={(event) => updateFromNode(box.key, event.target as Konva.Rect)}
          onTransformEnd={(event) => updateFromNode(box.key, event.target as Konva.Rect)}
        />
        {showNumbers && box.kind === "line" && (
          <Group x={(x1 + x2) / 2} y={y1} onClick={(event) => { event.cancelBubble = true; onSelect(box.key); }}>
            <Circle radius={badge / 2} fill={active ? PROOF_COLORS.select : PROOF_COLORS.column} stroke="#ffffff" strokeWidth={stroke(2)} />
            <Text text={String(box.order)} width={badge} height={badge} offsetX={badge / 2} offsetY={badge / 2} align="center" verticalAlign="middle" fill="#ffffff" fontSize={badge * 0.42} fontStyle="bold" />
          </Group>
        )}
        {showNumbers && box.kind === "region" && (
          <Group x={x1} y={y1} onClick={(event) => { event.cancelBubble = true; onSelect(box.key); }}>
            <Circle radius={badge / 2} x={badge / 2} y={badge / 2} fill={active ? PROOF_COLORS.select : PROOF_COLORS.region} stroke="#ffffff" strokeWidth={stroke(2)} />
            <Text text={String(box.order)} width={badge} height={badge} align="center" verticalAlign="middle" fill="#ffffff" fontSize={badge * 0.42} fontStyle="bold" />
          </Group>
        )}
        {showNumbers && box.kind === "char" && (
          <Group x={x2} y={y1} onClick={(event) => { event.cancelBubble = true; onSelect(box.key); }}>
            <Rect width={smallBadge} offsetX={smallBadge} fill="#ffffff" stroke={isCurrent ? PROOF_COLORS.current : PROOF_COLORS.char} strokeWidth={stroke(1.5)} />
            <Text text={String(box.order)} width={smallBadge} height={smallBadge} align="center" verticalAlign="middle" fill={isCurrent ? PROOF_COLORS.current : PROOF_COLORS.char} fontSize={smallBadge * 0.55} />
          </Group>
        )}
      </Group>
    );
  }

  return (
    <div ref={containerRef} className="proof-canvas-scroll" onContextMenu={(event) => event.preventDefault()}>
      <Stage
        ref={stageRef} width={size.width} height={size.height} scaleX={scale} scaleY={scale} x={position.x} y={position.y}
        draggable={!draft && !drawMode}
        onDragEnd={(event) => setPosition({ x: event.target.x(), y: event.target.y() })}
        onWheel={handleWheel} onMouseDown={handleMouseDown} onMouseMove={handleMouseMove} onMouseUp={handleMouseUp}
        onDblClick={() => stageRef.current && zoomAt(1.25, stageRef.current.getPointerPosition() ?? { x: size.width / 2, y: size.height / 2 })}
        onClick={(event) => { if (event.target === event.target.getStage()) onSelect(null); }}
      >
        <Layer>
          <Group rotation={rotation} x={page.width / 2} y={page.height / 2} offsetX={page.width / 2} offsetY={page.height / 2}>
            {image ? <KonvaImage ref={imageRef} image={image} width={page.width} height={page.height} listening={false} /> : <Text text="页面图片加载中…" x={80} y={80} fontSize={48} fill="#7d7469" />}
            {showRegions && regions.map(renderBox)}
            {showColumns && columns.map(renderBox)}
            {showChars && chars.map(renderBox)}
            {draft ? <Rect x={draft.x} y={draft.y} width={draft.width} height={draft.height} fill="rgba(68,131,228,0.12)" stroke={PROOF_COLORS.char} strokeWidth={stroke(2)} dash={[14, 10]} listening={false} /> : null}
          </Group>
          <Transformer ref={transformerRef} rotateEnabled={false} borderStroke={PROOF_COLORS.select} anchorFill="#ffffff" anchorStroke={PROOF_COLORS.select} anchorSize={9} borderStrokeWidth={2} />
        </Layer>
      </Stage>
    </div>
  );
}
