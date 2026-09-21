"""任务 OCR 重置端点（all / columns 两种模式）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from marker.backend import main
from marker.backend.database import Base
from marker.backend.models import (
    Book, BookPage, LayoutRegion, OcrPageJob, PageAssignment, RecognitionJob, TextChar, TextLine, User,
)


@pytest.fixture()
def db_session(tmp_path: Path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    yield db
    db.close()
    engine.dispose()


RESULT = {
    "regions": [
        {"region_type": "text", "order_no": 1, "bbox": [10, 10, 200, 400], "confirmed": False},
        {"region_type": "seal", "order_no": 2, "bbox": [300, 300, 380, 380], "confirmed": False},
    ],
    "lines": [
        {"region_order_no": 1, "order_no": 1, "bbox": [150, 10, 200, 400], "char_size": 0, "confirmed": False, "needs_char_split": False, "ocr_text": "右列"},
        {"region_order_no": 1, "order_no": 2, "bbox": [100, 10, 150, 400], "char_size": 0, "confirmed": False, "needs_char_split": False, "ocr_text": "左列"},
    ],
    "chars": [
        {"line_order_no": 1, "order_no": 1, "bbox": [150, 10, 200, 205], "raw_text": "右", "corrected_text": "右", "candidates": ["右"], "confidence": 0.8, "status": "unchecked"},
        {"line_order_no": 1, "order_no": 2, "bbox": [150, 205, 200, 400], "raw_text": "列", "corrected_text": "列", "candidates": ["列"], "confidence": 0.8, "status": "unchecked"},
        {"line_order_no": 2, "order_no": 3, "bbox": [100, 10, 150, 205], "raw_text": "左", "corrected_text": "左", "candidates": ["左"], "confidence": 0.8, "status": "unchecked"},
        {"line_order_no": 2, "order_no": 4, "bbox": [100, 205, 150, 400], "raw_text": "列", "corrected_text": "列", "candidates": ["列"], "confidence": 0.8, "status": "unchecked"},
    ],
    "warnings": [],
}


def _seed(db, tmp_path: Path, with_raw: bool = True) -> tuple[User, int]:
    admin = User(username="admin", password_hash="x", role="admin", is_active=True)
    db.add(admin)
    db.flush()
    book = Book(title="重置测试书", page_count=1, status="ready", created_by=admin.id)
    db.add(book)
    db.flush()
    image = tmp_path / "page.png"
    image.write_bytes(b"png")
    page = BookPage(book_id=book.id, page_no=1, page_id=f"book{book.id}-p1", image_path=str(image), width=800, height=1200)
    db.add(page)
    db.flush()
    assignment = PageAssignment(book_id=book.id, page_id=page.id, user_id=admin.id, status="in_progress")
    db.add(assignment)
    db.flush()
    batch = RecognitionJob(book_id=book.id, status="done", total_pages=1)
    db.add(batch)
    db.flush()
    raw_path = ""
    if with_raw:
        raw = tmp_path / "ocr_raw" / f"book_{book.id}_page_0001_abcd.json"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(json.dumps(RESULT, ensure_ascii=False), encoding="utf-8")
        raw_path = str(raw)
    db.add(OcrPageJob(batch_id=batch.id, page_id=page.id, image_sha256="a" * 12, model="m", params_hash="p", status="done", raw_path=raw_path))
    main.seed_assignment_from_recognition(db, assignment, RESULT)
    return admin, assignment.id


def test_reset_ocr_all_restores_recognition(db_session, tmp_path: Path):
    db = db_session
    admin, assignment_id = _seed(db, tmp_path)
    # 模拟用户改动：移动区域、删除两列与字
    db.query(TextChar).delete()
    db.query(TextLine).delete()
    region = db.query(LayoutRegion).filter(LayoutRegion.order_no == 1).first()
    region.x1, region.y1 = 55, 66
    db.commit()
    result = main.reset_assignment_ocr(assignment_id, main.OcrResetIn(mode="all"), admin, db)
    assert len(result["regions"]) == 2 and result["regions"][0]["bbox"] == [10.0, 10.0, 200.0, 400.0]
    assert len(result["lines"]) == 2 and result["chars"][0]["raw_text"] == "右"
    assignment = db.get(PageAssignment, assignment_id)
    assert assignment.status == "in_progress"
    assert db.query(main.WorkflowRevision).filter(main.WorkflowRevision.action == "reset_ocr_all").count() == 1


def test_reset_ocr_columns_keeps_regions(db_session, tmp_path: Path):
    db = db_session
    admin, assignment_id = _seed(db, tmp_path)
    db.query(TextChar).delete()
    db.query(TextLine).delete()
    region = db.query(LayoutRegion).filter(LayoutRegion.order_no == 1).first()
    region.x2 = 250  # 用户放大了区域
    db.commit()
    result = main.reset_assignment_ocr(assignment_id, main.OcrResetIn(mode="columns"), admin, db)
    assert len(result["regions"]) == 2 and result["regions"][0]["bbox"][2] == 250.0  # 区域保留用户改动
    assert len(result["lines"]) == 2 and len(result["chars"]) == 4
    # 列按中点落点重新挂回区域：右列中点 x=175 ∈ [10,250]
    line_ids = {line["id"] for line in result["lines"]}
    assert len(line_ids) == 2
    region_one = next(r for r in result["regions"] if r["order_no"] == 1)
    for line in db.query(TextLine).all():
        assert line.region_id == region_one["id"]
        assert line.ocr_text in ("右列", "左列")


def test_reset_ocr_without_raw_conflicts(db_session, tmp_path: Path):
    db = db_session
    admin, assignment_id = _seed(db, tmp_path, with_raw=False)
    with pytest.raises(HTTPException) as exc:
        main.reset_assignment_ocr(assignment_id, main.OcrResetIn(mode="all"), admin, db)
    assert exc.value.status_code == 409
    # 失败不破坏既有数据
    assert db.query(LayoutRegion).count() == 2 and db.query(TextLine).count() == 2


def test_recognition_latest_returns_result(db_session, tmp_path: Path):
    db = db_session
    _seed(db, tmp_path)
    page = db.query(BookPage).first()
    detail = main.page_recognition_latest(page.id, db.query(User).first(), db)
    assert detail["job"]["status"] == "done" and detail["job"]["attempts"] >= 0
    assert len(detail["result"]["regions"]) == 2
    assert len(detail["result"]["lines"]) == 2 and len(detail["result"]["chars"]) == 4


def test_recognition_latest_404_without_raw(db_session, tmp_path: Path):
    db = db_session
    admin, _assignment_id = _seed(db, tmp_path, with_raw=False)
    page = db.query(BookPage).first()
    with pytest.raises(HTTPException) as exc:
        main.page_recognition_latest(page.id, admin, db)
    assert exc.value.status_code == 404
