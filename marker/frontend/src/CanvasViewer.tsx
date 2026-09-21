import { useEffect, useMemo, useRef, useState } from "react";
import Konva from "konva";
import { Group, Image as KonvaImage, Label, Layer, Rect, Stage, Tag, Text, Transformer } from "react-konva";
import type { BookPage } from "./api";
import { api } from "./api";

export type CanvasBox = {
  id?: number;
  kind: "region" | "line" | "char" | "entity";
  label: string;
  color: string;
  bbox: [number, number, number, number];
};

type DraftRect = { x: number; y: number; width: number; height: number };

type Props = {
  token?: string;
  page: BookPage;
  boxes: CanvasBox[];
  selectedKey: string | null;
  createColor: string;
  createLabel: string;
  readOnly?: boolean;
  onSelect: (key: string | null) => void;
  onCreate: (bbox: [number, number, number, number]) => void;
  onUpdate: (key: string, bbox: [number, number, number, number]) => void;
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
    img.onload = () => {
      imageCache.set(cacheKey, img);
      URL.revokeObjectURL(objectUrl);
      resolve(img);
    };
    img.onerror = () => { URL.revokeObjectURL(objectUrl); reject(new Error("页面图片加载失败")); };
    if (!cached) {
      imageCache.set(cacheKey, img);
      img.src = objectUrl;
    }
  });
}

function boxKey(box: CanvasBox, index: number) {
  return `${box.kind}:${box.id ?? index}`;
}

export default function CanvasViewer({ token = localStorage.getItem("bencao_token") ?? "", page, boxes, selectedKey, createColor, createLabel, readOnly, onSelect, onCreate, onUpdate }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<Konva.Stage | null>(null);
  const transformerRef = useRef<Konva.Transformer | null>(null);
  const shapeRefs = useRef(new Map<string, Konva.Rect>());
  const drawStart = useRef<{ x: number; y: number } | null>(null);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [size, setSize] = useState({ width: 1000, height: 720 });
  const [scale, setScale] = useState(0.32);
  const [position, setPosition] = useState({ x: 80, y: 40 });
  const [draft, setDraft] = useState<DraftRect | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0].contentRect;
      setSize({ width: rect.width, height: rect.height });
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadImage(api.base + page.image_url, token)
      .then((img) => {
        if (!cancelled) setImage(img);
      })
      .catch(() => {
        if (!cancelled) setImage(null);
      });
    setPosition({ x: 80, y: 40 });
    return () => {
      cancelled = true;
    };
  }, [page.image_url, token]);

  useEffect(() => {
    const node = selectedKey ? shapeRefs.current.get(selectedKey) : null;
    if (node && transformerRef.current && !readOnly) {
      transformerRef.current.nodes([node]);
      transformerRef.current.getLayer()?.batchDraw();
    } else {
      transformerRef.current?.nodes([]);
    }
  }, [selectedKey, boxes, readOnly]);

  const selectedText = useMemo(() => boxes.find((box, index) => boxKey(box, index) === selectedKey)?.label ?? createLabel, [boxes, selectedKey, createLabel]);

  function pointerInImage() {
    const stage = stageRef.current;
    const pointer = stage?.getPointerPosition();
    if (!stage || !pointer) return null;
    return {
      x: (pointer.x - stage.x()) / scale,
      y: (pointer.y - stage.y()) / scale
    };
  }

  function clampDraft(rect: DraftRect): [number, number, number, number] {
    const x1 = Math.max(0, Math.min(page.width, rect.x));
    const y1 = Math.max(0, Math.min(page.height, rect.y));
    const x2 = Math.max(0, Math.min(page.width, rect.x + rect.width));
    const y2 = Math.max(0, Math.min(page.height, rect.y + rect.height));
    return [x1, y1, x2, y2];
  }

  function handleWheel(event: Konva.KonvaEventObject<WheelEvent>) {
    event.evt.preventDefault();
    const stage = stageRef.current;
    const pointer = stage?.getPointerPosition();
    if (!stage || !pointer) return;
    const oldScale = scale;
    const nextScale = Math.min(2.4, Math.max(0.08, oldScale * (event.evt.deltaY > 0 ? 0.92 : 1.08)));
    const mousePointTo = { x: (pointer.x - stage.x()) / oldScale, y: (pointer.y - stage.y()) / oldScale };
    setScale(nextScale);
    setPosition({ x: pointer.x - mousePointTo.x * nextScale, y: pointer.y - mousePointTo.y * nextScale });
  }

  function handleMouseDown(event: Konva.KonvaEventObject<MouseEvent>) {
    if (readOnly || event.evt.button !== 2) return;
    event.evt.preventDefault();
    const point = pointerInImage();
    if (!point) return;
    drawStart.current = point;
    onSelect(null);
    setDraft({ x: point.x, y: point.y, width: 0, height: 0 });
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
    const bbox = clampDraft(draft);
    if (Math.abs(bbox[2] - bbox[0]) >= 3 && Math.abs(bbox[3] - bbox[1]) >= 3) onCreate(bbox);
    drawStart.current = null;
    setDraft(null);
  }

  function updateFromNode(key: string, node: Konva.Rect) {
    const scaleX = node.scaleX();
    const scaleY = node.scaleY();
    node.scaleX(1);
    node.scaleY(1);
    const x = Math.max(0, node.x());
    const y = Math.max(0, node.y());
    const width = Math.max(3, node.width() * scaleX);
    const height = Math.max(3, node.height() * scaleY);
    onUpdate(key, [x, y, Math.min(page.width, x + width), Math.min(page.height, y + height)]);
  }

  return (
    <section className="canvas-pane">
      <div className="canvas-status">
        <span>第 {page.page_no} 页</span>
        <span>{Math.round(scale * 100)}%</span>
        <span>{boxes.length} 个框</span>
        <span>{selectedText}</span>
      </div>
      <div ref={containerRef} className="canvas-scroll" onContextMenu={(event) => event.preventDefault()}>
        <Stage
          ref={stageRef}
          width={size.width}
          height={size.height}
          scaleX={scale}
          scaleY={scale}
          x={position.x}
          y={position.y}
          draggable={!draft}
          onDragEnd={(event) => setPosition({ x: event.target.x(), y: event.target.y() })}
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onClick={(event) => {
            if (event.target === event.target.getStage()) onSelect(null);
          }}
        >
          <Layer>
            {image ? <KonvaImage image={image} width={page.width} height={page.height} /> : <Text text="页面加载中..." x={80} y={80} />}
            {boxes.map((box, index) => {
              const [x1, y1, x2, y2] = box.bbox;
              const key = boxKey(box, index);
              const active = key === selectedKey;
              return (
                <Group key={key}>
                  <Rect
                    ref={(node) => {
                      if (node) shapeRefs.current.set(key, node);
                      else shapeRefs.current.delete(key);
                    }}
                    x={x1}
                    y={y1}
                    width={x2 - x1}
                    height={y2 - y1}
                    fill={`${box.color}22`}
                    stroke={active ? "#111827" : box.color}
                    strokeWidth={active ? 7 : 4}
                    dash={box.kind === "char" ? [8, 7] : undefined}
                    draggable={!readOnly}
                    onClick={(event) => {
                      event.cancelBubble = true;
                      onSelect(key);
                    }}
                    onDragEnd={(event) => updateFromNode(key, event.target as Konva.Rect)}
                    onTransformEnd={(event) => updateFromNode(key, event.target as Konva.Rect)}
                  />
                  <Label x={x1} y={Math.max(0, y2 + 5)}>
                    <Tag fill={box.color} />
                    <Text text={box.label} fill="#ffffff" fontSize={18} padding={5} />
                  </Label>
                </Group>
              );
            })}
            {draft ? <Rect x={draft.x} y={draft.y} width={draft.width} height={draft.height} fill={`${createColor}22`} stroke={createColor} strokeWidth={4} dash={[12, 8]} /> : null}
            <Transformer ref={transformerRef} rotateEnabled={false} borderStroke="#111827" anchorFill="#ffffff" anchorStroke="#111827" />
          </Layer>
        </Stage>
      </div>
    </section>
  );
}
