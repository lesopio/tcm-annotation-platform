"""预处理管线 v4：主版框检测 → 版框内墨迹投影切列 → 每列字格切分与文字对应。

核心：不再按几何等分猜列位置，而是对页面像素做**墨迹投影**——
- 先从横竖长线检测古籍页面的主版框，云端版面块只提供文字，不再充当外层区域；
- 二值化得到墨迹掩码，沿 x 统计每列墨迹占比，剔除贯穿整列的细竖线（界栏/版框），
  按墨迹真实分布切出列边界（古籍从右向左）；
- 列框 y 范围按列内墨迹收紧；区域框也按其列的墨迹并集校正；
- 区域裁剪再识别提供文本；文本行数与投影列数一致时逐列对应，
  不一致时按序分摊并逐列补识别（每页上限 COLUMN_REFILL_LIMIT 次）；
- 每列字格优先按列内横向墨迹投影的真实字间隙切分，无间隙时按字数均分。

数据形状与 seed_assignment_from_recognition 对齐：
regions（版面区域）/ lines（列框，含 ocr_text）/ chars（字框，raw_text=corrected_text）。
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from .ocr_service import call_paddleocr_vl_api


def clean_content(content: str) -> str:
    """去掉模型返回中的 HTML/Markdown 表格标记，只留文字。"""
    text = re.sub(r"<[^>]+>", "", content or "")
    lines: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(re.fullmatch(r"[-: ]*", cell) for cell in cells):
                continue  # markdown 分隔行
            line = "".join(cells)
        else:
            line = line.replace("|", "")
        lines.append(line)
    return "\n".join(lines)

Caller = Callable[[str | Path, dict[str, str] | None], dict]

REGION_TYPE_MAP = {
    "text": "text", "paragraph": "text", "title": "header", "header": "header",
    "table": "table", "figure": "image", "image": "image", "seal": "seal", "stamp": "seal",
}
# 古籍中的"表格"多为多列竖排文字（条目网格），同样按文字切块再识别
TEXT_REGION_TYPES = {"text", "header", "table"}
CROP_PADDING = 6
COLUMN_SPLIT_RATIO = 1.6  # 几何回退路径：块宽超过单列宽线索的该倍数即判定多列
COLUMN_REFILL_LIMIT = 24  # 每页最多补识别的列数（防云端限流）
CHAR_CELL_MIN = 8.0  # 字格最短边（页面像素）
CHAR_CELL_RATIO = (0.5, 2.0)  # 竖排列字格 高/宽 合理区间
RULE_LINE_MAX_WIDTH = 10  # 视为界栏/版框细竖线的最大宽度（像素）
RULE_LINE_MIN_FILL = 0.88  # 细竖线需贯穿的墨迹占比
SPAN_MIN_ASPECT = 2.2  # 列框高宽比下限（横条/水印花纹不是列）
WATERMARK_MAX_UNIT = 14  # 水印重复单元的最大长度
FRAME_ROW_MIN_FILL = 0.36  # 主版框上下横线至少覆盖页面宽度比例
FRAME_COL_MIN_FILL = 0.48  # 主版框左右竖线至少覆盖版框高度比例
FRAME_MIN_SIZE_RATIO = 0.45  # 版框宽高相对整页的最小比例


def region_type_of(label: str) -> str:
    label = (label or "text").lower()
    return next((value for key, value in REGION_TYPE_MAP.items() if key in label), "text")


def parse_blocks(raw: dict) -> list[dict]:
    """从 PaddleOCR-VL 响应提取 [{label, bbox, content}]，兼容多种字段命名。"""
    pages = raw.get("layoutParsingResults") or raw.get("layout_parsing_results") or raw.get("pages") or []
    if isinstance(pages, dict):
        pages = [pages]
    page = pages[0] if pages else raw
    pruned = page.get("prunedResult") or page.get("pruned_result") or page.get("raw") or {}
    if not isinstance(pruned, dict):
        return []
    blocks = pruned.get("parsing_res_list") or pruned.get("parsingResList") or pruned.get("layout_det_res", {}).get("boxes") or pruned.get("layoutDetRes", {}).get("boxes") or []
    result: list[dict] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        bbox = block.get("block_bbox") or block.get("bbox") or block.get("coordinate") or block.get("box")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        result.append({
            "label": str(block.get("block_label") or block.get("label") or block.get("type") or "text"),
            "bbox": [float(value) for value in bbox],
            "content": clean_content(str(block.get("block_content") or block.get("content") or block.get("text") or "")),
        })
    return result


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2] if ordered else 0.0


def chunk_texts(texts: list[str], count: int) -> list[str]:
    """把文本行按列数分配：行数一致逐列对应；多则依序分组；少则合并均分。"""
    if count <= 0:
        return []
    if len(texts) == count:
        return list(texts)
    if len(texts) > count:
        base, extra = divmod(len(texts), count)
        groups: list[str] = []
        cursor = 0
        for index in range(count):
            take = base + (1 if index < extra else 0)
            groups.append("".join(texts[cursor:cursor + take]))
            cursor += take
        return groups
    merged = "".join(texts)
    per = -(-len(merged) // count)
    return [merged[index * per:(index + 1) * per] for index in range(count)]


def split_bbox_into_columns(bbox: list[float], count: int, texts: list[str]) -> list[tuple[list[float], str]]:
    """竖排块几何切列（回退路径）：沿 x 等分 count 列、首列在最右；文本按阅读序分配。"""
    x1, y1, x2, y2 = bbox
    column_width = (x2 - x1) / count
    segments: list[tuple[list[float], str]] = []
    for index, text in enumerate(chunk_texts(texts, count)):
        right = x2 - index * column_width
        segments.append(([right - column_width, y1, right, y2], text))
    return segments


def split_block_into_lines(bbox: list[float], content: str) -> list[tuple[list[float], str]]:
    """把一个识别块按其多行文本切为行框。竖排（高>宽）按列宽切且第一列在最右（古籍从右向左）。"""
    texts = [line for line in content.split("\n") if line.strip()]
    if not texts:
        return []
    x1, y1, x2, y2 = bbox
    width, height = x2 - x1, y2 - y1
    count = len(texts)
    segments: list[tuple[list[float], str]] = []
    if height > width:  # 竖排：列沿 x 方向并排，首列在最右
        column_width = width / count
        for index, text in enumerate(texts):
            right = x2 - index * column_width
            segments.append(([right - column_width, y1, right, y2], text))
    else:  # 横排：行沿 y 方向堆叠
        row_height = height / count
        for index, text in enumerate(texts):
            segments.append(([x1, y1 + index * row_height, x2, y1 + (index + 1) * row_height], text))
    return segments


def derive_columns(blocks: list[dict]) -> list[dict]:
    """区域裁剪块 → 列框候选（投影失败时的几何回退）。"""
    median_width = _median([block["bbox"][2] - block["bbox"][0] for block in blocks])
    columns: list[dict] = []
    for block in blocks:
        bbox, content = block["bbox"], block["content"]
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        texts = [line for line in content.split("\n") if line.strip()]
        char_total = sum(len(text) for text in texts)
        self_hint = height / max(1, max((len(text) for text in texts), default=1))
        hints = [value for value in (median_width, self_hint) if value > 0]
        hint = min(hints) if hints else 0.0
        cell_hint = ((width * height) / char_total) ** 0.5 if char_total >= 4 and width > 0 and height > 0 else 0.0
        column_count = 0
        if height > width and len(texts) >= 2 and hint > 0 and width > COLUMN_SPLIT_RATIO * hint:
            column_count = max(2, round(width / hint))
            if abs(len(texts) - column_count) <= 1:
                column_count = len(texts)
            column_count = min(column_count, len(texts))
        elif height > width and len(texts) < 2 and cell_hint > 0 and width > COLUMN_SPLIT_RATIO * cell_hint:
            column_count = max(2, min(round(width / cell_hint), char_total // 2))
        if column_count >= 2:
            for column_bbox, text in split_bbox_into_columns(bbox, column_count, texts):
                columns.append({"bbox": column_bbox, "content": text, "uncertain": column_count != len(texts)})
        elif len(texts) >= 2:
            for line_bbox, text in split_block_into_lines(bbox, content):
                columns.append({"bbox": line_bbox, "content": text, "uncertain": False})
        elif content.strip():
            columns.append({"bbox": bbox, "content": content, "uncertain": False})
    return columns


def split_line_into_chars(bbox: list[float], text: str) -> list[tuple[list[float], str]]:
    """把行框按字数均分为单字框：竖排列自上而下切高度，横排行自左向右切宽度。"""
    chars = [char for char in text if char.strip()]
    if not chars:
        return []
    x1, y1, x2, y2 = bbox
    width, height = x2 - x1, y2 - y1
    count = len(chars)
    result: list[tuple[list[float], str]] = []
    if height >= width:  # 竖排列：字沿高度排列
        char_height = height / count
        for index, char in enumerate(chars):
            result.append(([x1, y1 + index * char_height, x2, y1 + (index + 1) * char_height], char))
    else:  # 横排行：字沿宽度排列
        char_width = width / count
        for index, char in enumerate(chars):
            result.append(([x1 + index * char_width, y1, x1 + (index + 1) * char_width, y2], char))
    return result


def char_cells_plausible(bbox: list[float], char_count: int) -> bool:
    """字格合理性：字格最短边与长宽比在常见范围（用于标记 needs_char_split）。"""
    if char_count <= 0:
        return True
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    low, high = CHAR_CELL_RATIO
    if height >= width:  # 竖排列：字沿高度
        cell = height / char_count
        return cell >= CHAR_CELL_MIN and low <= cell / width <= high
    cell = width / char_count
    return cell >= CHAR_CELL_MIN and low <= cell / height <= high


# ---------- 墨迹投影 ----------

def _ink_mask(gray: np.ndarray) -> np.ndarray:
    """自适应二值化：以中值（纸色）72% 为阈，更暗者视为墨。"""
    threshold = float(np.median(gray)) * 0.72
    return gray < max(60.0, min(200.0, threshold))


def _runs(flags: np.ndarray, merge_gap: int, min_size: int) -> list[list[int]]:
    """布尔序列 → [start, end) 连续段；相邻间隔 ≤ merge_gap 合并；短于 min_size 丢弃。"""
    runs: list[list[int]] = []
    start: int | None = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append([start, index])
            start = None
    if start is not None:
        runs.append([start, len(flags)])
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [run for run in merged if run[1] - run[0] >= min_size]


def _erase_rule_lines(ink: np.ndarray) -> np.ndarray:
    """剔除贯穿整列的竖线（界栏及较厚外框）：置零而非删列，保持 x 坐标不变。"""
    fill = ink.mean(axis=0)
    line_mask = np.zeros(ink.shape[1], dtype=bool)
    for run in _runs(fill >= RULE_LINE_MIN_FILL, merge_gap=2, min_size=1):
        if run[1] - run[0] <= RULE_LINE_MAX_WIDTH:
            line_mask[run[0]:run[1]] = True
    # 扫描页外框常达 20~40px，虽不属于“细线”，但其贯穿率显著高于正文笔画。
    for run in _runs(fill >= 0.70, merge_gap=2, min_size=1):
        if run[1] - run[0] <= 45:
            line_mask[run[0]:run[1]] = True
    if line_mask.any():
        erased = ink.copy()
        erased[:, line_mask] = False
        return erased, np.flatnonzero(line_mask)
    return ink, np.array([], dtype=int)


def _is_watermark(text: str) -> bool:
    """重复短单元（如"图书馆版权所有"循环、银行名循环）视为扫描件水印文字。"""
    stripped = text.strip()
    length = len(stripped)
    if length < 8:
        return False
    for unit_len in range(2, min(WATERMARK_MAX_UNIT, length // 3) + 1):
        if stripped.startswith(stripped[:unit_len] * 3):
            return True
    return False


def _x_overlap_ratio(a: list[float], b: list[float]) -> float:
    """两列框 x 方向重叠比例（相对较窄者）。"""
    overlap = min(a[2], b[2]) - max(a[0], b[0])
    if overlap <= 0:
        return 0.0
    return overlap / max(1.0, min(a[2] - a[0], b[2] - b[0]))


CJK_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _is_margin_junk(bbox: list[float], text: str, page_width: float) -> bool:
    """版框外杂迹：贴页边的短文本列（装订边噪声），或基本不含汉字的短列。"""
    chars = [char for char in text if char.strip()]
    if not chars:
        return True
    if len(chars) <= 4 and (bbox[2] <= 70 or bbox[0] >= page_width - 70):
        return True
    return len(chars) <= 3 and sum(1 for char in chars if CJK_CHAR.match(char)) < len(chars) * 0.6


def _char_runs(col_ink: np.ndarray, expected: int) -> list[list[int]]:
    """列内横向墨迹投影 → 恰好 expected 个字格 [y1,y2)。

    先尝试直接取得彼此分离的字块；粘连字导致段数不一致时，以平均字距为先验，
    在每个理论分界附近寻找墨迹最浅的横向谷底。相比整列等分，这能避开多数笔画。
    """
    if expected <= 0 or col_ink.size == 0:
        return []
    height = col_ink.shape[0]
    fill = np.convolve(col_ink.mean(axis=1), np.ones(3) / 3, mode="same")
    cut = max(0.05, float(np.percentile(fill, 75)) * 0.3)
    runs = _runs(fill > cut, merge_gap=max(3, int(height * 0.008)), min_size=max(10, int(height * 0.03)))
    if len(runs) == expected:
        return runs
    active = np.flatnonzero(fill > max(0.018, float(np.percentile(fill, 70)) * 0.12))
    if not len(active):
        return []
    top, bottom = int(active[0]), int(active[-1]) + 1
    span = bottom - top
    cell = span / expected
    if cell < 6:
        return []
    smoothed = np.convolve(fill, np.ones(7) / 7, mode="same")
    boundaries = [top]
    for index in range(1, expected):
        target = top + index * cell
        radius = max(3, int(cell * 0.34))
        min_cell = max(2, int(cell * 0.35))
        lo = max(boundaries[-1] + min_cell, int(target) - radius)
        hi = min(bottom - min_cell * (expected - index), int(target) + radius + 1)
        if hi <= lo:
            return []
        local = smoothed[lo:hi]
        distance_penalty = np.abs(np.arange(lo, hi) - target) / max(1.0, cell) * max(0.01, float(local.max()) * 0.12)
        boundaries.append(lo + int(np.argmin(local + distance_penalty)))
    boundaries.append(bottom)
    valley_runs = [[boundaries[index], boundaries[index + 1]] for index in range(expected)]
    return valley_runs if all(run[1] - run[0] >= max(4, cell * 0.3) for run in valley_runs) else []


def _dominant_band_extent(ink: np.ndarray, start: int, end: int) -> tuple[int, int] | None:
    """取得横线带在 x 方向最长的连续覆盖范围。"""
    if end <= start:
        return None
    support = ink[start:end].mean(axis=0)
    runs = _runs(support > 0.18, merge_gap=max(6, ink.shape[1] // 180), min_size=max(20, ink.shape[1] // 20))
    if not runs:
        return None
    return tuple(max(runs, key=lambda run: run[1] - run[0]))


def detect_page_frame(ink: np.ndarray) -> list[float] | None:
    """从古籍页的上下横线、左右竖线检测主版框；检测不可靠时返回 None。"""
    height, width = ink.shape
    if height < 80 or width < 80:
        return None
    row_fill = np.convolve(ink.mean(axis=1), np.ones(5) / 5, mode="same")
    row_threshold = max(FRAME_ROW_MIN_FILL, float(np.percentile(row_fill, 99)) * 0.58)
    bands = _runs(row_fill >= row_threshold, merge_gap=max(5, height // 500), min_size=max(3, height // 1200))
    top_bands = [band for band in bands if height * 0.04 <= (band[0] + band[1]) / 2 <= height * 0.48]
    bottom_bands = [band for band in bands if height * 0.52 <= (band[0] + band[1]) / 2 <= height * 0.96]
    pairs = [
        (top, bottom)
        for top in top_bands for bottom in bottom_bands
        if bottom[0] - top[1] >= height * FRAME_MIN_SIZE_RATIO
    ]
    if not pairs:
        return None
    top_band, bottom_band = max(
        pairs,
        key=lambda pair: (
            float(row_fill[pair[0][0]:pair[0][1]].max())
            + float(row_fill[pair[1][0]:pair[1][1]].max())
            + (pair[1][0] - pair[0][1]) / height
        ),
    )
    y1, y2 = top_band[0], bottom_band[1]
    col_fill = ink[top_band[1]:bottom_band[0]].mean(axis=0)
    col_threshold = max(FRAME_COL_MIN_FILL, float(np.percentile(col_fill, 99)) * 0.62)
    verticals = [
        run for run in _runs(col_fill >= col_threshold, merge_gap=max(2, width // 800), min_size=1)
        if run[1] - run[0] <= max(45, int(width * 0.025))
    ]
    top_extent = _dominant_band_extent(ink, top_band[0], top_band[1])
    bottom_extent = _dominant_band_extent(ink, bottom_band[0], bottom_band[1])
    extents = [extent for extent in (top_extent, bottom_extent) if extent]
    horizontal_left = min((extent[0] for extent in extents), default=0)
    horizontal_right = max((extent[1] for extent in extents), default=width)
    if verticals:
        left_run, right_run = verticals[0], verticals[-1]
        x1 = left_run[0]
        x2 = right_run[1] if right_run is not left_run else horizontal_right
        if x1 > width * 0.35:
            x1 = horizontal_left
        if x2 < width * 0.65 or (horizontal_right > width * 0.9 and horizontal_right - x2 > width * 0.08):
            x2 = horizontal_right
    else:
        x1, x2 = horizontal_left, horizontal_right
    x1, x2 = max(0, int(x1)), min(width, int(x2))
    if x2 - x1 < width * FRAME_MIN_SIZE_RATIO or y2 - y1 < height * FRAME_MIN_SIZE_RATIO:
        return None
    return [float(x1), float(y1), float(x2), float(y2)]


def _bbox_inside_frame(bbox: list[float], frame: list[float], min_overlap: float = 0.2) -> bool:
    """块中心或足够面积落在主版框内。"""
    x1, y1, x2, y2 = bbox
    fx1, fy1, fx2, fy2 = frame
    center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
    if fx1 <= center_x <= fx2 and fy1 <= center_y <= fy2:
        return True
    overlap = max(0.0, min(x2, fx2) - max(x1, fx1)) * max(0.0, min(y2, fy2) - max(y1, fy1))
    area = max(1.0, (x2 - x1) * (y2 - y1))
    return overlap / area >= min_overlap


def _dedupe_adjacent_column_texts(columns: list[dict]) -> None:
    """去掉云端 OCR 偶发的跨列串读：前一列末尾完整重复下一列文本。"""
    for index in range(len(columns) - 1):
        current = columns[index]["text"]
        following = columns[index + 1]["text"]
        if len(following) >= 4 and len(current) >= len(following) + 2 and current.endswith(following):
            columns[index]["text"] = current[:-len(following)]


def _trim_nested_column_boxes(columns: list[dict], frame: list[float]) -> bool:
    """裁掉大列框中已由下一独立短列覆盖的下半段（常见于卷名下方印章）。"""
    changed = False
    fx1, fy1, fx2, fy2 = frame
    for item in columns:
        bbox = item["line"]["bbox"]
        bbox[:] = [max(fx1, bbox[0]), max(fy1, bbox[1]), min(fx2, bbox[2]), min(fy2, bbox[3])]
    for current in columns:
        bbox = current["line"]["bbox"]
        height = bbox[3] - bbox[1]
        blockers = []
        for other in columns:
            other_bbox = other["line"]["bbox"]
            other_height = other_bbox[3] - other_bbox[1]
            if other is current or _x_overlap_ratio(bbox, other_bbox) < 0.65:
                continue
            if bbox[1] + max(30.0, height * 0.25) < other_bbox[1] < bbox[3] and height > other_height * 1.8:
                blockers.append(other_bbox[1])
        if blockers:
            new_bottom = min(blockers) - 4
            if new_bottom - bbox[1] >= max(40.0, (bbox[2] - bbox[0]) * 1.5):
                bbox[3] = new_bottom
                changed = True
    return changed


def _local_p75(profile: np.ndarray, window: int = 700, stride: int = 25) -> np.ndarray:
    """滑动窗口 75 分位（只统计有墨的 x），用于墨迹密度差异大的版面局部归一化。"""
    width = len(profile)
    xs = list(range(0, width, stride)) + [width - 1]
    values: list[float] = []
    for x in xs:
        lo, hi = max(0, x - window // 2), min(width, x + window // 2)
        segment = profile[lo:hi][profile[lo:hi] > 0.02]
        values.append(float(np.percentile(segment, 75)) if len(segment) > 30 else 0.0)
    return np.interp(np.arange(width), xs, [max(value, 0.04) for value in values])


def _estimate_pitch(profile: np.ndarray) -> int:
    """自相关估计列距周期（像素）。古籍连续网格常锁到倍频，辅以更小滞后子峰与折半规则。"""
    active = profile > 0.02
    if active.sum() < 100:
        return 0
    centered = np.where(active, profile - profile[active].mean(), 0.0)
    correlation = np.correlate(centered, centered, mode="full")[len(centered) - 1:]
    low, high = 55, min(430, len(correlation) - 1)
    if high <= low:
        return 0
    peak = int(np.argmax(correlation[low:high])) + low
    for lag in range(low + 2, peak - 1):  # 更小滞后中的首个显著峰即基频
        if correlation[lag] >= 0.72 * correlation[peak] and correlation[lag] >= correlation[lag - 1] and correlation[lag] >= correlation[lag + 1]:
            return lag
    if peak >= 320:  # 古籍列距很少超过 320：在半/三分之一处找子峰折半
        for divisor in (2, 3):
            target = peak // divisor
            if target < 60:
                break
            base = max(low, target - 18)
            candidate = base + int(np.argmax(correlation[base:target + 19]))
            if correlation[candidate] >= 0.3 * correlation[peak] and correlation[candidate] >= correlation[candidate - 1] and correlation[candidate] >= correlation[candidate + 1]:
                return candidate
    return peak


def projection_spans(ink: np.ndarray) -> list[list[int]]:
    """竖排墨迹掩码 → 列 span 列表 [x1,y1,x2,y2]（图内坐标，从右向左）。

    墨迹占比曲线经局部 75 分位归一化后取 0.5 阈值得初始列段；
    以自相关列距为周期上限，对过宽列段在其内部最深谷处强制分裂；
    y 方向按列内墨迹收紧；过滤明显窄于 0.3 倍列距的碎段。
    """
    height, width = ink.shape
    if height < 20 or width < 20:
        return []
    profile = np.convolve(ink.mean(axis=0), np.ones(11) / 11, mode="same")
    if not (profile > 0.02).any():
        return []
    normalized = profile / np.maximum(_local_p75(profile), 0.04)
    pitch = _estimate_pitch(profile)
    min_width = max(12, int(pitch * 0.38)) if pitch else max(12, int(width * 0.02))
    min_gap = max(4, int((pitch or 200) * 0.08))
    runs = [list(run) for run in _runs(normalized > 0.5, merge_gap=min_gap, min_size=min_width)]
    max_width = int(pitch * 1.4) if pitch else width
    for _ in range(10):
        changed = False
        rounds: list[list[int]] = []
        for run in runs:
            if run[1] - run[0] > max_width and run[1] - run[0] > 40:
                valley = run[0] + 4 + int(np.argmin(profile[run[0] + 4:run[1] - 4]))
                if profile[valley] < profile[run[0]:run[1]].max() * 0.85:
                    rounds.append([run[0], valley])
                    rounds.append([valley, run[1]])
                    changed = True
                    continue
            rounds.append(run)
        runs = rounds
        if not changed:
            break
    if pitch:
        runs = [run for run in runs if run[1] - run[0] >= pitch * 0.3]
    spans: list[list[int]] = []
    for x1, x2 in runs:
        rows = _runs(ink[:, x1:x2].mean(axis=1) > 0.05, merge_gap=max(4, int(height * 0.008)), min_size=max(12, int(height * 0.02)))
        y1, y2 = (rows[0][0], rows[-1][1]) if rows else (0, height)
        pad = max(1, int((y2 - y1) * 0.03))
        y1, y2 = max(0, y1 - pad), min(height, y2 + pad)
        if (y2 - y1) / max(1, x2 - x1) < SPAN_MIN_ASPECT:
            continue  # 横条/水印花纹不是竖排列
        spans.append([x1, y1, x2, y2])
    if pitch:
        spans = [span for span in spans if span[2] - span[0] >= pitch * 0.38]
    spans.sort(key=lambda span: -span[0])
    return spans

def _crop_image(image_path: str | Path, bbox: list[float], padding: int = CROP_PADDING) -> tuple[Path, tuple[int, int]]:
    """裁剪并落盘临时文件，返回 (临时图路径, 裁剪起点在原图中的坐标)。"""
    with Image.open(image_path) as image:
        x1, y1, x2, y2 = bbox
        left = max(0, int(min(x1, x2)) - padding)
        top = max(0, int(min(y1, y2)) - padding)
        right = min(image.width, int(max(x1, x2)) + padding)
        bottom = min(image.height, int(max(y1, y2)) + padding)
        crop = image.crop((left, top, right, bottom))
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        crop.save(handle.name)
        return Path(handle.name), (left, top)


def _refill_column(image_path: str | Path, config: dict[str, str] | None, caller: Caller, bbox: list[float]) -> tuple[list[float], str] | None:
    """对单个列框再裁剪补识别：返回收紧后的 (bbox, 文本)，失败返回 None。"""
    crop_path, origin = _crop_image(image_path, bbox, padding=2)
    try:
        blocks = [block for block in parse_blocks(caller(crop_path, config)) if block["content"].strip()]
    finally:
        crop_path.unlink(missing_ok=True)
    if not blocks:
        return None
    best = max(blocks, key=lambda block: (block["bbox"][2] - block["bbox"][0]) * (block["bbox"][3] - block["bbox"][1]))
    text = "".join(line for line in best["content"].split("\n") if line.strip())
    if not text:
        return None
    absolute = [
        max(bbox[0], min(bbox[2], best["bbox"][0] + origin[0])),
        max(bbox[1], min(bbox[3], best["bbox"][1] + origin[1])),
        max(bbox[0], min(bbox[2], best["bbox"][2] + origin[0])),
        max(bbox[1], min(bbox[3], best["bbox"][3] + origin[1])),
    ]
    if absolute[2] - absolute[0] < 4 or absolute[3] - absolute[1] < 4:
        return (list(bbox), text)
    return (absolute, text)


Progress = Callable[[str, int], None]


def preprocess_page(image_path: str | Path, config: dict[str, str] | None = None, caller: Caller = call_paddleocr_vl_api, progress: Progress | None = None) -> dict:
    """主版框检测 → 版框内墨迹投影切列 → 每列字格切分与文字对应。

    progress(阶段说明, 百分比) 在三阶段起点与逐列推进时回调，供任务进度展示。
    """
    def report(stage: str, percent: int) -> None:
        if progress:
            try:
                progress(stage, percent)
            except Exception:
                pass

    report("① 主版框与版面识别", 10)
    raw_blocks = parse_blocks(caller(image_path, config))
    report(f"版面识别完成：云端返回 {len(raw_blocks)} 个内容块", 30)
    regions: list[dict] = []
    lines: list[dict] = []
    chars: list[dict] = []
    warnings: list[str] = []
    refill_budget = COLUMN_REFILL_LIMIT
    with Image.open(image_path) as opened:
        page_gray = np.array(opened.convert("L"))
    raw_page_ink = _ink_mask(page_gray)
    frame = detect_page_frame(raw_page_ink)
    page_ink = raw_page_ink
    page_ink, _ = _erase_rule_lines(page_ink)
    report("② 主版框内墨迹投影切列（剔除界栏/版框）", 40)
    page_spans = projection_spans(page_ink)
    if frame:
        page_spans = [span for span in page_spans if _bbox_inside_frame([float(value) for value in span], frame, min_overlap=0.5)]
    # 投影列 → 文本区域的排他归属：x 中心落在区域横向范围内，纵向重叠率（交并比）最高的区域独占该列
    text_regions = [
        (index, block) for index, block in enumerate(raw_blocks, 1)
        if region_type_of(block["label"]) in TEXT_REGION_TYPES
        and (not frame or _bbox_inside_frame(block["bbox"], frame))
    ]
    spans_by_region: dict[int, list[list[float]]] = {}
    for span in page_spans:
        center_x = (span[0] + span[2]) / 2
        best_region, best_iou = 0, 0.2
        for index, block in text_regions:
            bx1, by1, bx2, by2 = block["bbox"]
            if not (bx1 - 12 <= center_x <= bx2 + 12):
                continue
            if (by2 - by1) < (bx2 - bx1) * 0.8:
                continue  # 横排区域（题签等）不按列投影切
            overlap = min(span[3], by2) - max(span[1], by1)
            union = max(span[3], by2) - min(span[1], by1)
            iou = overlap / union if union > 0 else 0.0
            if iou > best_iou:
                best_region, best_iou = index, iou
        if best_region:
            spans_by_region.setdefault(best_region, []).append([float(value) for value in span])
    report(f"投影切列完成：主版框内 {len(page_spans)} 个候选列", 52)
    page_height_px, page_width_px = page_gray.shape
    columns_done = 0
    for index, block in enumerate(raw_blocks, 1):
        region_type = region_type_of(block["label"])
        if frame and not _bbox_inside_frame(block["bbox"], frame):
            continue
        if not frame:
            regions.append({"region_type": region_type, "order_no": index, "bbox": block["bbox"], "confirmed": False})
        if region_type not in TEXT_REGION_TYPES:
            continue
        parent_region_no = 1 if frame else index
        bx1, by1, bx2, by2 = block["bbox"]
        # 区域级投影：在区域裁剪内做第二遍切列，短列/上下叠放列不会被整页邻居的归一化淹没
        candidates = [list(span) for span in spans_by_region.get(index, [])]
        if (by2 - by1) >= (bx2 - bx1) * 0.8:
            pad = 12
            rx1, ry1 = max(0, int(bx1) - pad), max(0, int(by1) - pad)
            rx2, ry2 = min(page_width_px, int(bx2) + pad), min(page_height_px, int(by2) + pad)
            if rx2 - rx1 > 40 and ry2 - ry1 > 40:
                region_ink = _ink_mask(page_gray[ry1:ry2, rx1:rx2])
                region_ink, _ = _erase_rule_lines(region_ink)
                for span in projection_spans(region_ink):
                    absolute = [float(span[0] + rx1), float(span[1] + ry1), float(span[2] + rx1), float(span[3] + ry1)]
                    if all(_x_overlap_ratio(absolute, kept) < 0.4 for kept in candidates):
                        candidates.append(absolute)
            candidates.sort(key=lambda span: -span[0])
        # 区域裁剪再识别，取文本行（阅读序）
        try:
            crop_path, origin = _crop_image(image_path, block["bbox"])
            try:
                crop_blocks = parse_blocks(caller(crop_path, config))
            finally:
                crop_path.unlink(missing_ok=True)
        except Exception:
            crop_blocks = []
        texts = [line for crop_block in crop_blocks for line in crop_block["content"].split("\n") if line.strip()]
        if not texts:
            texts = [line for line in block["content"].split("\n") if line.strip()]
        if candidates:
            # 区域框按列墨迹并集校正
            if not frame:
                regions[-1]["bbox"] = [
                    min(span[0] for span in candidates) - 4, min(span[1] for span in candidates) - 4,
                    max(span[2] for span in candidates) + 4, max(span[3] for span in candidates) + 4,
                ]
            columns = [{"bbox": span, "content": text, "uncertain": len(texts) != len(candidates)}
                       for span, text in zip(candidates, chunk_texts(texts, len(candidates)))]
        else:
            # 投影失败（空白/横排/异形版面）→ 几何回退
            fallback_blocks = crop_blocks or [{"label": "text", "bbox": [0, 0, bx2 - bx1, by2 - by1], "content": block["content"]}]
            offset = origin if crop_blocks else (bx1, by1)
            columns = []
            for entry in derive_columns(fallback_blocks):
                columns.append({"bbox": [entry["bbox"][0] + offset[0], entry["bbox"][1] + offset[1], entry["bbox"][2] + offset[0], entry["bbox"][3] + offset[1]], "content": entry["content"], "uncertain": entry["uncertain"]})
        for column in columns:
            line_bbox = [float(value) for value in column["bbox"]]
            text = column["content"]
            if column["uncertain"] and refill_budget > 0 and line_bbox[3] - line_bbox[1] > line_bbox[2] - line_bbox[0]:
                refill_budget -= 1
                try:
                    refilled = _refill_column(image_path, config, caller, line_bbox)
                except Exception:
                    refilled = None
                if refilled:
                    refilled_bbox, refilled_text = refilled
                    # 孤列小图常被读漏：补识别字数不足几何容量 30% 时弃用其文本，保留区域级分摊文本
                    capacity = int((line_bbox[3] - line_bbox[1]) / max(8.0, 0.45 * max(1.0, line_bbox[2] - line_bbox[0])))
                    if len([char for char in refilled_text if char.strip()]) >= max(2, capacity * 0.3):
                        line_bbox, text = list(refilled_bbox), refilled_text
            if not text.strip():
                continue
            char_list = [char for char in text if char.strip()]
            width_px, height_px = line_bbox[2] - line_bbox[0], line_bbox[3] - line_bbox[1]
            if _is_watermark(text):
                warnings.append(f"区域{index}一列文本为重复水印（{text[:10]}…），已丢弃")
                continue
            capacity = int(height_px / max(8.0, 0.45 * width_px)) if width_px > 0 else 0
            if capacity > 0 and len(char_list) > capacity * 2.5:
                warnings.append(f"区域{index}一列文本 {len(char_list)} 字远超几何容量 {capacity} 字（疑似串列/水印），已丢弃")
                continue
            if _is_margin_junk(line_bbox, text, float(page_width_px)):
                warnings.append(f"区域{index}一列贴边短文本「{text[:6]}」疑为版框外杂迹，已丢弃")
                continue
            line_order = len(lines) + 1
            plausible = char_cells_plausible(line_bbox, len(char_list))
            lines.append({
                "region_order_no": parent_region_no, "order_no": line_order, "bbox": line_bbox,
                "char_size": 0, "confirmed": False, "needs_char_split": not plausible, "ocr_text": text,
            })
            if not plausible:
                warnings.append(f"区域{index}第{line_order}列字格切分可疑（列宽{line_bbox[2] - line_bbox[0]:.0f}×高{line_bbox[3] - line_bbox[1]:.0f}，{len(char_list)}字）")
            # 字格：优先用列内横向墨迹投影的真实字间隙，无间隙时按字数均分
            x1, y1, x2, y2 = (max(0, int(line_bbox[0])), max(0, int(line_bbox[1])), min(page_ink.shape[1], int(line_bbox[2])), min(page_ink.shape[0], int(line_bbox[3])))
            char_boxes: list[tuple[list[float], str]] = []
            col_ink = page_ink[y1:y2, x1:x2]
            runs = _char_runs(col_ink, len(char_list)) if x2 - x1 > 8 and y2 - y1 > 8 else []
            if runs:
                for run, char in zip(runs, char_list):
                    char_boxes.append(([line_bbox[0], line_bbox[1] + run[0], line_bbox[2], line_bbox[1] + run[1]], char))
            else:
                char_boxes = split_line_into_chars(line_bbox, text)
            for char_bbox, char in char_boxes:
                chars.append({
                    "line_order_no": line_order, "order_no": len(chars) + 1, "bbox": char_bbox,
                    "raw_text": char, "corrected_text": char, "candidates": [char, "□"],
                    "confidence": 0.8, "status": "unchecked",
                })
            columns_done += 1
            report(f"③ 列 {line_order}：{len(char_list)} 字「{text[:10]}{'…' if len(text) > 10 else ''}」", min(95, 55 + columns_done * 3))
        if not candidates and not columns:
            warnings.append(f"区域{index}未能切出任何列")
    if frame:
        regions = [{"region_type": "text", "order_no": 1, "bbox": frame, "confirmed": False}]
        # 云端偶尔把相邻列串成一行；排序后才能安全判断“前列末尾=后一列全文”。
        combined = [{"line": line, "text": line["ocr_text"]} for line in lines]
        combined.sort(key=lambda item: (-((item["line"]["bbox"][0] + item["line"]["bbox"][2]) / 2), item["line"]["bbox"][1]))
        if _trim_nested_column_boxes(combined, frame):
            warnings.append("检测到同栏上下重叠内容，已按独立短列修正纵向边界")
        before_dedupe = [item["text"] for item in combined]
        _dedupe_adjacent_column_texts(combined)
        if any(before != item["text"] for before, item in zip(before_dedupe, combined)):
            warnings.append("检测到跨列串读，已移除相邻列中的重复文字")
        for order, item in enumerate(combined, 1):
            item["line"]["order_no"] = order
            item["line"]["ocr_text"] = item["text"]
        lines = [item["line"] for item in combined if item["text"]]
        # 原字框仍指向去重前的顺序/文本，统一按排序后的列重新生成。
        chars = []
        for line in lines:
            text = line["ocr_text"]
            char_list = [char for char in text if char.strip()]
            line["needs_char_split"] = not char_cells_plausible(line["bbox"], len(char_list))
            x1, y1, x2, y2 = (
                max(0, int(line["bbox"][0])), max(0, int(line["bbox"][1])),
                min(page_ink.shape[1], int(line["bbox"][2])), min(page_ink.shape[0], int(line["bbox"][3])),
            )
            runs = _char_runs(page_ink[y1:y2, x1:x2], len(char_list)) if x2 - x1 > 8 and y2 - y1 > 8 else []
            char_boxes = [
                ([line["bbox"][0], line["bbox"][1] + run[0], line["bbox"][2], line["bbox"][1] + run[1]], char)
                for run, char in zip(runs, char_list)
            ] if runs else split_line_into_chars(line["bbox"], text)
            for char_bbox, char in char_boxes:
                chars.append({
                    "line_order_no": line["order_no"], "order_no": len(chars) + 1, "bbox": char_bbox,
                    "raw_text": char, "corrected_text": char, "candidates": [char, "□"],
                    "confidence": 0.8, "status": "unchecked",
                })
    if not regions:
        warnings.append("整页版面识别未返回任何区域")
    report(f"完成：{len(regions)} 区域 · {len(lines)} 列 · {len(chars)} 字", 98)
    return {"regions": regions, "lines": lines, "chars": chars, "warnings": warnings}
