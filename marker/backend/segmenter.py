from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

RULE_VERSION = "frame-template-v2"
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "data" / "segment_template.json"


@dataclass(frozen=True)
class Frame:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def _merge_centers(values: list[int], distance: int) -> list[int]:
    if not values:
        return []
    values = sorted(values)
    groups: list[list[int]] = [[values[0]]]
    for value in values[1:]:
        if value - groups[-1][-1] <= distance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [round(sum(group) / len(group)) for group in groups]


def _load_binary(image_path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    image_data = np.fromfile(str(image_path), dtype=np.uint8)
    gray = cv2.imdecode(image_data, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"image not readable: {image_path}")
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return gray, binary


def _content_bbox(binary: np.ndarray) -> Frame:
    ys, xs = np.where(binary > 0)
    if len(xs) == 0 or len(ys) == 0:
        height, width = binary.shape
        return Frame(0, 0, width - 1, height - 1)
    return Frame(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def _line_components(binary: np.ndarray, orientation: str) -> list[tuple[int, int, int, int]]:
    height, width = binary.shape
    if orientation == "horizontal":
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(160, width // 4), 1))
    else:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(260, height // 5)))
    lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
    contours, _ = cv2.findContours(lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [cv2.boundingRect(contour) for contour in contours]


def _detect_frame(binary: np.ndarray) -> Frame:
    height, width = binary.shape
    content = _content_bbox(binary)
    horizontal = [
        (x, y, w, h)
        for x, y, w, h in _line_components(binary, "horizontal")
        if w >= width * 0.24 and h <= max(40, height * 0.025)
    ]
    vertical = [
        (x, y, w, h)
        for x, y, w, h in _line_components(binary, "vertical")
        if h >= height * 0.18 and w <= max(35, width * 0.02)
    ]

    if horizontal:
        top_line = min(horizontal, key=lambda item: item[1])
        bottom_line = max(horizontal, key=lambda item: item[1] + item[3])
        top = top_line[1]
        bottom = bottom_line[1] + bottom_line[3]
        h_left = min(x for x, _, _, _ in horizontal)
        h_right = max(x + w for x, _, w, _ in horizontal)
    else:
        top = content.top
        bottom = content.bottom
        h_left = content.left
        h_right = content.right

    useful_vertical = [
        (x, y, w, h)
        for x, y, w, h in vertical
        if y < bottom and y + h > top and h >= max(300, (bottom - top) * 0.22)
    ]
    if useful_vertical:
        v_left = min(x for x, _, _, _ in useful_vertical)
        v_right = max(x + w for x, _, w, _ in useful_vertical)
        left = min(h_left, v_left)
        right = max(h_right, v_right)
    else:
        left = h_left
        right = h_right

    pad_x = max(8, round(width * 0.006))
    pad_y = max(8, round(height * 0.004))
    left = max(0, left - pad_x)
    right = min(width - 1, right + pad_x)
    top = max(0, top - pad_y)
    bottom = min(height - 1, bottom + pad_y)

    if right - left < width * 0.25 or bottom - top < height * 0.35:
        return content
    return Frame(left, top, right, bottom)


def _detect_column_lines(binary: np.ndarray, frame: Frame) -> list[int]:
    frame_binary = binary[frame.top : frame.bottom + 1, frame.left : frame.right + 1]
    frame_height, frame_width = frame_binary.shape
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(220, round(frame_height * 0.18))))
    vertical = cv2.morphologyEx(frame_binary, cv2.MORPH_OPEN, kernel, iterations=1)
    contours, _ = cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    centers: list[int] = [frame.left, frame.right]
    min_height = max(240, round(frame_height * 0.18))
    max_width = max(28, round(frame_width * 0.025))
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h >= min_height and w <= max_width:
            centers.append(frame.left + round(x + w / 2))
    return _merge_centers(centers, max(8, round(frame_width * 0.008)))


def _regular_step(lines: list[int]) -> int | None:
    gaps = [right - left for left, right in zip(lines, lines[1:]) if 90 <= right - left <= 320]
    if len(gaps) < 2:
        return None
    median = int(np.median(gaps))
    close = [gap for gap in gaps if abs(gap - median) <= median * 0.35]
    if len(close) < 2:
        return None
    return int(np.median(close))


def _template_lines(frame: Frame) -> list[int] | None:
    if not TEMPLATE_PATH.exists():
        return None
    try:
        data = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
        relative = data.get("relative_lines")
        if not isinstance(relative, list) or len(relative) < 3:
            return None
        return [frame.left + round(float(value) * frame.width) for value in relative]
    except Exception:
        return None


def _save_template(frame: Frame, lines: list[int]) -> None:
    # Title pages or partial frames are too narrow to serve as a book-wide template.
    if len(lines) < 8 or frame.width <= 1300:
        return
    step = _regular_step(lines)
    if not step:
        return
    relative = [(line - frame.left) / frame.width for line in lines]
    TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATE_PATH.write_text(
        json.dumps(
            {"rule_version": RULE_VERSION, "relative_lines": relative, "line_count": len(lines), "median_step": step},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _complete_grid(frame: Frame, lines: list[int]) -> list[int]:
    lines = sorted(set(line for line in lines if frame.left - 5 <= line <= frame.right + 5))
    lines = [frame.left if abs(line - frame.left) <= 12 else frame.right if abs(line - frame.right) <= 12 else line for line in lines]
    lines = _merge_centers(sorted(set(lines)), max(8, round(frame.width * 0.006)))
    step = _regular_step(lines)

    template = _template_lines(frame)
    if template and (not step or len(lines) < 5):
        lines = sorted(set([frame.left, *template, frame.right]))
        step = _regular_step(lines)

    if not step:
        # The book columns are stable and usually around 160-220px wide at 300dpi.
        count = max(4, min(14, round(frame.width / 190)))
        step = max(120, round(frame.width / count))
        lines = [frame.left + round(index * frame.width / count) for index in range(count + 1)]
        return sorted(set([frame.left, *lines, frame.right]))

    completed = set(lines)
    for left, right in zip(lines, lines[1:]):
        gap = right - left
        if gap <= step * 1.45:
            continue
        missing = max(1, round(gap / step))
        for index in range(1, missing):
            value = round(left + gap * index / missing)
            if frame.left < value < frame.right:
                completed.add(value)

    start = min(lines)
    while start - step > frame.left + step * 0.35:
        start -= step
        completed.add(start)
    end = max(lines)
    while end + step < frame.right - step * 0.35:
        end += step
        completed.add(end)

    completed.add(frame.left)
    completed.add(frame.right)
    return sorted(completed)


def _segments_from_grid(binary: np.ndarray, frame: Frame, lines: list[int]) -> list[tuple[int, int, int, int]]:
    step = _regular_step(lines)
    expected = step or max(120, round(frame.width / max(4, round(frame.width / 190))))
    min_width = max(120, round(expected * 0.58))
    max_width = round(expected * 1.65)
    pad = max(3, round(expected * 0.02))

    segments: list[tuple[int, int, int, int]] = []
    for left, right in zip(lines, lines[1:]):
        width = right - left
        if width < min_width or width > max_width:
            continue
        x1 = max(0, left + pad)
        x2 = min(binary.shape[1] - 1, right - pad)
        if x2 - x1 < min_width:
            continue
        roi = binary[frame.top : frame.bottom, x1:x2]
        ink = int(cv2.countNonZero(roi))
        # Keep bottom whitespace, but require enough ink somewhere in the column.
        if ink < max(140, (x2 - x1) * frame.height * 0.0012):
            continue
        segments.append((x1, frame.top, x2, frame.bottom))

    # Drop isolated outer slivers if they are much narrower than the remaining columns.
    if len(segments) >= 3:
        widths = [x2 - x1 for x1, _, x2, _ in segments]
        median = float(np.median(widths))
        segments = [item for item in segments if item[2] - item[0] >= median * 0.72]
    return segments


def cut_vertical_segments(image_path: str | Path) -> list[dict]:
    _, binary = _load_binary(image_path)
    frame = _detect_frame(binary)
    lines = _complete_grid(frame, _detect_column_lines(binary, frame))
    segments = _segments_from_grid(binary, frame, lines)

    if not segments:
        # Last resort: full frame, never a text-only sliver.
        segments = [(frame.left, frame.top, frame.right, frame.bottom)]
    else:
        _save_template(frame, lines)

    segments.sort(key=lambda item: item[0], reverse=True)
    return [
        {"segment_no": index + 1, "bbox": [float(x1), float(y1), float(x2), float(y2)], "rule_version": RULE_VERSION}
        for index, (x1, y1, x2, y2) in enumerate(segments)
    ]
