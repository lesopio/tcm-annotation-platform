from __future__ import annotations

import json
import hashlib
import shutil
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Annotated, Literal
from urllib.parse import urlparse

import fitz
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import create_token, get_current_user, hash_password, require_admin, verify_password
from .bootstrap import bootstrap, cleanup_stale_exports
from .database import Base, DATA_DIR, DB_PATH, EXPORT_DIR, IMPORT_DIR, SessionLocal, engine, get_db
from .models import (
    AdjudicationRecord,
    Annotation,
    AnnotationRevision,
    Book,
    BookEntity,
    BookPage,
    BookWorkflowRun,
    CharacterEntry,
    EntityAnnotation,
    EntityType,
    GraphEdge,
    GraphNode,
    Guideline,
    ImportBatch,
    LayoutRegion,
    LabelDefinition,
    MedicalCase,
    OntologyType,
    OcrPageJob,
    Page,
    PageAssignment,
    PageSegment,
    PlatformJob,
    RecognitionJob,
    ReviewRecord,
    SemanticEntity,
    SemanticRelation,
    TextChar,
    TextLine,
    TextUnit,
    User,
    WorkflowRevision,
    WorkflowNodeRun,
    WorkflowPageTask,
    WorkflowTemplate,
    WorkflowVersion,
)
from .ocr_service import call_paddleocr_vl_api, normalize_paddleocr_vl_response, recognize_crop, recognize_page_layout_and_text
from .preprocess import preprocess_page
from .ocr_config import effective_ocr_config, public_ocr_config, save_ocr_config
from .platform_config import is_test_mode, public_platform_setting, set_test_mode
from .renderer import cache_all_status, cleanup_temp_files, ensure_cache_window, render_page, start_cache_all_pages
from .segmenter import cut_vertical_segments
from .serializers import (
    annotation_out,
    assignment_out,
    book_entity_out,
    book_out,
    book_page_out,
    character_entry_out,
    entity_annotation_out,
    entity_out,
    guideline_out,
    layout_region_out,
    label_definition_out,
    ocr_page_job_out,
    page_out,
    page_segment_out,
    recognition_job_out,
    text_char_out,
    text_line_out,
    user_out,
    workflow_revision_out,
)
from .settings import settings
from .workflow_engine import NODE_TYPES, default_graph, validate_graph
from .semantic_api import router as semantic_router

app = FastAPI(title="Bencao-VSR Annotation Platform")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(semantic_router)

BOOK_RENDER_LOCK = Lock()
ACTIVE_UPLOADS_LOCK = Lock()
ACTIVE_UPLOADS: set[tuple[str, int]] = set()


class LoginIn(BaseModel):
    username: str
    password: str


class EntityIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    description: str = ""
    is_active: bool = True


class GuidelineIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1)
    sort_order: int = 0
    is_active: bool = True
    version: int = Field(default=1, ge=1)
    status: Literal["draft", "published", "retired"] = "draft"
    scope: str = "全平台"
    examples: list[dict] = []


class AnnotationIn(BaseModel):
    page_id: str
    entity_id: int
    bbox: list[float] = Field(min_length=4, max_length=4)
    note: str = ""
    status: str = "draft"


class AnnotationUpdate(BaseModel):
    entity_id: int | None = None
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    note: str | None = None
    status: str | None = None
    is_deleted: bool | None = None


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str | None = Field(default=None, min_length=4)
    role: Literal["admin", "annotator", "reviewer", "expert", "data_engineer"] = "annotator"
    display_name: str = ""
    is_active: bool = True


class ReviewIn(BaseModel):
    status: Literal["draft", "pending", "approved", "rejected"]


class BookUpdateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    task_prompt: str = ""
    status: str = "active"


class BookEntityIn(BaseModel):
    id: int | None = None
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=180)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    description: str = ""
    is_active: bool = True


class AssignmentRangeIn(BaseModel):
    user_id: int
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)


class AssignmentRangesIn(BaseModel):
    items: list[AssignmentRangeIn]


class BoxIn(BaseModel):
    id: int | None = None
    bbox: list[float] = Field(min_length=4, max_length=4)


class LayoutRegionIn(BoxIn):
    region_type: str = "text"
    label_id: int | None = None
    order_no: int = 1
    confirmed: bool = False


class TextLineIn(BoxIn):
    region_id: int | None = None
    layout_label_id: int | None = None
    stratum_label_id: int | None = None
    order_no: int = 1
    char_size: float = 0
    confirmed: bool = False
    needs_char_split: bool = False
    ocr_text: str = ""


class TextCharIn(BoxIn):
    line_id: int | None = None
    custom_char_id: int | None = None
    order_no: int = 1
    raw_text: str = ""
    corrected_text: str = ""
    candidates: list[str] = []
    confidence: float = 0
    status: Literal["unchecked", "confirmed", "unclear", "missing"] = "unchecked"


class EntityAnnotationIn(BoxIn):
    entity_id: int
    note: str = ""


class WorkflowSaveIn(BaseModel):
    expected_version: int = Field(ge=1)
    current_step: int = Field(default=1, ge=1, le=6)
    regions: list[LayoutRegionIn] = []
    lines: list[TextLineIn] = []
    chars: list[TextCharIn] = []
    entity_annotations: list[EntityAnnotationIn] = []


class ReviewActionIn(BaseModel):
    action: Literal["approve", "return"]
    comment: str = ""


class LabelDefinitionIn(BaseModel):
    id: int | None = None
    group: Literal["region", "layout", "stratum"]
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=160)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    description: str = ""
    sort_order: int = 0
    is_active: bool = True


class CharacterEntryIn(BaseModel):
    book_id: int | None = None
    unicode_codepoint: str = ""
    character: str = Field(default="", max_length=20)
    ids: str = ""
    radical: str = ""
    strokes: int | None = Field(default=None, ge=0, le=99)
    readings: str = ""
    aliases: str = ""
    source_page_id: int | None = None


class CharacterReviewIn(BaseModel):
    action: Literal["promote", "reject"]


class OcrBatchIn(BaseModel):
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)


class OcrSettingsIn(BaseModel):
    access_token: str | None = Field(default=None, max_length=4096)
    clear_access_token: bool = False
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="PaddleOCR-VL-1.6", min_length=1, max_length=120)


class WorkflowDefinitionIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    graph: dict


class WorkflowGraphIn(BaseModel):
    graph: dict


class WorkflowBindIn(BaseModel):
    version_id: int


class WorkflowTaskAssignIn(BaseModel):
    user_id: int
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)


class WorkflowTaskActionIn(BaseModel):
    action: Literal["complete", "approve", "return"] = "complete"
    comment: str = ""


@app.on_event("startup")
def on_startup() -> None:
    _backup_database_for_migration(3)
    Base.metadata.create_all(bind=engine)
    _migrate_db()
    db = SessionLocal()
    try:
        bootstrap(db)
        ensure_builtin_workflow(db)
    finally:
        db.close()
    cleanup_temp_files()
    cleanup_stale_exports()


def _migrate_db() -> None:
    with engine.connect() as conn:
        def add_columns(table: str, definitions: dict[str, str]) -> None:
            columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
            for name, definition in definitions.items():
                if name not in columns:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

        add_columns("users", {"is_ai_expert": "BOOLEAN DEFAULT 0"})
        add_columns("page_assignments", {"version": "INTEGER DEFAULT 1"})
        add_columns("layout_regions", {"label_id": "INTEGER REFERENCES label_definitions(id)"})
        add_columns("text_lines", {
            "region_id": "INTEGER REFERENCES layout_regions(id)",
            "layout_label_id": "INTEGER REFERENCES label_definitions(id)",
            "stratum_label_id": "INTEGER REFERENCES label_definitions(id)",
            "needs_char_split": "BOOLEAN DEFAULT 0",
            "ocr_text": "TEXT DEFAULT ''",
        })
        add_columns("text_chars", {"custom_char_id": "INTEGER REFERENCES character_entries(id)"})
        add_columns("guidelines", {
            "version": "INTEGER DEFAULT 1",
            "status": "VARCHAR(24) DEFAULT 'draft'",
            "scope": "VARCHAR(240) DEFAULT '全平台'",
            "examples_json": "TEXT DEFAULT '[]'",
            "published_at": "DATETIME",
        })
        conn.exec_driver_sql("PRAGMA user_version = 3")
        conn.commit()


def _backup_database_for_migration(target_version: int) -> None:
    if not DB_PATH.exists():
        return
    with engine.connect() as conn:
        current = int(conn.exec_driver_sql("PRAGMA user_version").scalar() or 0)
    if current >= target_version:
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DB_PATH.with_name(f"{DB_PATH.stem}.before_v{target_version}_{stamp}{DB_PATH.suffix}")
    shutil.copy2(DB_PATH, backup)


def ensure_builtin_workflow(db: Session) -> None:
    template = db.query(WorkflowTemplate).filter(WorkflowTemplate.is_builtin.is_(True)).first()
    if template:
        return
    admin = db.query(User).filter(User.role == "admin").order_by(User.id).first()
    if not admin:
        return
    template = WorkflowTemplate(name="古籍三阶段标准流程", description="OCR、三阶段标注、逐阶段审核、终审与导出", is_builtin=True, created_by=admin.id)
    db.add(template)
    db.flush()
    db.add(WorkflowVersion(template_id=template.id, version=1, status="published", graph_json=json.dumps(default_graph(), ensure_ascii=False), created_by=admin.id, published_at=datetime.now(timezone.utc)))
    db.commit()


def workflow_version_out(db: Session, version: WorkflowVersion) -> dict:
    return {
        "id": version.id, "template_id": version.template_id, "version": version.version,
        "status": version.status, "graph": json.loads(version.graph_json),
        "published_at": version.published_at.isoformat() if version.published_at else None,
        "created_at": version.created_at.isoformat(), "updated_at": version.updated_at.isoformat(),
    }


def workflow_template_out(db: Session, template: WorkflowTemplate) -> dict:
    versions = db.query(WorkflowVersion).filter(WorkflowVersion.template_id == template.id).order_by(WorkflowVersion.version.desc()).all()
    draft = next((item for item in versions if item.status == "draft"), None)
    published = next((item for item in versions if item.status == "published"), None)
    return {
        "id": template.id, "name": template.name, "description": template.description,
        "is_builtin": template.is_builtin, "draft": workflow_version_out(db, draft) if draft else None,
        "published": workflow_version_out(db, published) if published else None,
        "versions": [{"id": item.id, "version": item.version, "status": item.status, "published_at": item.published_at.isoformat() if item.published_at else None} for item in versions],
        "created_at": template.created_at.isoformat(), "updated_at": template.updated_at.isoformat(),
    }


def node_run_out(db: Session, node: WorkflowNodeRun) -> dict:
    tasks = db.query(WorkflowPageTask).filter(WorkflowPageTask.node_run_id == node.id).all()
    return {
        "id": node.id, "node_key": node.node_key, "node_type": node.node_type, "label": node.label,
        "role": node.role, "status": node.status, "completed_pages": sum(item.status in ("done", "approved", "skipped") for item in tasks),
        "total_pages": len(tasks),
        "tasks": [{"id": item.id, "page_id": item.page_id, "page_no": db.get(BookPage, item.page_id).page_no if db.get(BookPage, item.page_id) else 0, "assignee_id": item.assignee_id, "status": item.status, "comment": item.comment, "version": item.version} for item in tasks],
    }


def book_workflow_out(db: Session, run: BookWorkflowRun) -> dict:
    version = db.get(WorkflowVersion, run.workflow_version_id)
    nodes = db.query(WorkflowNodeRun).filter(WorkflowNodeRun.run_id == run.id).order_by(WorkflowNodeRun.id).all()
    return {
        "id": run.id, "book_id": run.book_id, "workflow_version_id": run.workflow_version_id,
        "pending_version_id": run.pending_version_id, "status": run.status,
        "graph": json.loads(version.graph_json) if version else {"nodes": [], "edges": []},
        "nodes": [node_run_out(db, item) for item in nodes],
        "started_at": run.started_at.isoformat(), "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def refresh_workflow_run(db: Session, run: BookWorkflowRun) -> None:
    version = db.get(WorkflowVersion, run.workflow_version_id)
    if not version:
        return
    graph = json.loads(version.graph_json)
    incoming: dict[str, list[str]] = {str(node["id"]): [] for node in graph["nodes"]}
    for edge in graph["edges"]:
        incoming.setdefault(str(edge["target"]), []).append(str(edge["source"]))
    node_runs = {item.node_key: item for item in db.query(WorkflowNodeRun).filter(WorkflowNodeRun.run_id == run.id).all()}
    changed = True
    while changed:
        changed = False
        for graph_node in graph["nodes"]:
            item = node_runs.get(str(graph_node["id"]))
            if not item or item.status in ("completed", "retired"):
                continue
            predecessors = [node_runs.get(key) for key in incoming.get(item.node_key, [])]
            if all(parent and parent.status == "completed" for parent in predecessors):
                if item.node_type in ("start", "end"):
                    item.status = "completed"
                    item.completed_at = datetime.now(timezone.utc)
                    changed = True
                elif item.status == "blocked":
                    item.status = "waiting_config" if item.node_type in ("ocr", "export") else "ready"
                    item.started_at = datetime.now(timezone.utc)
                    for task in db.query(WorkflowPageTask).filter(WorkflowPageTask.node_run_id == item.id, WorkflowPageTask.status == "blocked").all():
                        task.status = "ready"
                    changed = True
    end_run = next((item for item in node_runs.values() if item.node_type == "end"), None)
    if end_run and end_run.status == "completed":
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
    db.flush()


def create_book_workflow_run(db: Session, book: Book, version: WorkflowVersion) -> BookWorkflowRun:
    graph = json.loads(version.graph_json)
    result = validate_graph(graph)
    if not result["ok"] or version.status != "published":
        raise HTTPException(status_code=400, detail="只能绑定校验通过的已发布工作流")
    existing = db.query(BookWorkflowRun).filter(BookWorkflowRun.book_id == book.id).first()
    if existing:
        raise HTTPException(status_code=409, detail="该书已绑定工作流；请使用升级接口")
    run = BookWorkflowRun(book_id=book.id, workflow_version_id=version.id, status="active")
    db.add(run)
    db.flush()
    pages = db.query(BookPage).filter(BookPage.book_id == book.id).order_by(BookPage.page_no).all()
    for graph_node in graph["nodes"]:
        spec = NODE_TYPES[str(graph_node["type"])]
        node_run = WorkflowNodeRun(run_id=run.id, node_key=str(graph_node["id"]), node_type=str(graph_node["type"]), label=str(graph_node.get("label") or spec["label"]), role=str(graph_node.get("role") or spec["role"]), status="blocked", total_pages=len(pages))
        db.add(node_run)
        db.flush()
        if node_run.node_type not in ("start", "end"):
            for page in pages:
                db.add(WorkflowPageTask(run_id=run.id, node_run_id=node_run.id, page_id=page.id, status="blocked"))
    refresh_workflow_run(db, run)
    db.commit()
    db.refresh(run)
    return run


@app.get("/api/dashboard")
def dashboard(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    assignments = db.query(PageAssignment)
    if user.role == "annotator":
        assignments = assignments.filter(PageAssignment.user_id == user.id)
    rows = assignments.all()
    task_query = db.query(WorkflowPageTask)
    if user.role != "admin":
        task_query = task_query.filter(WorkflowPageTask.assignee_id == user.id)
    tasks = task_query.all()
    return {
        "role": user.role,
        "stats": {
            "books": db.query(Book).count(), "pages": db.query(BookPage).count(),
            "ready": sum(item.status in ("ready", "assigned") for item in tasks) if tasks else sum(item.status == "assigned" for item in rows),
            "in_progress": sum(item.status == "in_progress" for item in tasks) if tasks else sum(item.status == "in_progress" for item in rows),
            "submitted": sum(item.status == "submitted" for item in rows),
            "approved": sum(item.status == "approved" for item in rows),
            "returned": sum(item.status == "returned" for item in rows),
            "ocr_running": db.query(RecognitionJob).filter(RecognitionJob.status.in_(["pending", "running"])).count(),
        },
        "recent": [assignment_out(item) for item in sorted(rows, key=lambda row: row.updated_at, reverse=True)[:8]],
    }


@app.get("/api/workflows/node-types")
def workflow_node_types(_: Annotated[User, Depends(require_admin)]) -> dict:
    return {"types": [{"type": key, **value} for key, value in NODE_TYPES.items()]}


@app.get("/api/settings/ocr")
def get_ocr_settings(_: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    return public_ocr_config(db)


class PlatformSettingsIn(BaseModel):
    test_mode: bool = False


@app.get("/api/settings/platform")
def get_platform_settings(_: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    return public_platform_setting(db)


@app.put("/api/settings/platform")
def update_platform_settings(
    payload: PlatformSettingsIn,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    return set_test_mode(db, payload.test_mode, admin.id)


@app.put("/api/settings/ocr")
def update_ocr_settings(
    payload: OcrSettingsIn,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    base_url = payload.base_url.strip()
    if base_url:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(status_code=422, detail="API 地址必须是有效的 HTTP 或 HTTPS 地址")
    return save_ocr_config(
        db,
        access_token=payload.access_token.strip() if payload.access_token else None,
        clear_access_token=payload.clear_access_token,
        base_url=base_url.rstrip("/"),
        model=payload.model,
        updated_by=admin.id,
    )


@app.post("/api/settings/ocr/test")
def test_ocr_settings(
    payload: OcrSettingsIn,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    test_mode = is_test_mode(db)
    if test_mode and settings.test_ocr_token:
        config = effective_ocr_config(db)
        note = "测试模式：使用 .env 测试凭据真实调用"
    else:
        config = effective_ocr_config(db)
        if payload.access_token and payload.access_token.strip():
            config["access_token"] = payload.access_token.strip()
        config["base_url"] = payload.base_url.strip().rstrip("/")
        config["model"] = payload.model.strip()
        note = ""
    if payload.access_token and payload.access_token.strip():
        config["access_token"] = payload.access_token.strip()
    config["base_url"] = payload.base_url.strip().rstrip("/")
    config["model"] = payload.model.strip()
    if not config["access_token"]:
        raise HTTPException(status_code=409, detail="请先输入或保存 OCR 模型密钥")
    if config["base_url"]:
        parsed = urlparse(config["base_url"])
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(status_code=422, detail="API 地址必须是有效的 HTTP 或 HTTPS 地址")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        test_path = Path(handle.name)
    try:
        image = Image.new("RGB", (960, 480), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((55, 55, 905, 425), outline="black", width=4)
        draw.text((110, 145), "OCR CONNECTION TEST", fill="black")
        draw.text((110, 235), "PADDLE OCR MODEL CHECK 2026", fill="black")
        image.save(test_path)
        started_at = time.perf_counter()
        raw = call_paddleocr_vl_api(test_path, config=config)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        normalized = normalize_paddleocr_vl_response(raw)
        return {
            "ok": True,
            "model": config["model"],
            "elapsed_ms": elapsed_ms,
            "region_count": len(normalized.get("regions", [])),
            "line_count": len(normalized.get("lines", [])),
            "warnings": ([note] if note else []) + normalized.get("warnings", []),
        }
    except HTTPException:
        raise
    except Exception as exc:
        message = str(exc).replace(config["access_token"], "[已隐藏]")
        raise HTTPException(status_code=502, detail=f"OCR 模型测试失败：{message}") from exc
    finally:
        test_path.unlink(missing_ok=True)


@app.get("/api/workflows")
def list_workflow_templates(_: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    ensure_builtin_workflow(db)
    return {"items": [workflow_template_out(db, item) for item in db.query(WorkflowTemplate).order_by(WorkflowTemplate.id).all()]}


@app.post("/api/workflows/validate")
def validate_workflow(payload: WorkflowGraphIn, _: Annotated[User, Depends(require_admin)]) -> dict:
    return validate_graph(payload.graph)


@app.post("/api/workflows")
def create_workflow_template(payload: WorkflowDefinitionIn, admin: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    result = validate_graph(payload.graph)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail={"message": "工作流校验失败", "errors": result["errors"]})
    template = WorkflowTemplate(name=payload.name, description=payload.description, created_by=admin.id)
    db.add(template)
    db.flush()
    db.add(WorkflowVersion(template_id=template.id, version=1, status="draft", graph_json=json.dumps(payload.graph, ensure_ascii=False), created_by=admin.id))
    db.commit()
    db.refresh(template)
    return workflow_template_out(db, template)


@app.get("/api/workflows/{template_id}")
def get_workflow_template(template_id: int, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    template = db.get(WorkflowTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return workflow_template_out(db, template)


@app.put("/api/workflows/{template_id}")
def update_workflow_template(template_id: int, payload: WorkflowDefinitionIn, admin: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    template = db.get(WorkflowTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="工作流不存在")
    result = validate_graph(payload.graph)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail={"message": "工作流校验失败", "errors": result["errors"]})
    draft = db.query(WorkflowVersion).filter(WorkflowVersion.template_id == template_id, WorkflowVersion.status == "draft").order_by(WorkflowVersion.version.desc()).first()
    if not draft:
        latest = db.query(WorkflowVersion).filter(WorkflowVersion.template_id == template_id).order_by(WorkflowVersion.version.desc()).first()
        draft = WorkflowVersion(template_id=template_id, version=(latest.version if latest else 0) + 1, status="draft", created_by=admin.id)
        db.add(draft)
    template.name, template.description = payload.name, payload.description
    draft.graph_json = json.dumps(payload.graph, ensure_ascii=False)
    db.commit()
    return workflow_template_out(db, template)


@app.post("/api/workflows/{template_id}/publish")
def publish_workflow(template_id: int, admin: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    template = db.get(WorkflowTemplate, template_id)
    draft = db.query(WorkflowVersion).filter(WorkflowVersion.template_id == template_id, WorkflowVersion.status == "draft").order_by(WorkflowVersion.version.desc()).first()
    if not template:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if not draft:
        if template.is_builtin:
            published = db.query(WorkflowVersion).filter(WorkflowVersion.template_id == template_id, WorkflowVersion.status == "published").order_by(WorkflowVersion.version.desc()).first()
            draft = WorkflowVersion(template_id=template_id, version=(published.version if published else 0) + 1, status="draft", graph_json=published.graph_json if published else json.dumps(default_graph(), ensure_ascii=False), created_by=admin.id)
            db.add(draft)
            db.flush()
        else:
            raise HTTPException(status_code=409, detail="没有可发布的草稿")
    result = validate_graph(json.loads(draft.graph_json))
    if not result["ok"]:
        raise HTTPException(status_code=400, detail={"message": "工作流校验失败", "errors": result["errors"]})
    draft.status, draft.published_at = "published", datetime.now(timezone.utc)
    db.commit()
    return workflow_template_out(db, template)


@app.get("/api/workflows/{template_id}/versions")
def list_workflow_versions(template_id: int, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    return [workflow_version_out(db, item) for item in db.query(WorkflowVersion).filter(WorkflowVersion.template_id == template_id).order_by(WorkflowVersion.version.desc()).all()]


@app.post("/api/books/{book_id}/workflow/bind")
def bind_book_workflow(book_id: int, payload: WorkflowBindIn, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    book, version = db.get(Book, book_id), db.get(WorkflowVersion, payload.version_id)
    if not book or not version:
        raise HTTPException(status_code=404, detail="书籍或工作流版本不存在")
    return book_workflow_out(db, create_book_workflow_run(db, book, version))


@app.get("/api/books/{book_id}/workflow")
def get_book_workflow(book_id: int, _: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    run = db.query(BookWorkflowRun).filter(BookWorkflowRun.book_id == book_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="该书尚未绑定工作流")
    return book_workflow_out(db, run)


@app.post("/api/books/{book_id}/workflow/nodes/{node_key}/assign")
def assign_workflow_node(book_id: int, node_key: str, payload: WorkflowTaskAssignIn, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    run = db.query(BookWorkflowRun).filter(BookWorkflowRun.book_id == book_id).first()
    user = db.get(User, payload.user_id)
    node = db.query(WorkflowNodeRun).filter(WorkflowNodeRun.run_id == (run.id if run else -1), WorkflowNodeRun.node_key == node_key).first()
    if not run or not node or not user:
        raise HTTPException(status_code=404, detail="流程节点或用户不存在")
    if user.role != node.role and user.role != "admin":
        raise HTTPException(status_code=400, detail=f"该节点要求 {node.role} 角色")
    pages = db.query(BookPage).filter(BookPage.book_id == book_id, BookPage.page_no.between(payload.start_page, payload.end_page)).all()
    for page in pages:
        task = db.query(WorkflowPageTask).filter(WorkflowPageTask.node_run_id == node.id, WorkflowPageTask.page_id == page.id).first()
        if task:
            task.assignee_id = user.id
            if task.status == "blocked" and node.status in ("ready", "active"):
                task.status = "ready"
    db.commit()
    return node_run_out(db, node)


@app.post("/api/workflow-page-tasks/{task_id}/action")
def workflow_page_task_action(task_id: int, payload: WorkflowTaskActionIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    task = db.get(WorkflowPageTask, task_id)
    node = db.get(WorkflowNodeRun, task.node_run_id) if task else None
    if not task or not node:
        raise HTTPException(status_code=404, detail="流程页任务不存在")
    if user.role != "admin" and task.assignee_id != user.id:
        raise HTTPException(status_code=403, detail="该任务未分配给当前用户")
    if payload.action == "return":
        if node.role != "reviewer" and user.role != "admin":
            raise HTTPException(status_code=403, detail="只有审核节点可以打回")
        task.status, task.comment = "returned", payload.comment
        version = db.get(WorkflowVersion, db.get(BookWorkflowRun, task.run_id).workflow_version_id)
        graph = json.loads(version.graph_json)
        parent_keys = [str(edge["source"]) for edge in graph["edges"] if str(edge["target"]) == node.node_key]
        for parent_key in parent_keys:
            parent = db.query(WorkflowNodeRun).filter(WorkflowNodeRun.run_id == task.run_id, WorkflowNodeRun.node_key == parent_key).first()
            if parent and parent.role == "annotator":
                parent.status = "active"
                parent_task = db.query(WorkflowPageTask).filter(WorkflowPageTask.node_run_id == parent.id, WorkflowPageTask.page_id == task.page_id).first()
                if parent_task:
                    parent_task.status, parent_task.comment = "ready", payload.comment
    else:
        task.status = "approved" if payload.action == "approve" else "done"
        task.comment = payload.comment
    task.version += 1
    remaining = db.query(WorkflowPageTask).filter(WorkflowPageTask.node_run_id == node.id, WorkflowPageTask.status.notin_(["done", "approved", "skipped"])).count()
    if remaining == 0:
        node.status, node.completed_at = "completed", datetime.now(timezone.utc)
        refresh_workflow_run(db, db.get(BookWorkflowRun, task.run_id))
    elif node.status in ("ready", "waiting_config"):
        node.status = "active"
    db.commit()
    return {"task": node_run_out(db, node), "run": book_workflow_out(db, db.get(BookWorkflowRun, task.run_id))}


def workflow_upgrade_check(db: Session, run: BookWorkflowRun, version: WorkflowVersion) -> dict:
    if version.status != "published":
        return {"ok": False, "errors": ["目标版本尚未发布"]}
    active = db.query(WorkflowPageTask).filter(WorkflowPageTask.run_id == run.id, WorkflowPageTask.status.in_(["in_progress", "submitted"])).count()
    errors = ["存在正在编辑或等待提交的页面"] if active else []
    new_nodes = {str(item["id"]): str(item["type"]) for item in json.loads(version.graph_json)["nodes"]}
    completed = db.query(WorkflowNodeRun).filter(WorkflowNodeRun.run_id == run.id, WorkflowNodeRun.status == "completed").all()
    for item in completed:
        if item.node_key not in new_nodes or new_nodes[item.node_key] != item.node_type:
            errors.append(f"已完成节点 {item.label} 无法映射到目标版本")
    return {"ok": not errors, "errors": errors, "completed_node_keys": [item.node_key for item in completed]}


@app.post("/api/books/{book_id}/workflow/upgrade-check")
def check_book_workflow_upgrade(book_id: int, payload: WorkflowBindIn, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    run = db.query(BookWorkflowRun).filter(BookWorkflowRun.book_id == book_id).first()
    version = db.get(WorkflowVersion, payload.version_id)
    if not run or not version:
        raise HTTPException(status_code=404, detail="运行实例或目标版本不存在")
    return workflow_upgrade_check(db, run, version)


@app.post("/api/books/{book_id}/workflow/upgrade")
def upgrade_book_workflow(book_id: int, payload: WorkflowBindIn, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    run = db.query(BookWorkflowRun).filter(BookWorkflowRun.book_id == book_id).first()
    version = db.get(WorkflowVersion, payload.version_id)
    if not run or not version:
        raise HTTPException(status_code=404, detail="运行实例或目标版本不存在")
    check = workflow_upgrade_check(db, run, version)
    if not check["ok"]:
        raise HTTPException(status_code=409, detail={"message": "工作流无法升级", "errors": check["errors"]})
    graph = json.loads(version.graph_json)
    existing = {item.node_key: item for item in db.query(WorkflowNodeRun).filter(WorkflowNodeRun.run_id == run.id).all()}
    pages = db.query(BookPage).filter(BookPage.book_id == book_id).all()
    new_keys = {str(item["id"]) for item in graph["nodes"]}
    for key, item in existing.items():
        if key not in new_keys and item.status != "completed":
            item.status = "retired"
    for graph_node in graph["nodes"]:
        key = str(graph_node["id"])
        if key in existing:
            continue
        spec = NODE_TYPES[str(graph_node["type"])]
        node = WorkflowNodeRun(run_id=run.id, node_key=key, node_type=str(graph_node["type"]), label=str(graph_node.get("label") or spec["label"]), role=str(graph_node.get("role") or spec["role"]), status="blocked", total_pages=len(pages))
        db.add(node); db.flush()
        if node.node_type not in ("start", "end"):
            for page in pages:
                db.add(WorkflowPageTask(run_id=run.id, node_run_id=node.id, page_id=page.id, status="blocked"))
    run.workflow_version_id = version.id
    refresh_workflow_run(db, run)
    db.commit()
    return book_workflow_out(db, run)


def require_entity(db: Session, entity_id: int) -> EntityType:
    entity = db.get(EntityType, entity_id)
    if not entity or not entity.is_active:
        raise HTTPException(status_code=404, detail="实体不存在或已停用")
    return entity


def require_ai_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_ai_expert:
        raise HTTPException(status_code=403, detail="仅 AI专家账号可使用")
    return user


def require_entity_manager(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role == "admin" or user.is_ai_expert:
        return user
    raise HTTPException(status_code=403, detail="无权管理实体")


def require_reviewer(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role in ("admin", "reviewer"):
        return user
    raise HTTPException(status_code=403, detail="需要审核员权限")


def require_assignment_access(db: Session, assignment_id: int, user: User, for_edit: bool = False) -> PageAssignment:
    assignment = db.get(PageAssignment, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="任务页不存在")
    if user.role in ("admin", "reviewer"):
        return assignment
    if assignment.user_id != user.id:
        raise HTTPException(status_code=403, detail="不能访问其他用户任务")
    if for_edit and assignment.status in ("submitted", "approved"):
        raise HTTPException(status_code=403, detail="页面已提交或已审核，不能继续编辑")
    return assignment


def snapshot(annotation: Annotation) -> str:
    return json.dumps(annotation_out(annotation), ensure_ascii=False)


def add_revision(db: Session, annotation: Annotation, actor: User, action: str) -> None:
    db.add(
        AnnotationRevision(
            annotation_id=annotation.id,
            actor_id=actor.id,
            action=action,
            snapshot_json=snapshot(annotation),
        )
    )


def normalize_bbox(values: list[float]) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = [float(v) for v in values]
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    if right - left < 2 or bottom - top < 2:
        raise HTTPException(status_code=400, detail="标注框过小")
    return left, top, right, bottom


@app.post("/api/auth/login")
def login(payload: LoginIn, db: Annotated[Session, Depends(get_db)]) -> dict:
    user = db.query(User).filter(User.username == payload.username, User.is_active.is_(True)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"access_token": create_token(user), "token_type": "bearer", "user": user_out(user)}


@app.get("/api/me")
def me(user: Annotated[User, Depends(get_current_user)]) -> dict:
    return user_out(user)


@app.get("/api/users")
def list_users(_: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    return [user_out(item) for item in db.query(User).order_by(User.id).all()]


@app.post("/api/users")
def create_user(payload: UserIn, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="用户名已存在")
    if not payload.password:
        raise HTTPException(status_code=400, detail="新用户必须设置密码")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        display_name=payload.display_name or payload.username,
        is_active=payload.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_out(user)


@app.put("/api/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserIn,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.role = payload.role
    user.display_name = payload.display_name or payload.username
    user.is_active = payload.is_active
    if payload.password:
        user.password_hash = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return user_out(user)


@app.get("/api/pages")
def list_pages(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(get_current_user)]) -> dict:
    pages = db.query(Page).order_by(Page.page_no).all()
    return {"total": len(pages), "items": [page_out(page) for page in pages]}


@app.post("/api/pages/{page_no}/cache")
def cache_pages(page_no: int, _: Annotated[User, Depends(get_current_user)]) -> dict:
    from threading import Thread

    def _bg() -> None:
        db = SessionLocal()
        try:
            ensure_cache_window(db, page_no)
        finally:
            db.close()

    Thread(target=_bg, daemon=True).start()
    return {"ok": True}


@app.post("/api/pages/cache-all")
def cache_all_pages(_: Annotated[User, Depends(get_current_user)]) -> dict:
    return start_cache_all_pages()


@app.get("/api/pages/cache-all/status")
def get_cache_all_status(_: Annotated[User, Depends(get_current_user)]) -> dict:
    return cache_all_status()


@app.post("/api/pages/rescan")
def rescan_pages(admin: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    from .bootstrap import ensure_pages
    before = db.query(Page).count()
    ensure_pages(db)
    after = db.query(Page).count()
    return {"added": after - before, "total": after}


@app.get("/api/pages/{page_no}/image")
def page_image(page_no: int, db: Annotated[Session, Depends(get_db)]) -> FileResponse:
    page = render_page(db, page_no)
    path = Path(page.image_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="页面图片不存在")
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/api/pages/{page_no}/segments")
def list_page_segments(
    page_no: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> list[dict]:
    page = db.query(Page).filter(Page.page_no == page_no).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    segments = db.query(PageSegment).filter(PageSegment.page_id == page.page_id).order_by(PageSegment.segment_no).all()
    return [page_segment_out(item) for item in segments]


@app.post("/api/pages/{page_no}/segments/rule-cut")
def rule_cut_page_segments(
    page_no: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_ai_user)],
) -> dict:
    page = render_page(db, page_no)
    rows = cut_vertical_segments(page.image_path)
    db.query(PageSegment).filter(PageSegment.page_id == page.page_id).delete()
    segments: list[PageSegment] = []
    for row in rows:
        x1, y1, x2, y2 = row["bbox"]
        segment = PageSegment(
            page_id=page.page_id,
            segment_no=row["segment_no"],
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            rule_version=row["rule_version"],
        )
        db.add(segment)
        segments.append(segment)
    db.commit()
    for segment in segments:
        db.refresh(segment)
    return {"page_id": page.page_id, "items": [page_segment_out(item) for item in segments]}


@app.get("/api/entities")
def list_entities(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(get_current_user)]) -> list[dict]:
    return [entity_out(item) for item in db.query(EntityType).order_by(EntityType.id).all()]


@app.post("/api/entities")
def create_entity(payload: EntityIn, _: Annotated[User, Depends(require_entity_manager)], db: Annotated[Session, Depends(get_db)]) -> dict:
    entity = EntityType(**payload.model_dump())
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity_out(entity)


@app.put("/api/entities/{entity_id}")
def update_entity(
    entity_id: int,
    payload: EntityIn,
    _: Annotated[User, Depends(require_entity_manager)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    entity = db.get(EntityType, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    for key, value in payload.model_dump().items():
        setattr(entity, key, value)
    db.commit()
    db.refresh(entity)
    return entity_out(entity)


@app.get("/api/guidelines")
def list_guidelines(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(get_current_user)]) -> list[dict]:
    query = db.query(Guideline).filter(Guideline.is_active.is_(True)).order_by(Guideline.sort_order, Guideline.id)
    return [guideline_out(item) for item in query.all()]


@app.get("/api/admin/guidelines")
def list_all_guidelines(_: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    return [guideline_out(item) for item in db.query(Guideline).order_by(Guideline.sort_order, Guideline.id).all()]


@app.post("/api/guidelines")
def create_guideline(payload: GuidelineIn, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    values = payload.model_dump(exclude={"examples"})
    guideline = Guideline(**values, examples_json=json.dumps(payload.examples, ensure_ascii=False), published_at=datetime.now(timezone.utc) if payload.status == "published" else None)
    db.add(guideline)
    db.commit()
    db.refresh(guideline)
    return guideline_out(guideline)


@app.put("/api/guidelines/{guideline_id}")
def update_guideline(
    guideline_id: int,
    payload: GuidelineIn,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    guideline = db.get(Guideline, guideline_id)
    if not guideline:
        raise HTTPException(status_code=404, detail="提示不存在")
    for key, value in payload.model_dump().items():
        if key == "examples":
            guideline.examples_json = json.dumps(value, ensure_ascii=False)
        else:
            setattr(guideline, key, value)
    if payload.status == "published" and not guideline.published_at:
        guideline.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(guideline)
    return guideline_out(guideline)


@app.get("/api/annotations")
def list_annotations(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    page_id: str,
    layer: Literal["mine", "all"] = "mine",
    user_id: int | None = None,
    include_deleted: bool = False,
) -> list[dict]:
    query = db.query(Annotation).filter(Annotation.page_id == page_id)
    if not include_deleted:
        query = query.filter(Annotation.is_deleted.is_(False))
    if user.role != "admin":
        query = query.filter(Annotation.user_id == user.id)
    elif layer == "mine":
        query = query.filter(Annotation.user_id == user.id)
    elif user_id:
        query = query.filter(Annotation.user_id == user_id)
    return [annotation_out(item) for item in query.order_by(Annotation.id).all()]


@app.post("/api/annotations")
def create_annotation(
    payload: AnnotationIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_entity(db, payload.entity_id)
    page = db.query(Page).filter(Page.page_id == payload.page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    x1, y1, x2, y2 = normalize_bbox(payload.bbox)
    annotation = Annotation(
        page_id=payload.page_id,
        entity_id=payload.entity_id,
        user_id=user.id,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        note=payload.note,
        status=payload.status,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    add_revision(db, annotation, user, "create")
    db.commit()
    return annotation_out(annotation)


@app.put("/api/annotations/{annotation_id}")
def update_annotation(
    annotation_id: int,
    payload: AnnotationUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    annotation = db.get(Annotation, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="标注不存在")
    if user.role != "admin" and annotation.user_id != user.id:
        raise HTTPException(status_code=403, detail="不能修改其他用户标注")
    if annotation.status in ("approved", "rejected") and user.role != "admin":
        raise HTTPException(status_code=403, detail="已审核标注不能修改")
    add_revision(db, annotation, user, "update")
    if payload.entity_id is not None:
        require_entity(db, payload.entity_id)
        annotation.entity_id = payload.entity_id
    if payload.bbox is not None:
        annotation.x1, annotation.y1, annotation.x2, annotation.y2 = normalize_bbox(payload.bbox)
    if payload.note is not None:
        annotation.note = payload.note
    if payload.status is not None:
        annotation.status = payload.status
    if payload.is_deleted is not None:
        annotation.is_deleted = payload.is_deleted
    annotation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(annotation)
    return annotation_out(annotation)


@app.delete("/api/annotations/{annotation_id}")
def delete_annotation(
    annotation_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    annotation = db.get(Annotation, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="标注不存在")
    if user.role != "admin" and annotation.user_id != user.id:
        raise HTTPException(status_code=403, detail="不能删除其他用户标注")
    if annotation.status in ("approved", "rejected") and user.role != "admin":
        raise HTTPException(status_code=403, detail="已审核标注不能删除")
    add_revision(db, annotation, user, "delete")
    annotation.is_deleted = True
    annotation.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@app.post("/api/annotations/{annotation_id}/undo")
def undo_annotation(
    annotation_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    annotation = db.get(Annotation, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="标注不存在")
    if user.role != "admin" and annotation.user_id != user.id:
        raise HTTPException(status_code=403, detail="不能撤回其他用户标注")
    revision = (
        db.query(AnnotationRevision)
        .filter(AnnotationRevision.annotation_id == annotation_id)
        .order_by(AnnotationRevision.id.desc())
        .first()
    )
    if not revision:
        raise HTTPException(status_code=404, detail="没有可撤回记录")
    data = json.loads(revision.snapshot_json)
    annotation.entity_id = data["entity_id"]
    annotation.x1, annotation.y1, annotation.x2, annotation.y2 = normalize_bbox(data["bbox"])
    annotation.note = data.get("note", "")
    annotation.status = data.get("status", "draft")
    annotation.is_deleted = data.get("is_deleted", False)
    annotation.updated_at = datetime.now(timezone.utc)
    db.delete(revision)
    db.commit()
    db.refresh(annotation)
    return annotation_out(annotation)


def export_payload(db: Session, annotations: list[Annotation], actor: User) -> dict:
    page_ids = sorted({item.page_id for item in annotations})
    pages = db.query(Page).filter(Page.page_id.in_(page_ids)).order_by(Page.page_no).all() if page_ids else []
    entities = db.query(EntityType).order_by(EntityType.id).all()
    return {
        "meta": {
            "format": "bencao-vsr",
            "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "exported_by": user_out(actor),
            "annotation_count": len(annotations),
        },
        "pages": [page_out(page) for page in pages],
        "entities": [entity_out(entity) for entity in entities],
        "annotations": [annotation_out(item) for item in annotations],
    }


@app.get("/api/export")
def export_annotations(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    scope: Literal["mine", "all"] = "mine",
) -> FileResponse:
    query = db.query(Annotation).filter(Annotation.is_deleted.is_(False))
    if scope != "all" or user.role != "admin":
        query = query.filter(Annotation.user_id == user.id)
    annotations = query.order_by(Annotation.page_id, Annotation.id).all()
    payload = export_payload(db, annotations, user)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_path = EXPORT_DIR / f"bencao_vsr_{scope}_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("annotations.json", json.dumps(payload["annotations"], ensure_ascii=False, indent=2))
        archive.writestr("entities.json", json.dumps(payload["entities"], ensure_ascii=False, indent=2))
        archive.writestr("pages.json", json.dumps(payload["pages"], ensure_ascii=False, indent=2))
        archive.writestr("meta.json", json.dumps(payload["meta"], ensure_ascii=False, indent=2))
        archive.writestr(
            "README.txt",
            f"Bencao-VSR 标注导出\n导出时间: {payload['meta']['exported_at']}\n标注数量: {len(annotations)}\n",
        )
    return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)


def get_or_create_import_user(db: Session, username: str, user_id_hint: str) -> User:
    username = username or f"imported_{user_id_hint or 'unknown'}"
    user = db.query(User).filter(User.username == username).first()
    if user:
        return user
    user = User(
        username=username,
        password_hash=hash_password("imported-disabled"),
        role="annotator",
        display_name=username,
        is_active=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/import")
def import_annotations(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
) -> dict:
    target = IMPORT_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    batch = ImportBatch(filename=target.name, imported_by=admin.id, status="pending")
    db.add(batch)
    db.commit()
    db.refresh(batch)
    imported = 0
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(target) as archive:
            archive.extractall(tmp)
        annotations_file = Path(tmp) / "annotations.json"
        if not annotations_file.exists():
            raise HTTPException(status_code=400, detail="压缩包缺少 annotations.json")
        rows = json.loads(annotations_file.read_text(encoding="utf-8"))
        for row in rows:
            entity_name = row.get("entity_name") or "Imported"
            entity = db.query(EntityType).filter(EntityType.name == entity_name).first()
            if not entity:
                entity = EntityType(name=entity_name, color=row.get("color") or "#2563eb", is_active=True)
                db.add(entity)
                db.commit()
                db.refresh(entity)
            source_user = get_or_create_import_user(db, row.get("username", ""), str(row.get("user_id", "")))
            x1, y1, x2, y2 = normalize_bbox(row["bbox"])
            db.add(
                Annotation(
                    page_id=row["page_id"],
                    entity_id=entity.id,
                    user_id=source_user.id,
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    note=row.get("note", ""),
                    status="pending",
                    import_batch_id=batch.id,
                )
            )
            imported += 1
    batch.status = "pending"
    db.commit()
    return {"batch_id": batch.id, "imported": imported}


@app.post("/api/annotations/{annotation_id}/review")
def review_annotation(
    annotation_id: int,
    payload: ReviewIn,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    annotation = db.get(Annotation, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="标注不存在")
    add_revision(db, annotation, admin, "review")
    annotation.status = payload.status
    annotation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(annotation)
    return annotation_out(annotation)


@app.post("/api/annotations/{annotation_id}/ocr")
def ocr_annotation(
    annotation_id: int,
    user: Annotated[User, Depends(require_ai_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    annotation = db.get(Annotation, annotation_id)
    if not annotation or annotation.is_deleted:
        raise HTTPException(status_code=404, detail="标注不存在")
    page = db.query(Page).filter(Page.page_id == annotation.page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    page = render_page(db, page.page_no)
    text = recognize_crop(page.image_path, [annotation.x1, annotation.y1, annotation.x2, annotation.y2])
    add_revision(db, annotation, user, "ocr")
    annotation.note = f"{annotation.note}\n{text}".strip() if annotation.note else text
    annotation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(annotation)
    return annotation_out(annotation)


DEFAULT_BOOK_ENTITIES = [
    ("C1", "《神农本经》", "#2563eb", "神农本经来源层"),
    ("C2", "名医增补 / 陶弘景注系统", "#16a34a", "名医别录、陶弘景相关层"),
    ("C3", "唐显庆新增，唐本先附", "#f97316", "唐本新增层"),
    ("C4", "五代蜀本新增，韩保升系统", "#9333ea", "蜀本、韩保升相关层"),
    ("C5", "宋开宝新增，今附", "#dc2626", "开宝新增、今附层"),
    ("C6", "宋嘉祐新补，新补", "#0891b2", "嘉祐新补层"),
    ("C7", "宋嘉祐新定，新定", "#4f46e5", "嘉祐新定层"),
    ("C8", "宋政和重修层 / 图经相关层", "#65a30d", "政和、图经相关层"),
    ("C9", "金代寇宗奭《本草衍义》层", "#be123c", "本草衍义层"),
    ("C10", "唐慎微续添 / 晦明轩标记层，墨盖子", "#111827", "续添和墨盖标记层"),
]

DEFAULT_LABELS = [
    ("region", "TEXT", "文字区", "#2563eb"), ("region", "IMAGE", "图片区", "#f97316"),
    ("region", "TABLE", "表格", "#7c3aed"), ("region", "SEAL", "印章", "#dc2626"),
    ("region", "EMBLEM", "校徽", "#be123c"), ("region", "HEADER", "题头", "#0891b2"),
    ("region", "MARGIN", "边批", "#65a30d"),
    ("layout", "COLUMN", "正文栏", "#2563eb"), ("layout", "DOUBLE_NOTE", "双行小注", "#7c3aed"),
    ("layout", "TITLE", "标题", "#f97316"), ("layout", "COMMENTARY", "注文", "#16a34a"),
    ("layout", "SPANNING", "跨栏", "#0891b2"),
    *[("stratum", code, name, color) for code, name, color, _ in DEFAULT_BOOK_ENTITIES],
]


def book_dir(book_id: int) -> Path:
    path = DATA_DIR / "books" / str(book_id)
    path.mkdir(parents=True, exist_ok=True)
    (path / "pages").mkdir(parents=True, exist_ok=True)
    return path


def ensure_default_book_entities(db: Session, book: Book) -> None:
    if db.query(BookEntity).filter(BookEntity.book_id == book.id).count():
        return
    for code, name, color, description in DEFAULT_BOOK_ENTITIES:
        db.add(BookEntity(book_id=book.id, code=code, name=name, color=color, description=description, is_active=True))
    db.commit()


def ensure_default_labels(db: Session, book: Book) -> None:
    if db.query(LabelDefinition).filter(LabelDefinition.book_id == book.id).count():
        return
    for order, (group, code, name, color) in enumerate(DEFAULT_LABELS, 1):
        db.add(LabelDefinition(book_id=book.id, group=group, code=code, name=name, color=color, sort_order=order, is_active=True))
    db.commit()


def render_uploaded_pdf_pages(db: Session, book: Book) -> None:
    doc = fitz.open(book.pdf_path)
    try:
        out_dir = book_dir(book.id) / "pages"
        book.page_count = doc.page_count
        book.status = "processing"
        db.commit()
        for index in range(doc.page_count):
            page_no = index + 1
            page = doc.load_page(index)
            matrix = fitz.Matrix(settings.render_dpi / 72, settings.render_dpi / 72)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image_path = out_dir / f"page_{page_no:04d}.png"
            pixmap.save(str(image_path))
            existing = db.query(BookPage).filter(BookPage.book_id == book.id, BookPage.page_no == page_no).first()
            width, height = pixmap.width, pixmap.height
            if existing:
                existing.width = width
                existing.height = height
                existing.image_path = str(image_path)
            else:
                db.add(
                    BookPage(
                        book_id=book.id,
                        page_no=page_no,
                        page_id=f"book_{book.id}_page_{page_no:04d}",
                        width=width,
                        height=height,
                        dpi=settings.render_dpi,
                        image_path=str(image_path),
                    )
                )
            db.commit()
        book.status = "ready"
        db.commit()
    finally:
        doc.close()


def process_uploaded_book(book_id: int, upload_key: tuple[str, int]) -> None:
    with BOOK_RENDER_LOCK:
        db = SessionLocal()
        try:
            book = db.get(Book, book_id)
            if not book:
                return
            render_uploaded_pdf_pages(db, book)
            builtin = db.query(WorkflowTemplate).filter(WorkflowTemplate.is_builtin.is_(True)).first()
            builtin_version = (
                db.query(WorkflowVersion)
                .filter(WorkflowVersion.template_id == builtin.id, WorkflowVersion.status == "published")
                .order_by(WorkflowVersion.version.desc())
                .first()
                if builtin
                else None
            )
            if builtin_version and not db.query(BookWorkflowRun).filter(BookWorkflowRun.book_id == book.id).first():
                create_book_workflow_run(db, book, builtin_version)
        except Exception:
            db.rollback()
            book = db.get(Book, book_id)
            if book:
                book.status = "failed"
                db.commit()
        finally:
            db.close()
            with ACTIVE_UPLOADS_LOCK:
                ACTIVE_UPLOADS.discard(upload_key)


def seed_assignment_from_recognition(db: Session, assignment: PageAssignment, result: dict | None = None) -> None:
    if db.query(LayoutRegion).filter(LayoutRegion.assignment_id == assignment.id).count():
        return
    page = db.get(BookPage, assignment.page_id)
    if not page:
        return
    if result is None:
        return
    line_by_order: dict[int, TextLine] = {}
    region_by_order: dict[int, LayoutRegion] = {}
    for row in result.get("regions", []):
        x1, y1, x2, y2 = normalize_bbox(row["bbox"])
        region = LayoutRegion(
                assignment_id=assignment.id,
                region_type=row.get("region_type", "text"),
                order_no=int(row.get("order_no", 1)),
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                confirmed=bool(row.get("confirmed", False)),
            )
        db.add(region)
        db.flush()
        region_by_order[int(row.get("order_no", 1))] = region
    db.flush()
    for row in result.get("lines", []):
        x1, y1, x2, y2 = normalize_bbox(row["bbox"])
        line = TextLine(
            assignment_id=assignment.id,
            region_id=region_by_order.get(int(row.get("region_order_no", 0))).id if region_by_order.get(int(row.get("region_order_no", 0))) else None,
            order_no=int(row.get("order_no", 1)),
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            char_size=float(row.get("char_size", 0)),
            confirmed=bool(row.get("confirmed", False)),
            needs_char_split=bool(row.get("needs_char_split", False)),
            ocr_text=str(row.get("ocr_text", "")),
        )
        db.add(line)
        db.flush()
        line_by_order[line.order_no] = line
    for row in result.get("chars", []):
        x1, y1, x2, y2 = normalize_bbox(row["bbox"])
        line = line_by_order.get(int(row.get("line_order_no", 0)))
        db.add(
            TextChar(
                assignment_id=assignment.id,
                line_id=line.id if line else None,
                order_no=int(row.get("order_no", 1)),
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                raw_text=row.get("raw_text", ""),
                corrected_text=row.get("corrected_text", row.get("raw_text", "")),
                candidates_json=json.dumps(row.get("candidates", []), ensure_ascii=False),
                confidence=float(row.get("confidence", 0)),
                status=row.get("status", "unchecked"),
            )
        )
    assignment.status = "in_progress" if assignment.status == "assigned" else assignment.status
    db.commit()


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_cloud_ocr_batch(job_id: int) -> None:
    db = SessionLocal()
    try:
        batch = db.get(RecognitionJob, job_id)
        if not batch:
            return
        batch.status = "running"
        platform_job = next((item for item in db.query(PlatformJob).filter(PlatformJob.job_type.in_(["batch_ocr", "page_preprocess"])).all() if json.loads(item.payload_json or "{}").get("recognition_job_id") == job_id), None)
        if platform_job:
            platform_job.status, platform_job.started_at, platform_job.progress = "running", datetime.now(timezone.utc), 0
            platform_job.result_json = json.dumps({"stage": "排队完成，开始处理", "logs": [f"批次 #{job_id} 开始 · 共 {batch.total_pages} 页"]}, ensure_ascii=False)
        db.commit()
        page_jobs = db.query(OcrPageJob).filter(OcrPageJob.batch_id == job_id).order_by(OcrPageJob.id).all()
        raw_dir = DATA_DIR / "ocr_raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        ocr_config = effective_ocr_config(db)

        def make_reporter(base_percent: int, span_percent: int, page_no: int):
            def report(stage: str, percent: int) -> None:
                if not platform_job:
                    return
                payload = json.loads(platform_job.result_json or "{}")
                logs = payload.get("logs", [])
                logs.append(f"[第 {page_no} 页] {stage}")
                payload.update({"stage": stage, "logs": logs[-200:]})
                platform_job.result_json = json.dumps(payload, ensure_ascii=False)
                platform_job.progress = max(platform_job.progress or 0, min(99, base_percent + int(span_percent * percent / 100)))
                db.commit()
            return report

        for index, page_job in enumerate(page_jobs, 1):
            db.refresh(batch)
            if batch.status == "cancelled":
                return
            page = db.get(BookPage, page_job.page_id)
            if not page:
                page_job.status, page_job.error = "failed", "页面不存在"
                db.commit()
                continue
            base, span = (index - 1) * 100 // max(len(page_jobs), 1), 100 // max(len(page_jobs), 1)
            try:
                cached = db.query(OcrPageJob).filter(
                    OcrPageJob.id != page_job.id,
                    OcrPageJob.image_sha256 == page_job.image_sha256,
                    OcrPageJob.params_hash == page_job.params_hash,
                    OcrPageJob.status.in_(["done", "cached"]),
                ).order_by(OcrPageJob.id.desc()).first()
                if cached and cached.raw_path and Path(cached.raw_path).exists():
                    normalized = json.loads(Path(cached.raw_path).read_text(encoding="utf-8"))
                    page_job.status = "cached"
                    page_job.raw_path = cached.raw_path
                else:
                    page_job.status = "running"
                    db.commit()
                    last_error: Exception | None = None
                    for attempt in range(1, 6):
                        page_job.attempts += 1
                        db.commit()
                        try:
                            normalized = preprocess_page(page.image_path, config=ocr_config, progress=make_reporter(base, span, page.page_no))
                            last_error = None
                            break
                        except Exception as exc:
                            last_error = exc
                            page_job.error = str(exc)
                            db.commit()
                            message = str(exc).lower()
                            transient = any(token in message for token in ("429", "rate", "timeout", "tempor", "502", "503", "504", "bad gateway", "限流", "超时", "队列", "queue", "10010", "稍后重试"))
                            if not transient or attempt == 5:
                                raise
                            time.sleep(min(90, 20 * attempt))
                    if last_error is not None:
                        raise last_error
                    raw_path = raw_dir / f"book_{page.book_id}_page_{page.page_no:04d}_{page_job.image_sha256[:12]}.json"
                    raw_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
                    page_job.raw_path = str(raw_path)
                    page_job.provider_job_id = "pipeline"
                    page_job.status = "done"
                # 单页预处理是“预览”动作：只生成新的 raw 结果；用户点击“保存”后才写入标注任务。
                # 批量预处理保持原行为，完成后直接播种任务。
                if not platform_job or platform_job.job_type != "page_preprocess":
                    assignments = db.query(PageAssignment).filter(PageAssignment.page_id == page.id).all()
                    for assignment in assignments:
                        seed_assignment_from_recognition(db, assignment, normalized)
                page.recognition_status = page_job.status
            except Exception as exc:
                page_job.status = "failed"
                page_job.error = str(exc)
                page.recognition_status = "failed"
            batch.current_page = index
            if platform_job:
                platform_job.progress = round(index / max(len(page_jobs), 1) * 100)
            db.commit()
        failed = db.query(OcrPageJob).filter(OcrPageJob.batch_id == job_id, OcrPageJob.status == "failed").count()
        batch.status = "partial" if failed else "done"
        batch.error = f"{failed} 页失败" if failed else ""
        if platform_job:
            platform_job.status = "failed" if failed == len(page_jobs) else "succeeded"
            platform_job.progress = 100
            platform_job.error = batch.error
            payload = json.loads(platform_job.result_json or "{}")
            payload.update({"recognition_job_id": batch.id, "pages": len(page_jobs), "failed": failed})
            payload["logs"] = payload.get("logs", [])[-200:] + [f"完成：{len(page_jobs) - failed}/{len(page_jobs)} 页成功"]
            platform_job.result_json = json.dumps(payload, ensure_ascii=False)
            platform_job.completed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


@app.get("/api/books")
def list_books(_: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    return [book_out(item) for item in db.query(Book).order_by(Book.id.desc()).all()]


@app.post("/api/books")
def create_book(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    title: str = Form(""),
    task_prompt: str = Form(""),
) -> dict:
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只支持上传 PDF")
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size <= 0:
        raise HTTPException(status_code=400, detail="PDF 文件为空")
    upload_key = (Path(filename).name.lower(), file_size)
    with ACTIVE_UPLOADS_LOCK:
        if upload_key in ACTIVE_UPLOADS:
            raise HTTPException(status_code=409, detail="同一 PDF 正在上传或生成页面，请勿重复提交")
        ACTIVE_UPLOADS.add(upload_key)
    book = Book(title=title.strip() or Path(filename).stem, task_prompt=task_prompt, status="uploading", created_by=admin.id)
    db.add(book)
    db.commit()
    db.refresh(book)
    try:
        pdf_path = book_dir(book.id) / "source.pdf"
        with pdf_path.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
        with fitz.open(pdf_path) as document:
            book.page_count = document.page_count
        book.pdf_path = str(pdf_path)
        book.status = "processing"
        db.commit()
        ensure_default_book_entities(db, book)
        ensure_default_labels(db, book)
        result = book_out(book)
        Thread(target=process_uploaded_book, args=(book.id, upload_key), daemon=True).start()
        return result
    except Exception:
        db.rollback()
        book.status = "failed"
        db.commit()
        with ACTIVE_UPLOADS_LOCK:
            ACTIVE_UPLOADS.discard(upload_key)
        raise


@app.put("/api/books/{book_id}")
def update_book(book_id: int, payload: BookUpdateIn, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    book = db.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    book.title = payload.title
    book.task_prompt = payload.task_prompt
    book.status = payload.status
    book.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(book)
    return book_out(book)


@app.delete("/api/books/{book_id}")
def delete_book(book_id: int, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    """硬删除书籍：级联清理页面、任务、标注、语义、图谱数据与磁盘文件，不可恢复。"""
    book = db.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    with ACTIVE_UPLOADS_LOCK:
        if any(key[1] == book_id for key in ACTIVE_UPLOADS):
            raise HTTPException(status_code=409, detail="书籍正在上传或渲染页面，请等待完成后再删除")
    running = db.query(RecognitionJob).filter(
        RecognitionJob.book_id == book_id, RecognitionJob.status.in_(["pending", "running"])
    ).first()
    if running:
        raise HTTPException(status_code=409, detail=f"识别批次 #{running.id} 正在运行，请先取消或等待完成")

    assignment_ids = [row.id for row in db.query(PageAssignment.id).filter(PageAssignment.book_id == book_id)]
    page_ids = [row.id for row in db.query(BookPage.id).filter(BookPage.book_id == book_id)]
    unit_ids = [row.id for row in db.query(TextUnit.id).filter(TextUnit.book_id == book_id)]
    batch_ids = [row.id for row in db.query(RecognitionJob.id).filter(RecognitionJob.book_id == book_id)]
    run_ids = [row.id for row in db.query(BookWorkflowRun.id).filter(BookWorkflowRun.book_id == book_id)]
    glyph_paths = [row.glyph_path for row in db.query(CharacterEntry).filter(CharacterEntry.book_id == book_id) if row.glyph_path]

    if assignment_ids:
        db.query(TextChar).filter(TextChar.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
        db.query(TextLine).filter(TextLine.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
        db.query(LayoutRegion).filter(LayoutRegion.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
        db.query(EntityAnnotation).filter(EntityAnnotation.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
        db.query(ReviewRecord).filter(ReviewRecord.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
        db.query(WorkflowRevision).filter(WorkflowRevision.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
        db.query(SemanticEntity).filter(SemanticEntity.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
        db.query(SemanticRelation).filter(SemanticRelation.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
        db.query(MedicalCase).filter(MedicalCase.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
        db.query(AdjudicationRecord).filter(AdjudicationRecord.assignment_a_id.in_(assignment_ids) | AdjudicationRecord.assignment_b_id.in_(assignment_ids)).delete(synchronize_session=False)
        db.query(PageAssignment).filter(PageAssignment.id.in_(assignment_ids)).delete(synchronize_session=False)
    if unit_ids:
        db.query(SemanticEntity).filter(SemanticEntity.text_unit_id.in_(unit_ids)).delete(synchronize_session=False)
        db.query(SemanticRelation).filter(SemanticRelation.text_unit_id.in_(unit_ids)).delete(synchronize_session=False)
        db.query(MedicalCase).filter(MedicalCase.text_unit_id.in_(unit_ids)).delete(synchronize_session=False)
        db.query(TextUnit).filter(TextUnit.parent_id.in_(unit_ids)).delete(synchronize_session=False)
        db.query(TextUnit).filter(TextUnit.id.in_(unit_ids)).delete(synchronize_session=False)
    if batch_ids:
        db.query(OcrPageJob).filter(OcrPageJob.batch_id.in_(batch_ids)).delete(synchronize_session=False)
    if page_ids:
        db.query(OcrPageJob).filter(OcrPageJob.page_id.in_(page_ids)).delete(synchronize_session=False)
        db.query(WorkflowPageTask).filter(WorkflowPageTask.page_id.in_(page_ids)).delete(synchronize_session=False)
    db.query(RecognitionJob).filter(RecognitionJob.book_id == book_id).delete(synchronize_session=False)
    if run_ids:
        node_ids = [row.id for row in db.query(WorkflowNodeRun.id).filter(WorkflowNodeRun.run_id.in_(run_ids))]
        if node_ids:
            db.query(WorkflowPageTask).filter(WorkflowPageTask.node_run_id.in_(node_ids)).delete(synchronize_session=False)
            db.query(WorkflowNodeRun).filter(WorkflowNodeRun.id.in_(node_ids)).delete(synchronize_session=False)
        db.query(BookWorkflowRun).filter(BookWorkflowRun.id.in_(run_ids)).delete(synchronize_session=False)
    db.query(AdjudicationRecord).filter(AdjudicationRecord.book_id == book_id).delete(synchronize_session=False)
    db.query(PlatformJob).filter(PlatformJob.book_id == book_id).delete(synchronize_session=False)
    db.query(CharacterEntry).filter(CharacterEntry.book_id == book_id).delete(synchronize_session=False)
    db.query(BookPage).filter(BookPage.book_id == book_id).delete(synchronize_session=False)
    db.query(BookEntity).filter(BookEntity.book_id == book_id).delete(synchronize_session=False)
    db.query(LabelDefinition).filter(LabelDefinition.book_id == book_id).delete(synchronize_session=False)
    db.query(OntologyType).filter(OntologyType.book_id == book_id).delete(synchronize_session=False)
    db.query(GraphEdge).filter(GraphEdge.book_id == book_id).delete(synchronize_session=False)
    db.query(GraphNode).filter(GraphNode.book_id == book_id).delete(synchronize_session=False)
    db.delete(book)
    db.commit()

    shutil.rmtree(DATA_DIR / "books" / str(book_id), ignore_errors=True)
    raw_dir = DATA_DIR / "ocr_raw"
    if raw_dir.exists():
        for raw_file in raw_dir.glob(f"book_{book_id}_*"):
            raw_file.unlink(missing_ok=True)
    for glyph in glyph_paths:
        Path(glyph).unlink(missing_ok=True)
    return {"ok": True, "deleted": book_id}


@app.get("/api/books/{book_id}/pages")
def list_book_pages(book_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    query = db.query(BookPage).filter(BookPage.book_id == book_id)
    if user.role == "annotator":
        assigned_page_ids = db.query(PageAssignment.page_id).filter(PageAssignment.book_id == book_id, PageAssignment.user_id == user.id)
        query = query.filter(BookPage.id.in_(assigned_page_ids))
    return [book_page_out(item) for item in query.order_by(BookPage.page_no).all()]


@app.get("/api/book-pages/{page_id}/image")
def book_page_image(page_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> FileResponse:
    page = db.get(BookPage, page_id)
    if not page or not Path(page.image_path).exists():
        raise HTTPException(status_code=404, detail="页面图片不存在")
    if user.role == "annotator":
        allowed = db.query(PageAssignment.id).filter(PageAssignment.page_id == page_id, PageAssignment.user_id == user.id).first()
        if not allowed:
            raise HTTPException(status_code=403, detail="该页面未分配给当前用户")
    return FileResponse(page.image_path, media_type="image/png", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@app.get("/api/books/{book_id}/entities")
def list_book_entities(book_id: int, _: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    book = db.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    ensure_default_book_entities(db, book)
    return [book_entity_out(item) for item in db.query(BookEntity).filter(BookEntity.book_id == book_id).order_by(BookEntity.id).all()]


@app.put("/api/books/{book_id}/entities")
def save_book_entities(
    book_id: int,
    payload: list[BookEntityIn],
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict]:
    if not db.get(Book, book_id):
        raise HTTPException(status_code=404, detail="书籍不存在")
    saved: list[BookEntity] = []
    for row in payload:
        entity = db.get(BookEntity, row.id) if row.id else None
        if entity and entity.book_id != book_id:
            raise HTTPException(status_code=400, detail="实体不属于当前书籍")
        if not entity:
            entity = BookEntity(book_id=book_id, code=row.code, name=row.name, color=row.color)
            db.add(entity)
        entity.code = row.code
        entity.name = row.name
        entity.color = row.color
        entity.description = row.description
        entity.is_active = row.is_active
        saved.append(entity)
    db.commit()
    return [book_entity_out(item) for item in saved]


@app.get("/api/books/{book_id}/labels")
def list_book_labels(book_id: int, _: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    book = db.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    ensure_default_labels(db, book)
    rows = db.query(LabelDefinition).filter(LabelDefinition.book_id == book_id).order_by(LabelDefinition.group, LabelDefinition.sort_order, LabelDefinition.id).all()
    return [label_definition_out(item) for item in rows]


@app.put("/api/books/{book_id}/labels")
def save_book_labels(book_id: int, payload: list[LabelDefinitionIn], _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    if not db.get(Book, book_id):
        raise HTTPException(status_code=404, detail="书籍不存在")
    saved: list[LabelDefinition] = []
    for row in payload:
        item = db.get(LabelDefinition, row.id) if row.id else None
        if item and item.book_id != book_id:
            raise HTTPException(status_code=400, detail="标签不属于当前书籍")
        duplicate = db.query(LabelDefinition).filter(LabelDefinition.book_id == book_id, LabelDefinition.group == row.group, LabelDefinition.code == row.code).first()
        if duplicate and duplicate.id != row.id:
            raise HTTPException(status_code=409, detail=f"标签代码已存在: {row.group}/{row.code}")
        if not item:
            item = LabelDefinition(book_id=book_id)
            db.add(item)
        for key, value in row.model_dump(exclude={"id"}).items():
            setattr(item, key, value)
        saved.append(item)
    db.commit()
    return [label_definition_out(item) for item in saved]


@app.post("/api/books/{book_id}/assignments")
def save_assignments(
    book_id: int,
    payload: AssignmentRangesIn,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    book = db.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    created = 0
    replaced_pages: set[int] = set()
    for item in payload.items:
        if item.end_page < item.start_page:
            raise HTTPException(status_code=400, detail="结束页不能小于开始页")
        user = db.get(User, item.user_id)
        if not user or user.role != "annotator":
            raise HTTPException(status_code=400, detail="只能分配给标注员")
        pages = db.query(BookPage).filter(BookPage.book_id == book_id, BookPage.page_no >= item.start_page, BookPage.page_no <= item.end_page).all()
        for page in pages:
            if page.id in replaced_pages:
                continue
            existing = db.query(PageAssignment).filter(PageAssignment.page_id == page.id).first()
            if existing:
                raise HTTPException(status_code=409, detail=f"第 {page.page_no} 页已分配给 {existing.user.username if existing.user else existing.user_id}")
            db.add(PageAssignment(book_id=book_id, page_id=page.id, user_id=user.id, status="assigned"))
            run = db.query(BookWorkflowRun).filter(BookWorkflowRun.book_id == book_id).first()
            if run:
                annotator_nodes = db.query(WorkflowNodeRun.id).filter(WorkflowNodeRun.run_id == run.id, WorkflowNodeRun.role == "annotator")
                for task in db.query(WorkflowPageTask).filter(WorkflowPageTask.page_id == page.id, WorkflowPageTask.node_run_id.in_(annotator_nodes)).all():
                    task.assignee_id = user.id
            replaced_pages.add(page.id)
            created += 1
    db.commit()
    return {"assigned": created}


@app.get("/api/books/{book_id}/assignments")
def list_book_assignments(book_id: int, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    rows = db.query(PageAssignment).join(BookPage, PageAssignment.page_id == BookPage.id).filter(PageAssignment.book_id == book_id).order_by(BookPage.page_no).all()
    return [assignment_out(item) for item in rows]


@app.post("/api/books/{book_id}/recognize/start")
def start_book_recognition(book_id: int, payload: OcrBatchIn, admin: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    book = db.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    if payload.end_page < payload.start_page:
        raise HTTPException(status_code=400, detail="结束页不能小于开始页")
    pages = db.query(BookPage).filter(BookPage.book_id == book_id, BookPage.page_no >= payload.start_page, BookPage.page_no <= payload.end_page).order_by(BookPage.page_no).all()
    if not pages:
        raise HTTPException(status_code=400, detail="页码范围内没有页面")
    ocr_config = effective_ocr_config(db)
    if not ocr_config["access_token"]:
        raise HTTPException(status_code=409, detail="尚未配置 OCR 模型密钥，请先前往系统设置完成配置")
    job = RecognitionJob(book_id=book_id, status="pending", total_pages=len(pages))
    db.add(job)
    db.commit()
    db.refresh(job)
    platform_job = PlatformJob(job_type="batch_ocr", book_id=book_id, created_by=admin.id, status="queued", progress=0,
                               model=str(ocr_config["model"]), payload_json=json.dumps({"recognition_job_id": job.id, "start_page": payload.start_page, "end_page": payload.end_page}),
                               result_json=json.dumps({"stage": "已发起", "logs": [f"批量预处理：第 {payload.start_page}-{payload.end_page} 页"]}, ensure_ascii=False))
    db.add(platform_job)
    params_hash = hashlib.sha256(f'{ocr_config["model"]}|layout=1|seal=1|temperature=0|pipe=11'.encode()).hexdigest()
    for page in pages:
        db.add(OcrPageJob(batch_id=job.id, page_id=page.id, image_sha256=_file_sha256(page.image_path), model=ocr_config["model"], params_hash=params_hash))
        page.recognition_status = "queued"
    db.commit()
    db.refresh(platform_job)
    Thread(target=run_cloud_ocr_batch, args=(job.id,), daemon=True).start()
    return {**recognition_job_out(job), "platform_job_id": platform_job.id}


@app.get("/api/books/{book_id}/recognize/status")
def book_recognition_status(book_id: int, _: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    job = db.query(RecognitionJob).filter(RecognitionJob.book_id == book_id).order_by(RecognitionJob.id.desc()).first()
    if not job:
        return {"status": "idle", "book_id": book_id, "current_page": 0, "total_pages": 0, "error": ""}
    result = recognition_job_out(job)
    page_numbers = {row.id: row.page_no for row in db.query(BookPage.id, BookPage.page_no).filter(BookPage.book_id == book_id)}
    result["pages"] = [{**ocr_page_job_out(item), "page_no": page_numbers.get(item.page_id)} for item in db.query(OcrPageJob).filter(OcrPageJob.batch_id == job.id).order_by(OcrPageJob.id).all()]
    return result


@app.get("/api/book-pages/{page_id}/recognition-latest")
def page_recognition_latest(page_id: int, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    """管理员预处理预览：返回某页最近一次成功识别的归一化结果（区域/列/字）。"""
    page = db.get(BookPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    job_row = (
        db.query(OcrPageJob)
        .filter(OcrPageJob.page_id == page_id, OcrPageJob.status.in_(["done", "cached"]), OcrPageJob.raw_path.isnot(None), OcrPageJob.raw_path != "")
        .order_by(OcrPageJob.id.desc())
        .first()
    )
    if not job_row or not Path(job_row.raw_path).exists():
        raise HTTPException(status_code=404, detail="该页尚无识别结果，请先在书籍处理台发起批量预处理")
    result = json.loads(Path(job_row.raw_path).read_text(encoding="utf-8"))
    return {"job": ocr_page_job_out(job_row), "result": result}


@app.post("/api/book-pages/{page_id}/preprocess")
def preprocess_single_page(page_id: int, admin: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    """预处理预览页"处理当前页"：真实重跑并只更新预览，既有标注在点击保存前不变。"""
    page = db.get(BookPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    ocr_config = effective_ocr_config(db)
    if not ocr_config["access_token"]:
        raise HTTPException(status_code=409, detail="尚未配置 OCR 模型密钥，请先前往系统设置完成配置")
    job = RecognitionJob(book_id=page.book_id, status="pending", total_pages=1)
    db.add(job)
    db.commit()
    db.refresh(job)
    # 追加 |force 使 params_hash 不同于常规批次，绕过 sha+params 去重缓存，保证真实重跑
    params_hash = hashlib.sha256(f'{ocr_config["model"]}|layout=1|seal=1|temperature=0|pipe=11|force'.encode()).hexdigest()
    db.add(OcrPageJob(batch_id=job.id, page_id=page.id, image_sha256=_file_sha256(page.image_path), model=ocr_config["model"], params_hash=params_hash))
    page.recognition_status = "queued"
    platform_job = PlatformJob(job_type="page_preprocess", book_id=page.book_id, page_id=page.id, created_by=admin.id, status="queued", progress=0,
                               model=str(ocr_config["model"]), payload_json=json.dumps({"recognition_job_id": job.id, "page_no": page.page_no}, ensure_ascii=False),
                               result_json=json.dumps({"stage": "已发起", "logs": [f"单页预处理：第 {page.page_no} 页"]}, ensure_ascii=False))
    db.add(platform_job)
    db.commit()
    db.refresh(platform_job)
    Thread(target=run_cloud_ocr_batch, args=(job.id,), daemon=True).start()
    return {"ok": True, "recognition_job_id": job.id, "platform_job_id": platform_job.id}


@app.delete("/api/book-pages/{page_id}/recognition")
def clear_page_recognition(page_id: int, admin: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    """预处理预览页"清空痕迹"：清除该页标注任务的区域/列/字、识别原文与任务记录（语义数据不动）。"""
    page = db.get(BookPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    counts = {"assignments": 0, "regions": 0, "lines": 0, "chars": 0, "raw_files": 0, "jobs": 0}
    for assignment in db.query(PageAssignment).filter(PageAssignment.page_id == page_id).all():
        counts["assignments"] += 1
        counts["chars"] += db.query(TextChar).filter(TextChar.assignment_id == assignment.id).delete()
        counts["lines"] += db.query(TextLine).filter(TextLine.assignment_id == assignment.id).delete()
        counts["regions"] += db.query(LayoutRegion).filter(LayoutRegion.assignment_id == assignment.id).delete()
        assignment.status = "assigned" if assignment.status in ("in_progress", "returned") else assignment.status
        assignment.current_step = 1
        assignment.version += 1
        assignment.updated_at = datetime.now(timezone.utc)
        db.add(WorkflowRevision(assignment_id=assignment.id, version=assignment.version, actor_id=admin.id, action="clear_recognition", snapshot_json="{}"))
    batch_ids: set[int] = set()
    for job_row in db.query(OcrPageJob).filter(OcrPageJob.page_id == page_id).all():
        if job_row.raw_path and Path(job_row.raw_path).exists():
            Path(job_row.raw_path).unlink(missing_ok=True)
            counts["raw_files"] += 1
        batch_ids.add(job_row.batch_id)
        db.delete(job_row)
        counts["jobs"] += 1
    db.flush()
    for batch_id in batch_ids:  # 页级任务清空后，空批次标记取消
        if not db.query(OcrPageJob).filter(OcrPageJob.batch_id == batch_id).count():
            batch = db.get(RecognitionJob, batch_id)
            if batch and batch.status in ("pending", "running"):
                batch.status = "cancelled"
    page.recognition_status = "pending"
    db.commit()
    return {"ok": True, **counts}


@app.post("/api/book-pages/{page_id}/apply-recognition")
def apply_page_recognition(page_id: int, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    """预处理预览页"保存"：把最近一次识别结果写入该页所有标注任务（无数据播种/有数据覆盖）。"""
    page = db.get(BookPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    job_row = (
        db.query(OcrPageJob)
        .filter(OcrPageJob.page_id == page_id, OcrPageJob.status.in_(["done", "cached"]), OcrPageJob.raw_path.isnot(None), OcrPageJob.raw_path != "")
        .order_by(OcrPageJob.id.desc())
        .first()
    )
    if not job_row or not Path(job_row.raw_path).exists():
        raise HTTPException(status_code=409, detail="该页尚无识别结果，请先点击“处理当前页”")
    result = json.loads(Path(job_row.raw_path).read_text(encoding="utf-8"))
    assignments = db.query(PageAssignment).filter(PageAssignment.page_id == page_id).all()
    if not assignments:
        raise HTTPException(status_code=409, detail="该页尚未分配标注任务，请先在书籍处理台的工作流标签发布任务")
    replaced = 0
    for assignment in assignments:
        if db.query(LayoutRegion).filter(LayoutRegion.assignment_id == assignment.id).count():
            db.query(TextChar).filter(TextChar.assignment_id == assignment.id).delete()
            db.query(TextLine).filter(TextLine.assignment_id == assignment.id).delete()
            db.query(LayoutRegion).filter(LayoutRegion.assignment_id == assignment.id).delete()
            db.flush()
            replaced += 1
        seed_assignment_from_recognition(db, assignment, result)
    return {"ok": True, "applied": len(assignments), "replaced": replaced, "lines": len(result.get("lines", [])), "chars": len(result.get("chars", []))}


@app.post("/api/recognition-jobs/{job_id}/cancel")
def cancel_recognition(job_id: int, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    job = db.get(RecognitionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="识别任务不存在")
    if job.status in ("pending", "running"):
        job.status = "cancelled"
        for item in db.query(PlatformJob).filter(PlatformJob.job_type == "batch_ocr").all():
            if json.loads(item.payload_json or "{}").get("recognition_job_id") == job.id:
                item.status, item.completed_at = "cancelled", datetime.now(timezone.utc)
        db.commit()
    return recognition_job_out(job)


@app.get("/api/recognition-jobs/{job_id}")
def recognition_job_detail(job_id: int, _: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]) -> dict:
    job = db.get(RecognitionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="识别任务不存在")
    result = recognition_job_out(job)
    page_numbers = {row.id: row.page_no for row in db.query(BookPage.id, BookPage.page_no).filter(BookPage.book_id == job.book_id)}
    result["pages"] = [{**ocr_page_job_out(item), "page_no": page_numbers.get(item.page_id)} for item in db.query(OcrPageJob).filter(OcrPageJob.batch_id == job.id).order_by(OcrPageJob.id).all()]
    return result


@app.get("/api/my/assignments")
def my_assignments(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    query = db.query(PageAssignment).join(BookPage, PageAssignment.page_id == BookPage.id)
    if user.role == "annotator":
        query = query.filter(PageAssignment.user_id == user.id)
    elif user.role in ("admin", "reviewer"):
        query = query.filter(PageAssignment.status.in_(["submitted", "returned", "approved"]))
    return [assignment_out(item) for item in query.order_by(PageAssignment.book_id.desc(), BookPage.page_no).all()]


@app.get("/api/review/assignments")
def review_assignments(_: Annotated[User, Depends(require_reviewer)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    rows = db.query(PageAssignment).join(BookPage, PageAssignment.page_id == BookPage.id).filter(PageAssignment.status == "submitted").order_by(PageAssignment.book_id.desc(), BookPage.page_no).all()
    return [assignment_out(item) for item in rows]


@app.get("/api/assignments/{assignment_id}/workflow")
def get_assignment_workflow(
    assignment_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    assignment = require_assignment_access(db, assignment_id, user)
    page = db.get(BookPage, assignment.page_id)
    book = db.get(Book, assignment.book_id)
    ensure_default_labels(db, book)
    entities = db.query(BookEntity).filter(BookEntity.book_id == assignment.book_id).order_by(BookEntity.id).all()
    regions = db.query(LayoutRegion).filter(LayoutRegion.assignment_id == assignment.id).order_by(LayoutRegion.order_no, LayoutRegion.id).all()
    lines = db.query(TextLine).filter(TextLine.assignment_id == assignment.id).order_by(TextLine.order_no, TextLine.id).all()
    chars = db.query(TextChar).filter(TextChar.assignment_id == assignment.id).order_by(TextChar.order_no, TextChar.id).all()
    entities_ann = db.query(EntityAnnotation).filter(EntityAnnotation.assignment_id == assignment.id).order_by(EntityAnnotation.id).all()
    labels = db.query(LabelDefinition).filter(LabelDefinition.book_id == assignment.book_id, LabelDefinition.is_active.is_(True)).order_by(LabelDefinition.group, LabelDefinition.sort_order).all()
    return {
        "book": book_out(book),
        "page": book_page_out(page),
        "assignment": assignment_out(assignment),
        "entities": [book_entity_out(item) for item in entities],
        "labels": [label_definition_out(item) for item in labels],
        "regions": [layout_region_out(item) for item in regions],
        "lines": [text_line_out(item) for item in lines],
        "chars": [text_char_out(item) for item in chars],
        "entity_annotations": [entity_annotation_out(item) for item in entities_ann],
    }


@app.put("/api/assignments/{assignment_id}/workflow")
def save_assignment_workflow(
    assignment_id: int,
    payload: WorkflowSaveIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    assignment = require_assignment_access(db, assignment_id, user, for_edit=True)
    if payload.expected_version != assignment.version:
        raise HTTPException(status_code=409, detail={"message": "任务已被其他用户更新，请重新加载", "current_version": assignment.version})
    before = {
        "current_step": assignment.current_step,
        "regions": [layout_region_out(item) for item in db.query(LayoutRegion).filter(LayoutRegion.assignment_id == assignment.id).order_by(LayoutRegion.order_no).all()],
        "lines": [text_line_out(item) for item in db.query(TextLine).filter(TextLine.assignment_id == assignment.id).order_by(TextLine.order_no).all()],
        "chars": [text_char_out(item) for item in db.query(TextChar).filter(TextChar.assignment_id == assignment.id).order_by(TextChar.order_no).all()],
        "entity_annotations": [entity_annotation_out(item) for item in db.query(EntityAnnotation).filter(EntityAnnotation.assignment_id == assignment.id).all()],
    }
    db.add(WorkflowRevision(assignment_id=assignment.id, version=assignment.version, actor_id=user.id, action="autosave", snapshot_json=json.dumps(before, ensure_ascii=False)))
    db.query(LayoutRegion).filter(LayoutRegion.assignment_id == assignment.id).delete()
    db.query(TextChar).filter(TextChar.assignment_id == assignment.id).delete()
    db.query(TextLine).filter(TextLine.assignment_id == assignment.id).delete()
    db.query(EntityAnnotation).filter(EntityAnnotation.assignment_id == assignment.id).delete()
    db.flush()
    old_to_new_region: dict[int, int] = {}
    old_to_new_line: dict[int, int] = {}
    valid_labels = {item.id: item for item in db.query(LabelDefinition).filter(LabelDefinition.book_id == assignment.book_id, LabelDefinition.is_active.is_(True)).all()}
    for row in payload.regions:
        if row.label_id and (row.label_id not in valid_labels or valid_labels[row.label_id].group != "region"):
            raise HTTPException(status_code=400, detail="区域标签无效")
        x1, y1, x2, y2 = normalize_bbox(row.bbox)
        region = LayoutRegion(assignment_id=assignment.id, region_type=row.region_type, label_id=row.label_id, order_no=row.order_no, x1=x1, y1=y1, x2=x2, y2=y2, confirmed=row.confirmed)
        db.add(region)
        db.flush()
        if row.id:
            old_to_new_region[row.id] = region.id
    db.flush()
    for row in payload.lines:
        mapped_region_id = old_to_new_region.get(row.region_id or 0)
        if not mapped_region_id:
            raise HTTPException(status_code=400, detail=f"版面单元 {row.order_no} 必须属于一个区域")
        if row.layout_label_id and (row.layout_label_id not in valid_labels or valid_labels[row.layout_label_id].group != "layout"):
            raise HTTPException(status_code=400, detail="版面标签无效")
        if row.stratum_label_id and (row.stratum_label_id not in valid_labels or valid_labels[row.stratum_label_id].group != "stratum"):
            raise HTTPException(status_code=400, detail="层累标签无效")
        x1, y1, x2, y2 = normalize_bbox(row.bbox)
        line = TextLine(assignment_id=assignment.id, region_id=mapped_region_id, layout_label_id=row.layout_label_id, stratum_label_id=row.stratum_label_id, order_no=row.order_no, x1=x1, y1=y1, x2=x2, y2=y2, char_size=row.char_size, confirmed=row.confirmed, needs_char_split=row.needs_char_split, ocr_text=row.ocr_text)
        db.add(line)
        db.flush()
        if row.id:
            old_to_new_line[row.id] = line.id
    for row in payload.chars:
        mapped_line_id = old_to_new_line.get(row.line_id or 0)
        if not mapped_line_id:
            raise HTTPException(status_code=400, detail=f"字符 {row.order_no} 必须属于一个版面单元")
        if row.custom_char_id:
            character = db.get(CharacterEntry, row.custom_char_id)
            if not character or (character.book_id not in (None, assignment.book_id) and character.status != "global"):
                raise HTTPException(status_code=400, detail="自定义字引用无效")
        x1, y1, x2, y2 = normalize_bbox(row.bbox)
        db.add(
            TextChar(
                assignment_id=assignment.id,
                line_id=mapped_line_id,
                custom_char_id=row.custom_char_id,
                order_no=row.order_no,
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                raw_text=row.raw_text,
                corrected_text=row.corrected_text,
                candidates_json=json.dumps(row.candidates, ensure_ascii=False),
                confidence=row.confidence,
                status=row.status,
            )
        )
    valid_entity_ids = {item.id for item in db.query(BookEntity.id).filter(BookEntity.book_id == assignment.book_id).all()}
    for row in payload.entity_annotations:
        if row.entity_id not in valid_entity_ids:
            raise HTTPException(status_code=400, detail="实体不属于当前书籍")
        x1, y1, x2, y2 = normalize_bbox(row.bbox)
        db.add(EntityAnnotation(assignment_id=assignment.id, entity_id=row.entity_id, x1=x1, y1=y1, x2=x2, y2=y2, note=row.note))
    assignment.current_step = payload.current_step
    assignment.version += 1
    assignment.status = "in_progress" if assignment.status in ("assigned", "returned") else assignment.status
    assignment.updated_at = datetime.now(timezone.utc)
    db.commit()
    return get_assignment_workflow(assignment.id, user, db)


class OcrResetIn(BaseModel):
    mode: str = "all"  # all=区域/列/字全部重置为识别结果；columns=保留区域，仅重置列与字


@app.post("/api/assignments/{assignment_id}/reset-ocr")
def reset_assignment_ocr(assignment_id: int, payload: OcrResetIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    """把任务的框与字重置为最近一次识别结果（供"OCR重置 / 自动重新分列和排序"）。"""
    assignment = require_assignment_access(db, assignment_id, user, for_edit=True)
    if payload.mode not in ("all", "columns"):
        raise HTTPException(status_code=400, detail="mode 只能是 all 或 columns")
    page = db.get(BookPage, assignment.page_id)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    job_row = (
        db.query(OcrPageJob)
        .filter(OcrPageJob.page_id == page.id, OcrPageJob.status.in_(["done", "cached"]), OcrPageJob.raw_path.isnot(None), OcrPageJob.raw_path != "")
        .order_by(OcrPageJob.id.desc())
        .first()
    )
    if not job_row or not Path(job_row.raw_path).exists():
        raise HTTPException(status_code=409, detail="该页没有可用的识别结果，请先在书籍预处理中完成识别")
    result = json.loads(Path(job_row.raw_path).read_text(encoding="utf-8"))
    db.query(TextChar).filter(TextChar.assignment_id == assignment.id).delete()
    db.query(TextLine).filter(TextLine.assignment_id == assignment.id).delete()
    db.flush()
    if payload.mode == "all":
        db.query(LayoutRegion).filter(LayoutRegion.assignment_id == assignment.id).delete()
        db.flush()
        seed_assignment_from_recognition(db, assignment, result)  # 内部自带 commit
    else:  # columns：保留区域，列/字按中点落点重新挂到区域
        kept_regions = db.query(LayoutRegion).filter(LayoutRegion.assignment_id == assignment.id).all()
        line_by_order: dict[int, TextLine] = {}
        for row in result.get("lines", []):
            x1, y1, x2, y2 = normalize_bbox(row["bbox"])
            center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
            parent = next((region for region in kept_regions if region.x1 <= center_x <= region.x2 and region.y1 <= center_y <= region.y2), None)
            line = TextLine(assignment_id=assignment.id, region_id=parent.id if parent else None, order_no=int(row.get("order_no", 1)), x1=x1, y1=y1, x2=x2, y2=y2, char_size=float(row.get("char_size", 0)), confirmed=bool(row.get("confirmed", False)), needs_char_split=bool(row.get("needs_char_split", False)), ocr_text=str(row.get("ocr_text", "")))
            db.add(line)
            db.flush()
            line_by_order[line.order_no] = line
        for row in result.get("chars", []):
            x1, y1, x2, y2 = normalize_bbox(row["bbox"])
            line = line_by_order.get(int(row.get("line_order_no", 0)))
            db.add(TextChar(assignment_id=assignment.id, line_id=line.id if line else None, order_no=int(row.get("order_no", 1)), x1=x1, y1=y1, x2=x2, y2=y2, raw_text=row.get("raw_text", ""), corrected_text=row.get("corrected_text", row.get("raw_text", "")), candidates_json=json.dumps(row.get("candidates", []), ensure_ascii=False), confidence=float(row.get("confidence", 0)), status=row.get("status", "unchecked")))
    assignment.version += 1
    assignment.status = "in_progress" if assignment.status == "assigned" else assignment.status
    assignment.updated_at = datetime.now(timezone.utc)
    db.add(WorkflowRevision(assignment_id=assignment.id, version=assignment.version, actor_id=user.id, action=f"reset_ocr_{payload.mode}", snapshot_json="{}"))
    db.commit()
    return get_assignment_workflow(assignment.id, user, db)


@app.post("/api/assignments/{assignment_id}/submit")
def submit_assignment(assignment_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    assignment = require_assignment_access(db, assignment_id, user, for_edit=True)
    assignment.status = "submitted"
    assignment.current_step = 6
    assignment.version += 1
    assignment.submitted_at = datetime.now(timezone.utc)
    assignment.updated_at = datetime.now(timezone.utc)
    db.add(WorkflowRevision(assignment_id=assignment.id, version=assignment.version, actor_id=user.id, action="submit", snapshot_json="{}"))
    db.commit()
    db.refresh(assignment)
    return assignment_out(assignment)


@app.post("/api/assignments/{assignment_id}/review")
def review_assignment(
    assignment_id: int,
    payload: ReviewActionIn,
    reviewer: Annotated[User, Depends(require_reviewer)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    assignment = db.get(PageAssignment, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="任务页不存在")
    assignment.status = "approved" if payload.action == "approve" else "returned"
    assignment.review_comment = payload.comment
    assignment.reviewed_at = datetime.now(timezone.utc)
    assignment.version += 1
    assignment.updated_at = datetime.now(timezone.utc)
    db.add(ReviewRecord(assignment_id=assignment.id, reviewer_id=reviewer.id, action=payload.action, comment=payload.comment))
    db.add(WorkflowRevision(assignment_id=assignment.id, version=assignment.version, actor_id=reviewer.id, action=payload.action, snapshot_json="{}"))
    db.commit()
    db.refresh(assignment)
    return assignment_out(assignment)


@app.get("/api/assignments/{assignment_id}/revisions")
def list_workflow_revisions(assignment_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    require_assignment_access(db, assignment_id, user)
    rows = db.query(WorkflowRevision).filter(WorkflowRevision.assignment_id == assignment_id).order_by(WorkflowRevision.id.desc()).limit(100).all()
    return [workflow_revision_out(item) for item in rows]


@app.post("/api/assignments/{assignment_id}/revisions/{revision_id}/restore")
def restore_workflow_revision(assignment_id: int, revision_id: int, reviewer: Annotated[User, Depends(require_reviewer)], db: Annotated[Session, Depends(get_db)]) -> dict:
    assignment = require_assignment_access(db, assignment_id, reviewer, for_edit=True)
    revision = db.get(WorkflowRevision, revision_id)
    if not revision or revision.assignment_id != assignment_id or not revision.snapshot_json or revision.snapshot_json == "{}":
        raise HTTPException(status_code=404, detail="可恢复修订不存在")
    data = json.loads(revision.snapshot_json)
    payload = WorkflowSaveIn(expected_version=assignment.version, **data)
    result = save_assignment_workflow(assignment_id, payload, reviewer, db)
    db.add(WorkflowRevision(assignment_id=assignment_id, version=result["assignment"]["version"], actor_id=reviewer.id, action="restore", snapshot_json=revision.snapshot_json))
    db.commit()
    return result


@app.get("/api/characters")
def search_characters(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], q: str = "", book_id: int | None = None) -> list[dict]:
    query = db.query(CharacterEntry).filter((CharacterEntry.status == "global") | (CharacterEntry.book_id == book_id))
    if q:
        like = f"%{q}%"
        query = query.filter(
            (CharacterEntry.character.like(like)) | (CharacterEntry.unicode_codepoint.like(like)) |
            (CharacterEntry.ids.like(like)) | (CharacterEntry.radical.like(like)) |
            (CharacterEntry.readings.like(like)) | (CharacterEntry.aliases.like(like))
        )
    rows = [character_entry_out(item) for item in query.order_by(CharacterEntry.status.desc(), CharacterEntry.id.desc()).limit(50).all()]
    token = q.strip().upper().replace("U+", "")
    try:
        codepoint = int(token, 16) if token and all(ch in "0123456789ABCDEF" for ch in token) else (ord(q) if len(q) == 1 else None)
    except ValueError:
        codepoint = None
    if codepoint is not None and 0 <= codepoint <= 0x10FFFF:
        char = chr(codepoint)
        if not any(item["unicode_codepoint"] == f"U+{codepoint:04X}" for item in rows):
            rows.insert(0, {"id": None, "book_id": None, "unicode_codepoint": f"U+{codepoint:04X}", "character": char, "ids": "", "radical": "", "strokes": None, "readings": "", "aliases": "Unicode", "glyph_url": "", "source_page_id": None, "status": "unicode"})
    return rows


@app.post("/api/characters")
def create_character(payload: CharacterEntryIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    if payload.book_id and not db.get(Book, payload.book_id):
        raise HTTPException(status_code=404, detail="书籍不存在")
    if not payload.character and not payload.ids:
        raise HTTPException(status_code=400, detail="字符或 IDS 至少填写一项")
    values = payload.model_dump()
    if not values["character"]:
        used = []
        for (code,) in db.query(CharacterEntry.unicode_codepoint).filter(CharacterEntry.unicode_codepoint.like("U+E%")).all():
            try: used.append(int(code[2:], 16))
            except ValueError: pass
        codepoint = max([0xDFFF, *used]) + 1
        if codepoint > 0xF8FF:
            raise HTTPException(status_code=409, detail="书内 PUA 编码空间已用尽")
        values["unicode_codepoint"] = f"U+{codepoint:04X}"
        values["character"] = chr(codepoint)
    elif not values["unicode_codepoint"] and len(values["character"]) == 1:
        values["unicode_codepoint"] = f"U+{ord(values['character']):04X}"
    item = CharacterEntry(**values, status="book" if payload.book_id else "pending", created_by=user.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return character_entry_out(item)


@app.post("/api/characters/{character_id}/glyph")
def upload_character_glyph(character_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], file: UploadFile = File(...)) -> dict:
    item = db.get(CharacterEntry, character_id)
    if not item or (user.role not in ("admin", "reviewer") and item.created_by != user.id):
        raise HTTPException(status_code=404, detail="自定义字不存在")
    suffix = Path(file.filename or "glyph.png").suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=400, detail="字形图片仅支持 PNG/JPEG/WebP")
    target_dir = DATA_DIR / "custom_glyphs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"char_{item.id}{suffix}"
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    item.glyph_path = str(target)
    db.commit()
    return character_entry_out(item)


@app.get("/api/characters/{character_id}/glyph")
def character_glyph(character_id: int, db: Annotated[Session, Depends(get_db)]) -> FileResponse:
    item = db.get(CharacterEntry, character_id)
    if not item or not item.glyph_path or not Path(item.glyph_path).exists():
        raise HTTPException(status_code=404, detail="字形图片不存在")
    return FileResponse(item.glyph_path)


@app.post("/api/characters/{character_id}/review")
def review_character(character_id: int, payload: CharacterReviewIn, reviewer: Annotated[User, Depends(require_reviewer)], db: Annotated[Session, Depends(get_db)]) -> dict:
    item = db.get(CharacterEntry, character_id)
    if not item:
        raise HTTPException(status_code=404, detail="自定义字不存在")
    item.status = "global" if payload.action == "promote" else "rejected"
    item.book_id = None if payload.action == "promote" else item.book_id
    item.reviewed_by = reviewer.id
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    return character_entry_out(item)


@app.get("/api/books/{book_id}/final-export")
def export_book_final(book_id: int, _: Annotated[User, Depends(require_reviewer)], db: Annotated[Session, Depends(get_db)]) -> FileResponse:
    book = db.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    assignments = db.query(PageAssignment).join(BookPage, PageAssignment.page_id == BookPage.id).filter(PageAssignment.book_id == book_id, PageAssignment.status == "approved").order_by(BookPage.page_no).all()
    labels = db.query(LabelDefinition).filter(LabelDefinition.book_id == book_id).order_by(LabelDefinition.id).all()
    characters = db.query(CharacterEntry).filter((CharacterEntry.book_id == book_id) | (CharacterEntry.status == "global")).all()
    payload = {"schema_version": "2.0", "book": book_out(book), "labels": [label_definition_out(item) for item in labels], "character_library": [character_entry_out(item) for item in characters], "pages": []}
    coco = {"info": {"description": "Bencao annotation layout export", "version": "2.0"}, "images": [], "categories": [{"id": item.id, "name": f"{item.group}:{item.code}", "supercategory": item.group} for item in labels], "annotations": []}
    char_coco = {"info": {"description": "Bencao corrected character boxes", "version": "2.0"}, "images": [], "categories": [{"id": 1, "name": "character", "supercategory": "text"}], "annotations": []}
    annotation_id = 1
    char_annotation_id = 1
    for assignment in assignments:
        page = db.get(BookPage, assignment.page_id)
        regions = db.query(LayoutRegion).filter(LayoutRegion.assignment_id == assignment.id).order_by(LayoutRegion.order_no).all()
        lines = db.query(TextLine).filter(TextLine.assignment_id == assignment.id).order_by(TextLine.order_no).all()
        chars = db.query(TextChar).filter(TextChar.assignment_id == assignment.id).order_by(TextChar.order_no).all()
        entities_ann = db.query(EntityAnnotation).filter(EntityAnnotation.assignment_id == assignment.id).all()
        revisions = db.query(WorkflowRevision).filter(WorkflowRevision.assignment_id == assignment.id).order_by(WorkflowRevision.id).all()
        payload["pages"].append(
            {
                "assignment": assignment_out(assignment),
                "image": book_page_out(page),
                "text": "".join((item.corrected_text or item.raw_text or "") for item in chars),
                "regions": [layout_region_out(item) for item in regions],
                "layout_units": [text_line_out(item) for item in lines],
                "chars": [text_char_out(item) for item in chars],
                "entities": [entity_annotation_out(item) for item in entities_ann],
                "revisions": [workflow_revision_out(item) for item in revisions],
            }
        )
        image_row = {"id": page.id, "file_name": Path(page.image_path).name, "width": page.width, "height": page.height, "page_no": page.page_no}
        coco["images"].append(image_row)
        char_coco["images"].append(image_row)
        for item in regions:
            if not item.label_id:
                continue
            w, h = item.x2 - item.x1, item.y2 - item.y1
            coco["annotations"].append({"id": annotation_id, "image_id": page.id, "category_id": item.label_id, "bbox": [item.x1, item.y1, w, h], "area": w * h, "iscrowd": 0, "attributes": {"kind": "region", "order": item.order_no}})
            annotation_id += 1
        for item in lines:
            w, h = item.x2 - item.x1, item.y2 - item.y1
            for kind, category_id in (("layout", item.layout_label_id), ("stratum", item.stratum_label_id)):
                if category_id:
                    coco["annotations"].append({"id": annotation_id, "image_id": page.id, "category_id": category_id, "bbox": [item.x1, item.y1, w, h], "area": w * h, "iscrowd": 0, "attributes": {"kind": kind, "order": item.order_no, "region_id": item.region_id}})
                    annotation_id += 1
        for item in chars:
            w, h = item.x2 - item.x1, item.y2 - item.y1
            char_coco["annotations"].append({"id": char_annotation_id, "image_id": page.id, "category_id": 1, "bbox": [item.x1, item.y1, w, h], "area": w * h, "iscrowd": 0, "attributes": {"text": item.corrected_text or item.raw_text, "raw_text": item.raw_text, "status": item.status, "line_id": item.line_id, "custom_char_id": item.custom_char_id}})
            char_annotation_id += 1
    legacy = {"book": payload["book"], "pages": [{"assignment": item["assignment"], "text": item["text"], "chars": item["chars"], "entities": item["entities"]} for item in payload["pages"]]}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_path = EXPORT_DIR / f"book_{book_id}_final_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("annotation-v2.json", json.dumps(payload, ensure_ascii=False, indent=2))
        archive.writestr("coco-layout.json", json.dumps(coco, ensure_ascii=False, indent=2))
        archive.writestr("coco-chars.json", json.dumps(char_coco, ensure_ascii=False, indent=2))
        archive.writestr("final.json", json.dumps(legacy, ensure_ascii=False, indent=2))
        for item in characters:
            if item.glyph_path and Path(item.glyph_path).exists():
                archive.write(item.glyph_path, f"custom-glyphs/{Path(item.glyph_path).name}")
    return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)


@app.post("/api/admin/cleanup")
def admin_cleanup(admin: Annotated[User, Depends(require_admin)]) -> dict:
    from .renderer import cleanup_temp_files as _clean_tmp
    tmp_removed = _clean_tmp()
    export_removed = cleanup_stale_exports()
    return {"temp_files_removed": tmp_removed, "exports_removed": export_removed}
