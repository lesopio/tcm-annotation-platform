"""全站测试模式（.env 真实测试凭据切换）与预处理管线。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from marker.backend.database import Base
from marker.backend.models import OcrProviderSetting, User
from marker.backend.ocr_config import effective_ocr_config, save_ocr_config
from marker.backend.preprocess import (
    char_cells_plausible, clean_content, derive_columns, detect_page_frame, parse_blocks, preprocess_page,
    split_bbox_into_columns, split_block_into_lines, split_line_into_chars,
)
from marker.backend.platform_config import is_test_mode, public_platform_setting, set_test_mode
from marker.backend.settings import settings


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def test_platform_test_mode_roundtrip():
    db, engine = _db()
    try:
        assert is_test_mode(db) is False
        result = set_test_mode(db, True, updated_by=1)
        assert result["test_mode"] is True
        assert isinstance(result["test_env_ready"], bool)
        assert is_test_mode(db) is True
        set_test_mode(db, False, updated_by=1)
        assert public_platform_setting(db)["test_mode"] is False
    finally:
        db.close()
        engine.dispose()


def test_effective_ocr_config_prefers_env_test_credentials():
    db, engine = _db()
    old = (settings.test_ocr_token, settings.test_ocr_base_url, settings.test_ocr_model)
    try:
        db.add(User(username="admin", password_hash="x", role="admin", is_active=True))
        db.flush()
        save_ocr_config(db, access_token="prod-token", clear_access_token=False, base_url="https://prod.example/jobs", model="PaddleOCR-VL-1.6", updated_by=1)
        assert effective_ocr_config(db)["access_token"] == "prod-token"
        set_test_mode(db, True, updated_by=1)
        object.__setattr__(settings, "test_ocr_token", "test-token")
        object.__setattr__(settings, "test_ocr_base_url", "https://test.example/jobs")
        object.__setattr__(settings, "test_ocr_model", "PaddleOCR-VL-TEST")
        config = effective_ocr_config(db)
        assert config == {"provider": "paddleocr", "access_token": "test-token", "base_url": "https://test.example/jobs", "model": "PaddleOCR-VL-TEST"}
        set_test_mode(db, False, updated_by=1)
        assert effective_ocr_config(db)["access_token"] == "prod-token"
    finally:
        object.__setattr__(settings, "test_ocr_token", old[0])
        object.__setattr__(settings, "test_ocr_base_url", old[1])
        object.__setattr__(settings, "test_ocr_model", old[2])
        db.close()
        engine.dispose()


def test_clean_content_strips_table_markup():
    assert clean_content("<table><tr><td>牛膝</td><td>平</td></tr></table>") == "牛膝平"
    assert clean_content("| 牛膝 | 平 |\n| --- | --- |") == "牛膝平"
    assert clean_content("神农本草经") == "神农本草经"


def test_parse_blocks_real_paddleocr_shape():
    raw = {"layoutParsingResults": [{"prunedResult": {"parsing_res_list": [
        {"block_label": "text", "block_content": "神农本草经\n名医别录", "block_bbox": [77, 78, 369, 219]},
        {"block_label": "seal", "block_content": "", "block_bbox": [10, 10, 60, 60]},
    ]}}]}
    blocks = parse_blocks(raw)
    assert len(blocks) == 2
    assert blocks[0]["content"] == "神农本草经\n名医别录"
    assert blocks[1]["bbox"] == [10.0, 10.0, 60.0, 60.0]


def test_split_block_into_lines_vertical_reads_right_to_left():
    segments = split_block_into_lines([100, 0, 200, 400], "右列\n左列")
    assert len(segments) == 2
    # 竖排：第一列在最右
    assert segments[0][1] == "右列"
    assert segments[0][0][0] == 150 and segments[0][0][2] == 200
    assert segments[1][0][0] == 100 and segments[1][0][2] == 150


def test_split_block_into_lines_horizontal_stacks():
    segments = split_block_into_lines([0, 0, 400, 100], "上行\n下行")
    assert segments[0][0][1] == 0 and segments[0][0][3] == 50
    assert segments[1][0][1] == 50 and segments[1][0][3] == 100


def test_split_line_into_chars_vertical_and_horizontal():
    vertical = split_line_into_chars([0, 0, 40, 120], "本草經")
    assert [char for _, char in vertical] == ["本", "草", "經"]
    assert vertical[0][0][3] == 40 and vertical[1][0][1] == 40  # 每字 40 高
    horizontal = split_line_into_chars([0, 0, 120, 40], "本草經")
    assert horizontal[0][0][2] == 40 and horizontal[2][0][0] == 80


def test_preprocess_page_pipeline_with_fake_caller(tmp_path: Path):
    image_path = tmp_path / "page.png"
    Image.new("RGB", (800, 1200), "white").save(image_path)

    def fake_caller(path, config=None):
        if str(path).endswith("page.png"):
            # 整页版面：一个文本区域 + 一个印章
            return {"layoutParsingResults": [{"prunedResult": {"parsing_res_list": [
                {"block_label": "text", "block_content": "", "block_bbox": [100, 100, 400, 1000]},
                {"block_label": "seal", "block_content": "", "block_bbox": [600, 900, 700, 1000]},
            ]}}]}
        # 区域裁剪再识别：返回两列竖排文字（相对裁剪图坐标）
        return {"layoutParsingResults": [{"prunedResult": {"parsing_res_list": [
            {"block_label": "text", "block_content": "神农本\n名医别", "block_bbox": [6, 6, 306, 1006]},
        ]}}]}

    result = preprocess_page(image_path, config={"provider": "paddleocr"}, caller=fake_caller)
    assert [region["region_type"] for region in result["regions"]] == ["text", "seal"]
    assert len(result["lines"]) == 2
    first, second = result["lines"]
    assert first["ocr_text"] == "神农本"
    assert first["region_order_no"] == 1
    # 裁剪带 6px 边距：列框相对页坐标右端约在 400+6 附近
    assert 380 <= first["bbox"][2] <= 420
    assert len(result["chars"]) == 6
    assert [char["raw_text"] for char in result["chars"][:3]] == ["神", "农", "本"]
    assert result["chars"][0]["line_order_no"] == 1 and result["chars"][3]["line_order_no"] == 2


def test_split_bbox_into_columns_text_assignment():
    # 行数与列数一致：逐列对应，首列在最右
    segments = split_bbox_into_columns([0, 0, 300, 100], 3, ["右", "中", "左"])
    assert [text for _, text in segments] == ["右", "中", "左"]
    assert segments[0][0][0] == 200 and segments[2][0][2] == 100
    # 行多于列：依序分组成列
    grouped = split_bbox_into_columns([0, 0, 200, 100], 2, ["甲", "乙", "丙", "丁", "戊"])
    assert [text for _, text in grouped] == ["甲乙丙", "丁戊"]
    assert grouped[0][0][0] == 100  # 首列仍在最右
    # 行少于列：合并全文均分（5 字切 4 列 → 2/2/1/0）
    chunked = split_bbox_into_columns([0, 0, 200, 100], 4, ["一二", "三四", "五"])
    assert [text for _, text in chunked] == ["一二", "三四", "五", ""]


def test_derive_columns_flags_uncertain_split():
    blocks = [
        {"label": "text", "bbox": [6, 6, 206, 1006], "content": "一\n二\n三\n四\n五\n六"},  # 宽块：几何判定 2 列
        {"label": "text", "bbox": [206, 6, 306, 1006], "content": "七"},  # 窄块：单列
    ]
    columns = derive_columns(blocks)
    assert len(columns) == 3
    assert columns[0]["content"] == "一二三" and columns[0]["uncertain"] is True
    assert columns[1]["content"] == "四五六" and columns[1]["uncertain"] is True
    assert columns[2]["content"] == "七" and columns[2]["uncertain"] is False
    # 首列在最右（块内 x 106..206）
    assert columns[0]["bbox"][0] == 106 and columns[0]["bbox"][2] == 206


def test_derive_columns_splits_single_line_wide_block():
    # 模型把多列并成一行（2201×3067 单行 131 字）：按面积估计列数（cell≈227 → 10 列），全部 uncertain
    blocks = [{"label": "text", "bbox": [0, 0, 2201, 3067], "content": "秦光平濁温" * 26 + "臣"}]
    columns = derive_columns(blocks)
    assert len(columns) == 10
    assert all(column["uncertain"] is True for column in columns)
    assert "".join(column["content"] for column in columns).endswith("臣")
    # 竖排单列（宽≈字高/字数）不触发切分
    single = derive_columns([{"label": "text", "bbox": [0, 0, 40, 400], "content": "本草經目"}])
    assert len(single) == 1 and single[0]["uncertain"] is False


def test_char_cells_plausible_bounds():
    assert char_cells_plausible([0, 0, 40, 120], 3) is True  # 40×40 方格
    assert char_cells_plausible([0, 0, 40, 400], 3) is False  # 字格过高（比例 3.3）
    assert char_cells_plausible([0, 0, 40, 60], 5) is False  # 字格过小（12px 高，比例 0.3）
    assert char_cells_plausible([0, 0, 120, 40], 3) is True  # 横排 40×40


def test_preprocess_page_refills_uncertain_columns(tmp_path: Path):
    image_path = tmp_path / "page.png"
    Image.new("RGB", (800, 1200), "white").save(image_path)
    calls = {"region": 0, "column": 0}

    def fake_caller(path, config=None):
        if str(path).endswith("page.png"):
            # 整页：一个文本区域 + 一个印章
            return {"layoutParsingResults": [{"prunedResult": {"parsing_res_list": [
                {"block_label": "text", "block_content": "", "block_bbox": [100, 100, 400, 1000]},
                {"block_label": "seal", "block_content": "", "block_bbox": [600, 900, 700, 1000]},
            ]}}]}
        with Image.open(path) as image:
            if image.width > 200:  # 区域裁剪（312px 宽）：一个 6 行宽块 + 一个窄单列块
                calls["region"] += 1
                return {"layoutParsingResults": [{"prunedResult": {"parsing_res_list": [
                    {"block_label": "text", "block_content": "一\n二\n三\n四\n五\n六", "block_bbox": [6, 6, 206, 1006]},
                    {"block_label": "text", "block_content": "七", "block_bbox": [206, 6, 306, 1006]},
                ]}}]}
        # 列补识别：返回该列的净文本（8 字 ≥ 几何容量阈值 ≈6.6 字，会被采用）
        calls["column"] += 1
        return {"layoutParsingResults": [{"prunedResult": {"parsing_res_list": [
            {"block_label": "text", "block_content": "甲乙丙丁戊己壬癸", "block_bbox": [2, 2, 102, 1002]},
        ]}}]}

    result = preprocess_page(image_path, config={"provider": "paddleocr"}, caller=fake_caller)
    assert calls["region"] == 1 and calls["column"] == 2  # 仅两个"不确定"列触发补识别
    assert [line["ocr_text"] for line in result["lines"]] == ["甲乙丙丁戊己壬癸", "甲乙丙丁戊己壬癸", "七"]
    assert len(result["chars"]) == 17  # 每列 8 个补识别字 + "七"
    assert result["chars"][0]["line_order_no"] == 1 and result["chars"][8]["line_order_no"] == 2 and result["chars"][16]["line_order_no"] == 3
    # 100×1000 的列切 8 字字格比例正常；单字"七"列失衡 → 标记 needs_char_split 并告警
    assert [line["needs_char_split"] for line in result["lines"]] == [False, False, True]
    assert result["warnings"]


def _draw_page(path: Path, columns: list[tuple[int, int, int, int]], rule_lines: list[tuple[int, int]] = ()) -> None:
    """合成古籍页：白底 + 指定 [x1,y1,x2,y2] 黑色竖列（列内为离散字块：80 高字 + 30 间隔）。"""
    image = Image.new("L", (800, 1200), 235)
    for x1, y1, x2, y2 in columns:
        block, gap, y = 80, 30, y1
        while y + block <= y2:
            for dy in range(block):
                for dx in range(x2 - x1):
                    image.putpixel((x1 + dx, y + dy), 40)
            y += block + gap
    for x1, x2 in rule_lines:  # 贯穿整列的界栏细线
        for y in range(60, 1140):
            for x in range(x1, x2):
                image.putpixel((x, y), 30)
    image.save(path)


def test_detect_page_frame_and_collapse_cloud_blocks(tmp_path: Path):
    image_path = tmp_path / "ruled.png"
    image = Image.new("L", (800, 1200), 235)
    # 主版框；横线和竖线均足够长，底部另有框外水印块。
    for y in range(100, 108):
        for x in range(80, 721):
            image.putpixel((x, y), 25)
    for y in range(1090, 1098):
        for x in range(80, 721):
            image.putpixel((x, y), 25)
    for x in list(range(80, 87)) + list(range(714, 721)):
        for y in range(100, 1098):
            image.putpixel((x, y), 25)
    for y in range(1120, 1180):
        for x in range(500, 700):
            image.putpixel((x, y), 30)
    image.save(image_path)
    ink = np.array(image) < 170
    frame = detect_page_frame(ink)
    assert frame is not None
    assert 75 <= frame[0] <= 90 and 710 <= frame[2] <= 725
    assert 95 <= frame[1] <= 105 and 1093 <= frame[3] <= 1103

    def fake_caller(path, config=None):
        if str(path).endswith("ruled.png"):
            return {"layoutParsingResults": [{"prunedResult": {"parsing_res_list": [
                {"block_label": "text", "block_content": "本草經", "block_bbox": [500, 180, 570, 700]},
                {"block_label": "text", "block_content": "名醫錄", "block_bbox": [300, 180, 370, 700]},
                {"block_label": "seal", "block_content": "", "block_bbox": [120, 800, 220, 900]},
                {"block_label": "text", "block_content": "館藏水印", "block_bbox": [500, 1120, 700, 1180]},
            ]}}]}
        return {"layoutParsingResults": [{"prunedResult": {"parsing_res_list": []}}]}

    result = preprocess_page(image_path, config={"provider": "paddleocr"}, caller=fake_caller)
    assert len(result["regions"]) == 1
    assert result["regions"][0]["bbox"] == frame
    assert all(line["region_order_no"] == 1 for line in result["lines"])
    assert not any("館藏水印" in line["ocr_text"] for line in result["lines"])


def test_projection_columns_align_with_ink(tmp_path: Path):
    """列框应贴真实墨迹：三列（列距 200、列宽 60、每列 4 字块），界栏线不产生第四列。"""
    image_path = tmp_path / "page.png"
    _draw_page(image_path, columns=[(160, 200, 240, 610), (360, 200, 440, 610), (560, 200, 640, 610)], rule_lines=[(497, 502)])

    def fake_caller(path, config=None):
        if str(path).endswith("page.png"):
            return {"layoutParsingResults": [{"prunedResult": {"parsing_res_list": [
                {"block_label": "text", "block_content": "", "block_bbox": [120, 100, 700, 1100]},
            ]}}]}
        return {"layoutParsingResults": [{"prunedResult": {"parsing_res_list": [
            {"block_label": "text", "block_content": "右列文本\n中列文字\n左列内容", "block_bbox": [0, 0, 600, 900]},
        ]}}]}

    result = preprocess_page(image_path, config={"provider": "paddleocr"}, caller=fake_caller)
    assert len(result["lines"]) == 3, result["lines"]
    first, second, third = result["lines"]
    assert (first["ocr_text"], second["ocr_text"], third["ocr_text"]) == ("右列文本", "中列文字", "左列内容")
    # 列框贴墨迹：右列 x≈560-640（±10 容差）；界栏线 x≈500 处没有第四列
    assert 550 <= first["bbox"][0] and first["bbox"][2] <= 650
    assert 350 <= second["bbox"][0] and second["bbox"][2] <= 450
    assert 150 <= third["bbox"][0] and third["bbox"][2] <= 250
    # 区域框按列墨迹并集校正（≈156-644）
    region = result["regions"][0]
    assert 145 <= region["bbox"][0] <= 175 and 630 <= region["bbox"][2] <= 660
    # 字格用真实字间隙：4 个 80 高字块 → 字框高度 ≈80（均分则为 ~108）
    char_boxes = [char for char in result["chars"] if char["line_order_no"] == 1]
    assert [char["raw_text"] for char in char_boxes] == ["右", "列", "文", "本"]
    assert all(60 <= char["bbox"][3] - char["bbox"][1] <= 110 for char in char_boxes)
    assert not any(line["needs_char_split"] for line in result["lines"])
