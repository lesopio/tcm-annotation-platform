"""书籍硬删除级联与识别批次详情。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from marker.backend import main
from marker.backend.database import Base
from marker.backend.models import (
    Book, BookPage, CharacterEntry, GraphEdge, GraphNode, LabelDefinition, LayoutRegion,
    MedicalCase, OntologyType, OcrPageJob, PageAssignment, PlatformJob, RecognitionJob,
    SemanticEntity, SemanticRelation, TextChar, TextLine, TextUnit, User, WorkflowNodeRun,
    WorkflowPageTask, BookWorkflowRun,
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


def _seed_book_tree(db, tmp_path: Path) -> int:
    admin = User(username="admin", password_hash="x", role="admin", display_name="管理员", is_active=True)
    db.add(admin)
    db.flush()
    book = Book(title="删除测试书", page_count=1, status="ready", created_by=admin.id)
    db.add(book)
    db.flush()
    page_dir = tmp_path / "books" / str(book.id) / "pages"
    page_dir.mkdir(parents=True)
    image = page_dir / "page_0001.png"
    image.write_bytes(b"png")
    page = BookPage(book_id=book.id, page_no=1, page_id=f"book{book.id}-p1", image_path=str(image), width=100, height=100)
    db.add(page)
    db.flush()
    assignment = PageAssignment(book_id=book.id, page_id=page.id, user_id=admin.id, status="assigned")
    db.add(assignment)
    db.flush()
    region = LayoutRegion(assignment_id=assignment.id, region_type="text", order_no=1, x1=0, y1=0, x2=10, y2=10)
    line = TextLine(assignment_id=assignment.id, region_id=None, order_no=1, x1=0, y1=0, x2=10, y2=5)
    char = TextChar(assignment_id=assignment.id, line_id=None, order_no=1, x1=0, y1=0, x2=2, y2=2, raw_text="本")
    db.add_all([region, line, char])
    unit = TextUnit(book_id=book.id, page_id=page.id, stable_id="u1")
    db.add(unit)
    db.flush()
    db.add_all([
        SemanticEntity(text_unit_id=unit.id, assignment_id=assignment.id, type_id=0, canonical_name="本", surface_text="本", start_offset=0, end_offset=1, source="manual", created_by=admin.id),
        SemanticRelation(text_unit_id=unit.id, assignment_id=assignment.id, type_id=0, source_entity_id=1, target_entity_id=1, source="manual", created_by=admin.id),
        MedicalCase(text_unit_id=unit.id, assignment_id=assignment.id, source="manual", created_by=admin.id),
    ])
    batch = RecognitionJob(book_id=book.id, status="done", total_pages=1)
    db.add(batch)
    db.flush()
    db.add(OcrPageJob(batch_id=batch.id, page_id=page.id, image_sha256="a" * 12, model="m", params_hash="p", status="done"))
    run = BookWorkflowRun(book_id=book.id, workflow_version_id=1)
    db.add(run)
    db.flush()
    node = WorkflowNodeRun(run_id=run.id, node_key="region", node_type="region", label="区域标注", role="annotator", status="completed", completed_pages=1, total_pages=1)
    db.add(node)
    db.flush()
    db.add(WorkflowPageTask(run_id=run.id, node_run_id=node.id, page_id=page.id, assignee_id=admin.id, status="completed"))
    db.add_all([
        LabelDefinition(book_id=book.id, group="region", code="R1", name="正文", color="#000000"),
        OntologyType(book_id=book.id, kind="entity", code="doctor", name="医家", color="#000000"),
    ])
    graph_node = GraphNode(book_id=book.id, type_code="doctor", canonical_name="张三", evidence_count=1)
    db.add(graph_node)
    db.flush()
    db.add(GraphEdge(book_id=book.id, type_code="teacher_of", source_node_id=graph_node.id, target_node_id=graph_node.id))
    glyph = tmp_path / "custom_glyphs" / f"char_book{book.id}.png"
    glyph.parent.mkdir(parents=True, exist_ok=True)
    glyph.write_bytes(b"g")
    global_glyph = tmp_path / "custom_glyphs" / "char_global.png"
    global_glyph.write_bytes(b"g")
    db.add(CharacterEntry(book_id=book.id, unicode_codepoint="U+672C", character="本", ids="", radical="", glyph_path=str(glyph), created_by=admin.id))
    db.add(CharacterEntry(book_id=None, unicode_codepoint="U+7B54", character="答", ids="", radical="", glyph_path=str(global_glyph), created_by=admin.id))
    db.add(PlatformJob(job_type="batch_ocr", book_id=book.id, created_by=admin.id, status="succeeded", progress=100))
    raw = tmp_path / "ocr_raw" / f"book_{book.id}_page_0001_aaaaaaaaaaaa.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("{}")
    db.commit()
    return book.id


def test_delete_book_cascades_everything(db_session, tmp_path: Path):
    db = db_session
    book_id = _seed_book_tree(db, tmp_path)
    result = main.delete_book(book_id, admin := db.query(User).first(), db)
    assert result == {"ok": True, "deleted": book_id}
    assert db.get(Book, book_id) is None
    for model in (BookPage, PageAssignment, LayoutRegion, TextLine, TextChar, TextUnit,
                  SemanticEntity, SemanticRelation, MedicalCase, RecognitionJob, OcrPageJob,
                  BookWorkflowRun, WorkflowNodeRun, WorkflowPageTask, LabelDefinition,
                  OntologyType, GraphNode, GraphEdge, PlatformJob):
        assert db.query(model).count() == 0, f"{model.__tablename__} 未清空"
    # 本书字形删除，全局字形保留
    entries = db.query(CharacterEntry).all()
    assert [e.character for e in entries] == ["答"]
    assert not (tmp_path / "books" / str(book_id)).exists()
    assert not list((tmp_path / "ocr_raw").glob(f"book_{book_id}_*"))
    assert not (tmp_path / "custom_glyphs" / f"char_book{book_id}.png").exists()
    assert (tmp_path / "custom_glyphs" / "char_global.png").exists()


def test_delete_book_blocked_while_batch_running(db_session, tmp_path: Path):
    db = db_session
    book_id = _seed_book_tree(db, tmp_path)
    batch = db.query(RecognitionJob).first()
    batch.status = "running"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        main.delete_book(book_id, db.query(User).first(), db)
    assert exc.value.status_code == 409
    assert db.get(Book, book_id) is not None


def test_recognition_job_detail_returns_pages(db_session, tmp_path: Path):
    db = db_session
    _seed_book_tree(db, tmp_path)
    batch_id = db.query(RecognitionJob).first().id
    detail = main.recognition_job_detail(batch_id, db.query(User).first(), db)
    assert detail["status"] == "done"
    assert len(detail["pages"]) == 1
    assert detail["pages"][0]["status"] == "done"
