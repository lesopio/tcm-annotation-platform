from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from threading import Lock
from typing import Any

import requests
from PIL import Image

from .ocr_config import effective_ocr_config
from .settings import settings

_OCR = None
_OCR_LOCK = Lock()


def _get_ocr():
    global _OCR
    with _OCR_LOCK:
        if _OCR is None:
            det = settings.ocr_det_model
            rec = settings.ocr_rec_model
            if not det or not rec:
                raise FileNotFoundError(
                    "OCR 模型路径未配置。请设置环境变量 BENCAO_OCR_DET_MODEL 和 BENCAO_OCR_REC_MODEL"
                )
            det_dir = Path(det)
            rec_dir = Path(rec)
            if not det_dir.exists() or not rec_dir.exists():
                raise FileNotFoundError(
                    f"PP-OCRv5 模型目录不存在: det={det}, rec={rec}"
                )
            from paddleocr import PaddleOCR

            _OCR = PaddleOCR(
                text_detection_model_dir=str(det_dir),
                text_recognition_model_dir=str(rec_dir),
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return _OCR


def _collect_texts(value: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(value, str):
        if value.strip():
            texts.append(value.strip())
    elif isinstance(value, dict):
        for key in ("rec_texts", "texts"):
            if key in value and isinstance(value[key], list):
                texts.extend(_collect_texts(value[key]))
        for key in ("rec_text", "text"):
            if key in value:
                texts.extend(_collect_texts(value[key]))
        if not texts:
            for item in value.values():
                texts.extend(_collect_texts(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            texts.extend(_collect_texts(item))
    elif hasattr(value, "json"):
        texts.extend(_collect_texts(value.json))
    elif hasattr(value, "to_dict"):
        texts.extend(_collect_texts(value.to_dict()))
    return texts


def recognize_crop(image_path: str | Path, bbox: list[float], padding: int = 8) -> str:
    with Image.open(image_path) as image:
        x1, y1, x2, y2 = bbox
        left = max(0, int(min(x1, x2)) - padding)
        top = max(0, int(min(y1, y2)) - padding)
        right = min(image.width, int(max(x1, x2)) + padding)
        bottom = min(image.height, int(max(y1, y2)) + padding)
        if right - left < 3 or bottom - top < 3:
            return ""
        crop = image.crop((left, top, right, bottom)).convert("RGB")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temp_path = Path(handle.name)
        try:
            crop.save(temp_path)
            result = _get_ocr().predict(str(temp_path))
        finally:
            temp_path.unlink(missing_ok=True)

    seen: set[str] = set()
    ordered: list[str] = []
    for text in _collect_texts(result):
        if text not in seen:
            ordered.append(text)
            seen.add(text)
    return "\n".join(ordered)


MOCK_CHARS = list("神农本经名医别录陶弘景唐本新补政和本草衍义")


def recognize_page_mock(image_path: str | Path) -> dict:
    """Stable local recognizer used until PaddleOCR-VL and PP-OCRv5 are wired in."""
    with Image.open(image_path) as image:
        width, height = image.size

    margin_x = max(40, round(width * 0.16))
    margin_y = max(40, round(height * 0.12))
    text_left = margin_x
    text_right = width - margin_x
    text_top = margin_y
    text_bottom = height - margin_y
    line_count = max(3, min(8, round((text_right - text_left) / max(120, width * 0.08))))
    line_width = max(44, round((text_right - text_left) / (line_count * 2.6)))

    regions = [
        {
            "region_type": "text",
            "order_no": 1,
            "bbox": [float(text_left), float(text_top), float(text_right), float(text_bottom)],
            "confirmed": False,
        }
    ]
    lines = []
    chars = []
    order_no = 1
    for index in range(line_count):
        x2 = text_right - index * round((text_right - text_left) / line_count)
        x1 = max(text_left, x2 - line_width)
        char_count = 6
        char_height = max(40, round((text_bottom - text_top) / (char_count + 4)))
        line = {
            "order_no": index + 1,
            "bbox": [float(x1), float(text_top), float(x2), float(text_bottom)],
            "char_size": float(char_height),
            "confirmed": False,
        }
        lines.append(line)
        for char_index in range(char_count):
            y1 = text_top + char_index * char_height
            y2 = y1 + char_height
            raw = MOCK_CHARS[(index * char_count + char_index) % len(MOCK_CHARS)]
            similar = [raw, MOCK_CHARS[(index + char_index + 3) % len(MOCK_CHARS)], "□"]
            chars.append(
                {
                    "line_order_no": index + 1,
                    "order_no": order_no,
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "raw_text": raw,
                    "corrected_text": raw,
                    "candidates": similar,
                    "confidence": 0.72,
                    "status": "unchecked",
                }
            )
            order_no += 1
    return {"regions": regions, "lines": lines, "chars": chars}


def recognize_page_layout_and_text(image_path: str | Path) -> dict:
    if settings.recognizer == "mock":
        return recognize_page_mock(image_path)
    if settings.recognizer == "paddle_vl_v5":
        raise NotImplementedError("PaddleOCR-VL + PP-OCRv5 接口已预留，当前本机阶段未启用真实模型。")
    raise ValueError(f"未知识别器: {settings.recognizer}")


def _plain(value: Any) -> Any:
    """Convert PaddleOCR SDK result objects into JSON-serializable values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump())
    if hasattr(value, "to_dict"):
        return _plain(value.to_dict())
    if hasattr(value, "__dict__"):
        return _plain({key: item for key, item in vars(value).items() if not key.startswith("_")})
    return str(value)


def call_paddleocr_vl_api(image_path: str | Path, config: dict[str, str] | None = None) -> dict:
    """Call the official asynchronous PaddleOCR Job API without loading a local model."""
    config = config or effective_ocr_config()
    if not config["access_token"]:
        raise RuntimeError("尚未配置 OCR 模型密钥；请由管理员在系统设置中填写")
    job_url = config["base_url"] or "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    headers = {"Authorization": f"bearer {config['access_token']}"}
    options = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useLayoutDetection": True,
        "useChartRecognition": False,
        "useSealRecognition": True,
        "useOcrForImageBlock": True,
        "temperature": 0,
        "topP": 1,
    }
    submitted: dict = {}
    for submit_attempt in range(1, 4):
        with Path(image_path).open("rb") as image_file:
            response = requests.post(
                job_url,
                headers=headers,
                data={"model": config["model"], "optionalPayload": json.dumps(options)},
                files={"file": (Path(image_path).name, image_file)},
                timeout=settings.paddleocr_request_timeout,
            )
        if response.status_code >= 400:
            # 携带响应体，便于上层识别"队列已满/限流"等可重试错误
            body = response.text[:200]
            if submit_attempt < 3 and ("10010" in body or "队列" in body or "稍后重试" in body):
                time.sleep(20 * submit_attempt)
                continue
            raise RuntimeError(f"HTTP {response.status_code}: {body}")
        submitted = response.json()
        break
    if submitted.get("code") != 0:
        raise RuntimeError(str(submitted.get("msg") or "OCR 任务提交失败"))
    job_id = str(submitted.get("data", {}).get("jobId") or "")
    if not job_id:
        raise RuntimeError("OCR 服务未返回任务 ID")

    deadline = time.monotonic() + settings.paddleocr_poll_timeout
    while time.monotonic() < deadline:
        status_response = requests.get(f"{job_url}/{job_id}", headers=headers, timeout=settings.paddleocr_request_timeout)
        status_response.raise_for_status()
        status_payload = status_response.json()
        if status_payload.get("code") != 0:
            raise RuntimeError(str(status_payload.get("msg") or "OCR 状态查询失败"))
        status_data = status_payload.get("data") or {}
        state = status_data.get("state")
        if state == "failed":
            raise RuntimeError(str(status_data.get("errorMsg") or "OCR 远端任务失败"))
        if state == "done":
            json_url = str((status_data.get("resultUrl") or {}).get("jsonUrl") or "")
            if not json_url:
                raise RuntimeError("OCR 任务完成但未返回结果地址")
            result_response = requests.get(json_url, timeout=settings.paddleocr_request_timeout)
            result_response.raise_for_status()
            layout_results: list[dict] = []
            raw_lines: list[dict] = []
            for line in result_response.text.splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                raw_lines.append(item)
                result = item.get("result") if isinstance(item, dict) else None
                if isinstance(result, dict):
                    values = result.get("layoutParsingResults") or result.get("layout_parsing_results") or []
                    if isinstance(values, list):
                        layout_results.extend(value for value in values if isinstance(value, dict))
            return {"jobId": job_id, "layoutParsingResults": layout_results, "rawLines": raw_lines}
        time.sleep(2)
    raise TimeoutError(f"OCR 任务等待超过 {settings.paddleocr_poll_timeout:g} 秒")


def normalize_paddleocr_vl_response(raw: dict) -> dict:
    """Normalize tolerant subsets of official responses into editable preannotations.

    Raw responses are always retained. Unknown response shapes deliberately produce
    an empty, manually editable workflow rather than fabricated character boxes.
    """
    pages = raw.get("pages") or raw.get("layoutParsingResults") or raw.get("layout_parsing_results") or []
    if isinstance(pages, dict):
        pages = [pages]
    page = pages[0] if pages else raw
    pruned = page.get("pruned_result") or page.get("prunedResult") or page.get("raw") or page
    if not isinstance(pruned, dict):
        return {"regions": [], "lines": [], "chars": [], "warnings": ["API 返回结构无法解析"]}

    regions: list[dict] = []
    lines: list[dict] = []
    chars: list[dict] = []
    blocks = (
        pruned.get("parsing_res_list")
        or pruned.get("parsingResList")
        or pruned.get("layout_det_res", {}).get("boxes")
        or pruned.get("layoutDetRes", {}).get("boxes")
        or []
    )
    type_map = {
        "text": "text", "paragraph": "text", "title": "header", "header": "header",
        "table": "table", "figure": "image", "image": "image", "seal": "seal", "stamp": "seal",
    }
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        bbox = block.get("bbox") or block.get("block_bbox") or block.get("coordinate") or block.get("box")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        label = str(block.get("label") or block.get("block_label") or block.get("type") or "text").lower()
        region_type = next((value for key, value in type_map.items() if key in label), "text")
        regions.append({"region_type": region_type, "order_no": index + 1, "bbox": bbox, "confirmed": False})
        text = str(block.get("content") or block.get("block_content") or block.get("text") or "")
        if region_type in ("text", "header"):
            lines.append({
                "region_order_no": index + 1,
                "order_no": len(lines) + 1,
                "bbox": bbox,
                "char_size": 0,
                "confirmed": False,
                "needs_char_split": True,
                "ocr_text": text,
            })
    return {"regions": regions, "lines": lines, "chars": chars, "warnings": [] if regions else ["未从 API 结果提取到坐标，保留原始响应供适配"]}
