"""预处理预览页三端点：处理当前页 / 清空痕迹 / 保存(apply) 与任务详情。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from marker.backend import main, semantic_api
from marker.backend.database import Base
from marker.backend.models import (
    Book, BookPage, LayoutRegion, OcrPageJob, PageAssignment, RecognitionJob, TextChar, TextLine, User, WorkflowRevision,
)


@pytest.fixture()
def db_session(tmp_path: Path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)

    class FakeThread:  # 不真正启动后台线程
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
    monkeypatch.setattr(main, "Thread", FakeThread)
    yield db
    db.close()
    engine.dispose()


def _seed(db, tmp_path: Path, with_raw: bool = True, with_content: bool = True) -> tuple[User, BookPage]:
    admin = User(username="admin", password_hash="x", role="admin", is_active=True)
    db.add(admin)
    db.flush()
    book = Book(title="单页处理测试书", page_count=1, status="ready", created_by=admin.id)
    db.add(book)
    db.flush()
    image = tmp_path / f"page_{book.id}.png"
    image.write_bytes(b"png")
    page = BookPage(book_id=book.id, page_no=1, page_id=f"book{book.id}-p1", image_path=str(image), width=800, height=1200)
    db.add(page)
    db.flush()
    assignment = PageAssignment(book_id=book.id, page_id=page.id, user_id=admin.id, status="in_progress", current_step=2)
    db.add(assignment)
    db.flush()
    raw_path = ""
    if with_raw:
        raw = tmp_path / "ocr_raw" / f"book_{book.id}_page_0001_abcd.json"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(json.dumps({
            "regions": [{"region_type": "text", "order_no": 1, "bbox": [10, 10, 200, 400], "confirmed": False}],
            "lines": [{"region_order_no": 1, "order_no": 1, "bbox": [150, 10, 200, 400], "char_size": 0, "confirmed": False, "needs_char_split": False, "ocr_text": "右列"}],
            "chars": [{"line_order_no": 1, "order_no": 1, "bbox": [150, 10, 200, 205], "raw_text": "右", "corrected_text": "右", "candidates": ["右"], "confidence": 0.8, "status": "unchecked"}],
            "warnings": [],
        }, ensure_ascii=False), encoding="utf-8")
        raw_path = str(raw)
    if with_content:
        db.add(LayoutRegion(assignment_id=assignment.id, region_type="text", order_no=1, x1=0, y1=0, x2=10, y2=10))
        db.add(TextLine(assignment_id=assignment.id, region_id=None, order_no=1, x1=0, y1=0, x2=10, y2=5))
        db.add(TextChar(assignment_id=assignment.id, line_id=None, order_no=1, x1=0, y1=0, x2=2, y2=2, raw_text="本"))
    batch = RecognitionJob(book_id=book.id, status="done", total_pages=1)
    db.add(batch)
    db.flush()
    db.add(OcrPageJob(batch_id=batch.id, page_id=page.id, image_sha256="a" * 12, model="PaddleOCR-VL-1.6", params_hash="p", status="done", raw_path=raw_path))
    db.commit()
    return admin, page


def test_preprocess_single_page_preserves_existing_content(db_session, tmp_path: Path, monkeypatch):
    db = db_session
    admin, page = _seed(db, tmp_path, with_raw=True, with_content=True)
    from marker.backend.ocr_config import save_ocr_config
    save_ocr_config(db, access_token="test-token", clear_access_token=False, base_url="https://test.example/jobs", model="PaddleOCR-VL-1.6", updated_by=admin.id)
    result = main.preprocess_single_page(page.id, admin, db)
    assert result["ok"] is True
    assert db.query(LayoutRegion).count() == 1 and db.query(TextLine).count() == 1 and db.query(TextChar).count() == 1
    # 后台单页处理只更新 raw 预览，不在用户点击“保存”前覆盖原标注。
    preview = {
        "regions": [{"region_type": "text", "order_no": 1, "bbox": [20, 20, 300, 500], "confirmed": False}],
        "lines": [{"region_order_no": 1, "order_no": 1, "bbox": [200, 20, 300, 500], "char_size": 0, "confirmed": False, "needs_char_split": False, "ocr_text": "新预览"}],
        "chars": [], "warnings": [],
    }
    monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(main, "preprocess_page", lambda *args, **kwargs: preview)
    main.run_cloud_ocr_batch(result["recognition_job_id"])
    db.expire_all()
    old_region = db.query(LayoutRegion).one()
    assert [old_region.x1, old_region.y1, old_region.x2, old_region.y2] == [0, 0, 10, 10]
    latest = main.page_recognition_latest(page.id, admin, db)
    assert latest["result"]["lines"][0]["ocr_text"] == "新预览"


def test_preprocess_single_page_creates_forced_jobs(db_session, tmp_path: Path):
    db = db_session
    admin, page = _seed(db, tmp_path, with_raw=True, with_content=False)
    from marker.backend.ocr_config import save_ocr_config
    save_ocr_config(db, access_token="test-token", clear_access_token=False, base_url="https://test.example/jobs", model="PaddleOCR-VL-1.6", updated_by=admin.id)
    db.query(LayoutRegion).delete(); db.commit()
    result = main.preprocess_single_page(page.id, admin, db)
    assert result["ok"] is True and result["platform_job_id"] > 0
    job_row = db.query(OcrPageJob).filter(OcrPageJob.page_id == page.id, OcrPageJob.status == "pending").one()
    normal_hash = hashlib.sha256("PaddleOCR-VL-1.6|layout=1|seal=1|temperature=0|pipe=11".encode()).hexdigest()
    assert job_row.params_hash != normal_hash  # force 后缀绕过去重缓存
    assert page.recognition_status == "queued"


def test_clear_page_recognition_wipes_traces(db_session, tmp_path: Path):
    db = db_session
    admin, page = _seed(db, tmp_path, with_raw=True, with_content=True)
    raw_file = Path(db.query(OcrPageJob).first().raw_path)
    result = main.clear_page_recognition(page.id, admin, db)
    assert result["regions"] == 1 and result["lines"] == 1 and result["chars"] == 1
    assert result["raw_files"] == 1 and result["jobs"] == 1
    assert not raw_file.exists()
    assert db.query(OcrPageJob).count() == 0
    assert db.query(LayoutRegion).count() == 0 and db.query(TextLine).count() == 0 and db.query(TextChar).count() == 0
    assignment = db.query(PageAssignment).one()
    assert assignment.status == "assigned" and assignment.current_step == 1
    assert db.query(WorkflowRevision).filter(WorkflowRevision.action == "clear_recognition").count() == 1
    assert page.recognition_status == "pending"


def test_apply_recognition_seeds_and_replaces(db_session, tmp_path: Path):
    db = db_session
    admin, page = _seed(db, tmp_path, with_raw=True, with_content=False)
    result = main.apply_page_recognition(page.id, admin, db)
    assert result["applied"] == 1 and result["replaced"] == 0 and result["lines"] == 1 and result["chars"] == 1
    assert db.query(LayoutRegion).count() == 1 and db.query(TextLine).count() == 1
    # 已有内容 → 覆盖而非跳过
    result2 = main.apply_page_recognition(page.id, admin, db)
    assert result2["replaced"] == 1 and db.query(TextLine).count() == 1


def test_apply_recognition_conflicts_without_raw(db_session, tmp_path: Path):
    db = db_session
    admin, page = _seed(db, tmp_path, with_raw=False, with_content=False)
    with pytest.raises(HTTPException) as exc:
        main.apply_page_recognition(page.id, admin, db)
    assert exc.value.status_code == 409


def test_platform_job_detail_returns_logs(db_session, tmp_path: Path):
    db = db_session
    admin, page = _seed(db, tmp_path, with_raw=False, with_content=False)
    from marker.backend.models import PlatformJob
    job = PlatformJob(job_type="page_preprocess", book_id=page.book_id, page_id=page.id, created_by=admin.id, status="running", progress=42,
                      payload_json=json.dumps({"page_no": 1}), result_json=json.dumps({"stage": "② 墨迹投影切列", "logs": ["[第 1 页] ① 整页版面识别", "[第 1 页] ② 墨迹投影切列（剔除界栏/版框）"]}))
    db.add(job); db.commit(); db.refresh(job)
    detail = semantic_api.job_detail(job.id, admin, db)
    assert detail["job_type"] == "page_preprocess" and detail["progress"] == 42
    assert detail["result"]["stage"].startswith("②")
    assert len(detail["result"]["logs"]) == 2
