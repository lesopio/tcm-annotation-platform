from copy import deepcopy

from marker.backend.workflow_engine import default_graph, validate_graph
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from marker.backend.database import Base
from marker.backend.main import create_book_workflow_run, refresh_workflow_run
from marker.backend.models import Book, BookPage, User, WorkflowNodeRun, WorkflowPageTask, WorkflowTemplate, WorkflowVersion
import json


def test_default_annotation_workflow_is_valid():
    result = validate_graph(default_graph())
    assert result["ok"] is True
    assert result["order"][0] == "start"
    assert result["order"][-1] == "end"


def test_cycle_is_rejected():
    graph = default_graph()
    graph["edges"].append({"source": "character", "target": "region"})
    result = validate_graph(graph)
    assert result["ok"] is False
    assert any("循环" in error for error in result["errors"])


def test_core_stage_dependency_is_rejected():
    graph = deepcopy(default_graph())
    graph["edges"] = [edge for edge in graph["edges"] if edge != {"source": "region_review", "target": "layout"}]
    graph["edges"].append({"source": "layout_review", "target": "region"})
    result = validate_graph(graph)
    assert result["ok"] is False
    assert any("区域标注之后" in error or "循环" in error for error in result["errors"])


def test_orphan_node_is_rejected():
    graph = default_graph()
    graph["nodes"].append({"id": "extra_review", "type": "final_review", "label": "额外复核", "role": "reviewer", "position": {"x": 0, "y": 0}, "params": {}})
    result = validate_graph(graph)
    assert result["ok"] is False
    assert any("有效路径" in error for error in result["errors"])


def test_book_run_waits_for_every_page_before_advancing():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(username="admin", password_hash="x", role="admin", display_name="管理员", is_active=True)
        db.add(admin); db.flush()
        book = Book(title="测试书", created_by=admin.id, page_count=2)
        db.add(book); db.flush()
        db.add_all([
            BookPage(book_id=book.id, page_no=1, page_id="test-1", width=100, height=100),
            BookPage(book_id=book.id, page_no=2, page_id="test-2", width=100, height=100),
        ])
        template = WorkflowTemplate(name="测试流程", created_by=admin.id)
        db.add(template); db.flush()
        version = WorkflowVersion(template_id=template.id, version=1, status="published", graph_json=json.dumps(default_graph()), created_by=admin.id)
        db.add(version); db.commit()
        run = create_book_workflow_run(db, book, version)
        ocr = db.query(WorkflowNodeRun).filter_by(run_id=run.id, node_type="ocr").one()
        region = db.query(WorkflowNodeRun).filter_by(run_id=run.id, node_type="region").one()
        assert ocr.status == "waiting_config"
        assert region.status == "blocked"
        tasks = db.query(WorkflowPageTask).filter_by(node_run_id=ocr.id).order_by(WorkflowPageTask.id).all()
        tasks[0].status = "skipped"
        ocr.status = "active"
        db.flush(); refresh_workflow_run(db, run)
        assert region.status == "blocked"
        tasks[1].status = "skipped"
        ocr.status = "completed"
        db.flush(); refresh_workflow_run(db, run)
        assert region.status == "ready"
