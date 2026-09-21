from __future__ import annotations

import csv
import io
import json
from collections import deque
from datetime import datetime, timezone
from typing import Annotated, Literal

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import get_current_user
from .database import get_db
from .models import (
    AdjudicationRecord, AiFeedback, Book, BookPage, GraphEdge, GraphNode, Guideline,
    LayoutRegion, MedicalCase, OntologyType, PageAssignment, PlatformJob,
    RecognitionJob, SemanticEntity, SemanticRelation, TextChar, TextLine, TextUnit, User,
)
from .ocr_service import call_paddleocr_vl_api, normalize_paddleocr_vl_response
from .platform_config import is_test_mode
from .semantic_config import effective_semantic_config, public_semantic_config, save_semantic_config


router = APIRouter(prefix="/api")
EDITOR_ROLES = {"admin", "annotator", "reviewer", "expert", "data_engineer"}
EXPERT_ROLES = {"admin", "reviewer", "expert"}
ADMIN_ROLES = {"admin", "data_engineer"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: str, default):
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return default


def _require(user: User, roles: set[str]) -> None:
    if user.role not in roles:
        raise HTTPException(403, "当前角色无权执行此操作")


def _type_out(row: OntologyType) -> dict:
    return {"id": row.id, "book_id": row.book_id, "kind": row.kind, "code": row.code, "name": row.name,
            "color": row.color, "description": row.description, "source_types": _json(row.source_types_json, []),
            "target_types": _json(row.target_types_json, []), "version": row.version, "is_active": row.is_active}


def _unit_out(row: TextUnit) -> dict:
    return {"id": row.id, "book_id": row.book_id, "page_id": row.page_id, "parent_id": row.parent_id,
            "stable_id": row.stable_id, "unit_type": row.unit_type, "title": row.title, "order_no": row.order_no,
            "source_page": row.source_page, "original_text": row.original_text, "normalized_text": row.normalized_text,
            "text_type": row.text_type, "version": row.version, "status": row.status,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def _entity_out(row: SemanticEntity, db: Session) -> dict:
    type_row = db.get(OntologyType, row.type_id)
    return {"id": row.id, "text_unit_id": row.text_unit_id, "assignment_id": row.assignment_id,
            "type_id": row.type_id, "type_code": type_row.code if type_row else "", "type_name": type_row.name if type_row else "",
            "color": type_row.color if type_row else "#64748b", "canonical_name": row.canonical_name,
            "surface_text": row.surface_text, "start_offset": row.start_offset, "end_offset": row.end_offset,
            "bbox": _json(row.bbox_json, []), "aliases": _json(row.aliases_json, []),
            "attributes": _json(row.attributes_json, {}), "source": row.source, "confidence": row.confidence,
            "uncertain": row.uncertain, "status": row.status, "created_by": row.created_by}


def _relation_out(row: SemanticRelation, db: Session) -> dict:
    type_row = db.get(OntologyType, row.type_id)
    return {"id": row.id, "text_unit_id": row.text_unit_id, "assignment_id": row.assignment_id,
            "type_id": row.type_id, "type_code": type_row.code if type_row else "", "type_name": type_row.name if type_row else "",
            "source_entity_id": row.source_entity_id, "target_entity_id": row.target_entity_id,
            "evidence_text": row.evidence_text, "source": row.source, "confidence": row.confidence,
            "uncertain": row.uncertain, "status": row.status, "created_by": row.created_by}


def _case_out(row: MedicalCase) -> dict:
    return {key: getattr(row, key) for key in ("id", "text_unit_id", "assignment_id", "source", "doctor", "disease",
            "symptoms", "diagnosis", "syndrome", "treatment", "formula", "medicines", "outcome", "note", "status", "created_by")}


def _job_out(row: PlatformJob, db: Session) -> dict:
    creator = db.get(User, row.created_by)
    book = db.get(Book, row.book_id) if row.book_id else None
    return {"id": row.id, "job_type": row.job_type, "book_id": row.book_id, "book_title": book.title if book else "",
            "page_id": row.page_id, "created_by": row.created_by, "creator": creator.display_name if creator else "",
            "status": row.status, "progress": row.progress, "model": row.model, "payload": _json(row.payload_json, {}),
            "result": _json(row.result_json, {}), "error": row.error, "attempts": row.attempts,
            "created_at": row.created_at.isoformat(), "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None}


class SemanticSettingsIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=160)
    timeout_seconds: int = Field(default=120, ge=10, le=600)


class OntologyIn(BaseModel):
    id: int | None = None
    book_id: int | None = None
    kind: Literal["entity", "relation"]
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    color: str = Field(default="#2563eb", pattern=r"^#[0-9a-fA-F]{6}$")
    description: str = ""
    source_types: list[str] = []
    target_types: list[str] = []
    is_active: bool = True


class TextUnitIn(BaseModel):
    id: int | None = None
    book_id: int
    page_id: int | None = None
    parent_id: int | None = None
    stable_id: str = Field(min_length=1, max_length=120)
    unit_type: Literal["book", "volume", "chapter", "article", "case", "theory", "saying"] = "article"
    title: str = ""
    order_no: int = 1
    source_page: str = ""
    original_text: str = ""
    normalized_text: str = ""
    text_type: str = "article"
    status: Literal["draft", "submitted", "approved", "gold"] = "draft"
    expected_version: int | None = None


class EntityIn(BaseModel):
    id: int | None = None
    text_unit_id: int
    assignment_id: int | None = None
    type_id: int
    canonical_name: str = Field(min_length=1, max_length=240)
    surface_text: str = ""
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=1)
    bbox: list[float] = []
    aliases: list[str] = []
    attributes: dict = {}
    source: Literal["manual", "ai", "import"] = "manual"
    confidence: float = Field(default=1, ge=0, le=1)
    uncertain: bool = False
    status: Literal["draft", "submitted", "approved", "rejected", "gold"] = "draft"


class RelationIn(BaseModel):
    id: int | None = None
    text_unit_id: int
    assignment_id: int | None = None
    type_id: int
    source_entity_id: int
    target_entity_id: int
    evidence_text: str = ""
    source: Literal["manual", "ai", "import"] = "manual"
    confidence: float = Field(default=1, ge=0, le=1)
    uncertain: bool = False
    status: Literal["draft", "submitted", "approved", "rejected", "gold"] = "draft"


class MedicalCaseIn(BaseModel):
    id: int | None = None
    text_unit_id: int
    assignment_id: int | None = None
    source: str = ""
    doctor: str = ""
    disease: str = ""
    symptoms: str = ""
    diagnosis: str = ""
    syndrome: str = ""
    treatment: str = ""
    formula: str = ""
    medicines: str = ""
    outcome: str = ""
    note: str = ""
    status: Literal["draft", "submitted", "approved", "gold"] = "draft"


class PreviewIn(BaseModel):
    page_id: int


class PreviewConfirmIn(BaseModel):
    job_id: int
    assignment_id: int
    mode: Literal["merge", "version"] = "merge"


class DoubleAssignIn(BaseModel):
    page_id: int
    annotator_a_id: int
    annotator_b_id: int


class AdjudicateIn(BaseModel):
    decision: dict
    comment: str = ""


class SemanticReviewIn(BaseModel):
    entity_ids: list[int] = []
    relation_ids: list[int] = []
    case_ids: list[int] = []
    text_unit_ids: list[int] = []
    action: Literal["approve", "reject"]


class FeedbackIn(BaseModel):
    entity_id: int | None = None
    relation_id: int | None = None
    action: Literal["accept", "reject", "uncertain"]


DEFAULT_ENTITIES = [
    ("doctor", "医家", "#9a3412"), ("book", "医籍", "#7c3aed"), ("disease", "疾病", "#b91c1c"),
    ("symptom", "症状", "#c2410c"), ("syndrome", "证候", "#a16207"), ("treatment", "治法", "#047857"),
    ("formula", "方剂", "#0369a1"), ("medicine", "药物", "#0f766e"), ("case_element", "医案要素", "#4338ca"),
    ("thought", "学术思想", "#6d28d9"),
]
DEFAULT_RELATIONS = [
    ("teacher_of", "师承", ["doctor"], ["doctor"]), ("family_inheritance", "家传", ["doctor"], ["doctor"]),
    ("fellow_disciple", "同门", ["doctor"], ["doctor"]), ("authored", "著述", ["doctor"], ["book"]),
    ("cites", "引用", ["book", "doctor"], ["book", "doctor"]), ("discusses", "论述", ["book", "doctor"], ["disease", "syndrome", "thought"]),
    ("treats", "治疗", ["doctor", "formula", "treatment"], ["disease", "syndrome"]), ("uses", "用方", ["doctor"], ["formula"]),
    ("modifies", "加减", ["formula"], ["formula", "medicine"]), ("inherits", "继承", ["doctor", "thought", "formula"], ["doctor", "thought", "formula"]),
    ("develops", "发展", ["doctor", "thought", "formula"], ["thought", "formula"]),
]


def seed_ontology(db: Session, book_id: int | None = None) -> None:
    if db.query(OntologyType).filter(OntologyType.book_id == book_id).count():
        return
    for code, name, color in DEFAULT_ENTITIES:
        db.add(OntologyType(book_id=book_id, kind="entity", code=code, name=name, color=color))
    for code, name, sources, targets in DEFAULT_RELATIONS:
        db.add(OntologyType(book_id=book_id, kind="relation", code=code, name=name, color="#475569",
                            source_types_json=json.dumps(sources), target_types_json=json.dumps(targets)))
    db.commit()


@router.get("/settings/semantic")
def get_semantic_settings(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, ADMIN_ROLES)
    return public_semantic_config(db)


@router.put("/settings/semantic")
def put_semantic_settings(data: SemanticSettingsIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, ADMIN_ROLES)
    return save_semantic_config(db, api_key=data.api_key, clear_api_key=data.clear_api_key, base_url=data.base_url,
                                model=data.model, timeout_seconds=data.timeout_seconds, updated_by=user.id)


def _openai_chat(config: dict, messages: list[dict], response_format: dict | None = None) -> dict:
    url = str(config["base_url"]).rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    payload = {"model": config["model"], "messages": messages, "temperature": 0}
    if response_format:
        payload["response_format"] = response_format
    response = requests.post(url, headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
                             json=payload, timeout=int(config["timeout_seconds"]))
    response.raise_for_status()
    return response.json()


@router.post("/settings/semantic/test")
def test_semantic_settings(data: SemanticSettingsIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, ADMIN_ROLES)
    note = ""
    if is_test_mode(db):
        config = effective_semantic_config(db)
        note = "测试模式：使用 .env 测试凭据"
    else:
        current = effective_semantic_config(db)
        config = {"api_key": data.api_key or current["api_key"], "base_url": data.base_url or current["base_url"],
                  "model": data.model or current["model"], "timeout_seconds": data.timeout_seconds}
    if not all((config["api_key"], config["base_url"], config["model"])):
        raise HTTPException(409, "请先填写语义模型地址、密钥和模型名")
    started = _now()
    result = _openai_chat(config, [{"role": "user", "content": "只回复：连接正常"}])
    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"ok": True, "model": config["model"], "message": (f"{note}：" if note else "") + content, "elapsed_ms": int((_now() - started).total_seconds() * 1000)}


@router.get("/ontology")
def list_ontology(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], book_id: int | None = None):
    seed_ontology(db, book_id)
    rows = db.query(OntologyType).filter(OntologyType.book_id == book_id).order_by(OntologyType.kind, OntologyType.id).all()
    return [_type_out(row) for row in rows]


@router.put("/ontology")
def save_ontology(items: list[OntologyIn], user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, ADMIN_ROLES)
    for item in items:
        row = db.get(OntologyType, item.id) if item.id else None
        if not row:
            row = OntologyType(book_id=item.book_id, kind=item.kind, code=item.code, name=item.name)
            db.add(row)
        row.book_id, row.kind, row.code, row.name, row.color = item.book_id, item.kind, item.code, item.name, item.color
        row.description, row.is_active = item.description, item.is_active
        row.source_types_json, row.target_types_json = json.dumps(item.source_types), json.dumps(item.target_types)
        row.version += 1 if row.id else 0
    db.commit()
    return [_type_out(row) for row in db.query(OntologyType).order_by(OntologyType.kind, OntologyType.id).all()]


@router.get("/text-units")
def list_text_units(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], book_id: int, page_id: int | None = None):
    query = db.query(TextUnit).filter(TextUnit.book_id == book_id)
    if page_id is not None:
        query = query.filter(TextUnit.page_id == page_id)
    return [_unit_out(row) for row in query.order_by(TextUnit.order_no, TextUnit.id).all()]


@router.post("/text-units")
def save_text_unit(data: TextUnitIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EDITOR_ROLES)
    if data.status in ("approved", "gold") and user.role not in EXPERT_ROLES:
        raise HTTPException(403, "只有审核员或专家可以批准文本")
    row = db.get(TextUnit, data.id) if data.id else None
    if row and data.expected_version is not None and row.version != data.expected_version:
        raise HTTPException(409, "文本已被其他用户修改，请刷新后重试")
    if not row:
        row = TextUnit(book_id=data.book_id, stable_id=data.stable_id)
        db.add(row)
    for key in ("book_id", "page_id", "parent_id", "stable_id", "unit_type", "title", "order_no", "source_page", "original_text", "normalized_text", "text_type", "status"):
        setattr(row, key, getattr(data, key))
    row.updated_by = user.id
    if row.id:
        row.version += 1
    db.commit(); db.refresh(row)
    return _unit_out(row)


@router.get("/semantic/workspace/{text_unit_id}")
def semantic_workspace(text_unit_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], assignment_id: int | None = None):
    unit = db.get(TextUnit, text_unit_id)
    if not unit:
        raise HTTPException(404, "文本单元不存在")
    seed_ontology(db, unit.book_id)
    if user.role == "annotator":
        assignment = db.query(PageAssignment).filter(PageAssignment.page_id == unit.page_id, PageAssignment.user_id == user.id).order_by(PageAssignment.id.desc()).first()
        if not assignment:
            raise HTTPException(403, "该文本单元未分配给当前标注员")
        assignment_id = assignment.id
    eq = db.query(SemanticEntity).filter(SemanticEntity.text_unit_id == unit.id)
    rq = db.query(SemanticRelation).filter(SemanticRelation.text_unit_id == unit.id)
    cq = db.query(MedicalCase).filter(MedicalCase.text_unit_id == unit.id)
    if assignment_id is not None:
        eq, rq, cq = eq.filter(SemanticEntity.assignment_id == assignment_id), rq.filter(SemanticRelation.assignment_id == assignment_id), cq.filter(MedicalCase.assignment_id == assignment_id)
    return {"unit": _unit_out(unit), "ontology": [_type_out(row) for row in db.query(OntologyType).filter(OntologyType.book_id == unit.book_id).all()],
            "entities": [_entity_out(row, db) for row in eq.order_by(SemanticEntity.start_offset).all()],
            "relations": [_relation_out(row, db) for row in rq.order_by(SemanticRelation.id).all()],
            "cases": [_case_out(row) for row in cq.order_by(MedicalCase.id).all()]}


@router.post("/semantic/entities")
def save_entity(data: EntityIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EDITOR_ROLES)
    unit, type_row = db.get(TextUnit, data.text_unit_id), db.get(OntologyType, data.type_id)
    if not unit or not type_row or type_row.kind != "entity":
        raise HTTPException(400, "文本单元或实体类型无效")
    if user.role == "annotator":
        assignment = db.query(PageAssignment).filter(PageAssignment.page_id == unit.page_id, PageAssignment.user_id == user.id).order_by(PageAssignment.id.desc()).first()
        if not assignment: raise HTTPException(403, "该文本单元未分配给当前标注员")
        data.assignment_id = assignment.id
    if data.status in ("approved", "gold") and user.role not in EXPERT_ROLES: raise HTTPException(403, "只有审核员或专家可以批准语义标注")
    text = unit.normalized_text or unit.original_text
    if data.end_offset <= data.start_offset or data.end_offset > len(text):
        raise HTTPException(400, "实体文本偏移超出规范文本范围")
    row = db.get(SemanticEntity, data.id) if data.id else None
    before = _entity_out(row, db) if row and row.source == "ai" else None
    if not row:
        row = SemanticEntity(text_unit_id=data.text_unit_id, assignment_id=data.assignment_id, type_id=data.type_id,
                             canonical_name=data.canonical_name, start_offset=data.start_offset, end_offset=data.end_offset, created_by=user.id)
        db.add(row)
    for key in ("text_unit_id", "assignment_id", "type_id", "canonical_name", "surface_text", "start_offset", "end_offset", "source", "confidence", "uncertain", "status"):
        setattr(row, key, getattr(data, key))
    row.surface_text = data.surface_text or text[data.start_offset:data.end_offset]
    row.bbox_json, row.aliases_json, row.attributes_json = json.dumps(data.bbox), json.dumps(data.aliases, ensure_ascii=False), json.dumps(data.attributes, ensure_ascii=False)
    if before:
        db.add(AiFeedback(entity_id=row.id, action="modified", before_json=json.dumps(before, ensure_ascii=False), after_json=json.dumps(data.model_dump(), ensure_ascii=False), actor_id=user.id))
    db.commit(); db.refresh(row)
    return _entity_out(row, db)


@router.delete("/semantic/entities/{entity_id}")
def delete_entity(entity_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EDITOR_ROLES)
    row = db.get(SemanticEntity, entity_id)
    if not row: raise HTTPException(404, "实体不存在")
    if db.query(SemanticRelation).filter((SemanticRelation.source_entity_id == entity_id) | (SemanticRelation.target_entity_id == entity_id)).count():
        raise HTTPException(409, "请先删除引用该实体的关系")
    db.delete(row); db.commit(); return {"ok": True}


@router.post("/semantic/relations")
def save_relation(data: RelationIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EDITOR_ROLES)
    source, target, type_row = db.get(SemanticEntity, data.source_entity_id), db.get(SemanticEntity, data.target_entity_id), db.get(OntologyType, data.type_id)
    if not source or not target or not type_row or type_row.kind != "relation": raise HTTPException(400, "关系端点或类型无效")
    if source.id == target.id: raise HTTPException(400, "关系不能指向自身")
    if user.role == "annotator":
        if source.created_by != user.id or target.created_by != user.id: raise HTTPException(403, "盲标期间只能关联自己的实体")
        data.assignment_id = source.assignment_id
    if data.status in ("approved", "gold") and user.role not in EXPERT_ROLES: raise HTTPException(403, "只有审核员或专家可以批准关系")
    source_type, target_type = db.get(OntologyType, source.type_id), db.get(OntologyType, target.type_id)
    allowed_s, allowed_t = _json(type_row.source_types_json, []), _json(type_row.target_types_json, [])
    if allowed_s and source_type and source_type.code not in allowed_s: raise HTTPException(400, "起点实体类型不符合关系约束")
    if allowed_t and target_type and target_type.code not in allowed_t: raise HTTPException(400, "终点实体类型不符合关系约束")
    row = db.get(SemanticRelation, data.id) if data.id else None
    before = _relation_out(row, db) if row and row.source == "ai" else None
    if not row:
        row = SemanticRelation(text_unit_id=data.text_unit_id, assignment_id=data.assignment_id, type_id=data.type_id,
                               source_entity_id=data.source_entity_id, target_entity_id=data.target_entity_id, created_by=user.id)
        db.add(row)
    for key in ("text_unit_id", "assignment_id", "type_id", "source_entity_id", "target_entity_id", "evidence_text", "source", "confidence", "uncertain", "status"):
        setattr(row, key, getattr(data, key))
    if before:
        db.add(AiFeedback(relation_id=row.id, action="modified", before_json=json.dumps(before, ensure_ascii=False), after_json=json.dumps(data.model_dump(), ensure_ascii=False), actor_id=user.id))
    try: db.commit()
    except Exception as exc:
        db.rollback(); raise HTTPException(409, "重复关系") from exc
    db.refresh(row); return _relation_out(row, db)


@router.delete("/semantic/relations/{relation_id}")
def delete_relation(relation_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EDITOR_ROLES)
    row = db.get(SemanticRelation, relation_id)
    if not row: raise HTTPException(404, "关系不存在")
    db.delete(row); db.commit(); return {"ok": True}


@router.post("/semantic/cases")
def save_case(data: MedicalCaseIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EDITOR_ROLES)
    unit = db.get(TextUnit, data.text_unit_id)
    if not unit: raise HTTPException(404, "文本单元不存在")
    if user.role == "annotator":
        assignment = db.query(PageAssignment).filter(PageAssignment.page_id == unit.page_id, PageAssignment.user_id == user.id).order_by(PageAssignment.id.desc()).first()
        if not assignment: raise HTTPException(403, "该文本单元未分配给当前标注员")
        data.assignment_id = assignment.id
    if data.status in ("approved", "gold") and user.role not in EXPERT_ROLES: raise HTTPException(403, "只有审核员或专家可以批准医案")
    row = db.get(MedicalCase, data.id) if data.id else None
    if not row:
        row = MedicalCase(text_unit_id=data.text_unit_id, assignment_id=data.assignment_id, created_by=user.id); db.add(row)
    for key in ("text_unit_id", "assignment_id", "source", "doctor", "disease", "symptoms", "diagnosis", "syndrome", "treatment", "formula", "medicines", "outcome", "note", "status"):
        setattr(row, key, getattr(data, key))
    db.commit(); db.refresh(row); return _case_out(row)


@router.get("/platform-jobs")
def list_jobs(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], limit: int = Query(default=100, ge=1, le=500)):
    query = db.query(PlatformJob)
    if user.role not in ADMIN_ROLES | EXPERT_ROLES: query = query.filter(PlatformJob.created_by == user.id)
    return [_job_out(row, db) for row in query.order_by(PlatformJob.id.desc()).limit(limit).all()]


@router.get("/platform-jobs/{job_id}")
def job_detail(job_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    row = db.get(PlatformJob, job_id)
    if not row: raise HTTPException(404, "任务不存在")
    if user.role not in ADMIN_ROLES | EXPERT_ROLES and row.created_by != user.id: raise HTTPException(403, "无权查看该任务")
    return _job_out(row, db)


@router.post("/platform-jobs/{job_id}/cancel")
def cancel_job(job_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    row = db.get(PlatformJob, job_id)
    if not row: raise HTTPException(404, "任务不存在")
    if user.role not in ADMIN_ROLES and row.created_by != user.id: raise HTTPException(403, "无权取消该任务")
    if row.status not in (("queued", "running") if row.job_type in ("batch_ocr", "page_preprocess") else ("queued",)): raise HTTPException(409, "当前状态不能安全取消")
    if row.job_type in ("batch_ocr", "page_preprocess"):
        recognition_id = int(_json(row.payload_json, {}).get("recognition_job_id", 0))
        recognition = db.get(RecognitionJob, recognition_id)
        if recognition and recognition.status in ("pending", "running"): recognition.status = "cancelled"
    row.status, row.completed_at = "cancelled", _now(); db.commit(); return _job_out(row, db)


@router.post("/platform-jobs/{job_id}/retry")
def retry_job(job_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    row = db.get(PlatformJob, job_id)
    if not row: raise HTTPException(404, "任务不存在")
    if row.status != "failed": raise HTTPException(409, "只有失败任务可以重试")
    if user.role not in ADMIN_ROLES and row.created_by != user.id: raise HTTPException(403, "无权重试该任务")
    if row.job_type == "ocr_preview" and row.page_id:
        return run_ocr_preview(PreviewIn(page_id=row.page_id), user, db)
    if row.job_type == "semantic_preannotation":
        unit_id = int(_json(row.payload_json, {}).get("text_unit_id", 0))
        return preannotate(unit_id, user, db)
    if row.job_type == "graph_build" and row.book_id:
        return build_graph(row.book_id, user, db)
    raise HTTPException(409, "该任务请在原始功能页面重新发起")


@router.post("/ocr-preview")
def run_ocr_preview(data: PreviewIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, ADMIN_ROLES)
    page = db.get(BookPage, data.page_id)
    if not page: raise HTTPException(404, "页面不存在")
    job = PlatformJob(job_type="ocr_preview", book_id=page.book_id, page_id=page.id, created_by=user.id,
                      status="running", progress=10, started_at=_now(), attempts=1)
    db.add(job); db.commit(); db.refresh(job)
    try:
        raw = call_paddleocr_vl_api(page.image_path)
        normalized = normalize_paddleocr_vl_response(raw)
        job.status, job.progress, job.result_json, job.completed_at = "succeeded", 100, json.dumps(normalized, ensure_ascii=False), _now()
    except Exception as exc:
        job.status, job.error, job.completed_at = "failed", str(exc), _now(); db.commit()
        raise HTTPException(502, f"OCR 预览失败：{exc}") from exc
    db.commit(); return _job_out(job, db)


def _norm_bbox(value: list[float]) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = value
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


@router.post("/ocr-preview/confirm")
def confirm_ocr_preview(data: PreviewConfirmIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, ADMIN_ROLES)
    job, assignment = db.get(PlatformJob, data.job_id), db.get(PageAssignment, data.assignment_id)
    if not job or job.status != "succeeded" or job.job_type != "ocr_preview": raise HTTPException(400, "预览任务无效或尚未成功")
    if not assignment or assignment.page_id != job.page_id: raise HTTPException(400, "任务与页面不匹配")
    existing = db.query(LayoutRegion).filter(LayoutRegion.assignment_id == assignment.id).count()
    if existing and data.mode == "merge": raise HTTPException(409, "该任务已有初标；请选择另存版本或取消")
    if existing and data.mode == "version":
        assignment = PageAssignment(book_id=assignment.book_id, page_id=assignment.page_id, user_id=assignment.user_id, status="in_progress")
        db.add(assignment); db.flush()
    result = _json(job.result_json, {})
    regions = {}
    for item in result.get("regions", []):
        x1, y1, x2, y2 = _norm_bbox(item.get("bbox", [0, 0, 1, 1])); row = LayoutRegion(assignment_id=assignment.id, region_type=item.get("region_type", "text"), order_no=item.get("order_no", 1), x1=x1, y1=y1, x2=x2, y2=y2)
        db.add(row); db.flush(); regions[row.order_no] = row
    lines = {}
    for item in result.get("lines", []):
        x1, y1, x2, y2 = _norm_bbox(item.get("bbox", [0, 0, 1, 1])); region = regions.get(item.get("region_order_no"))
        row = TextLine(assignment_id=assignment.id, region_id=region.id if region else None, order_no=item.get("order_no", 1), x1=x1, y1=y1, x2=x2, y2=y2, char_size=item.get("char_size", 0), ocr_text=item.get("ocr_text", ""))
        db.add(row); db.flush(); lines[row.order_no] = row
    for item in result.get("chars", []):
        x1, y1, x2, y2 = _norm_bbox(item.get("bbox", [0, 0, 1, 1])); line = lines.get(item.get("line_order_no"))
        db.add(TextChar(assignment_id=assignment.id, line_id=line.id if line else None, order_no=item.get("order_no", 1), x1=x1, y1=y1, x2=x2, y2=y2, raw_text=item.get("raw_text", ""), corrected_text=item.get("corrected_text", item.get("raw_text", "")), candidates_json=json.dumps(item.get("candidates", []), ensure_ascii=False), confidence=item.get("confidence", 0), status="unchecked"))
    assignment.status = "in_progress"; db.commit()
    return {"ok": True, "assignment_id": assignment.id}


def _entity_key(row: SemanticEntity) -> tuple:
    return row.start_offset, row.end_offset, row.type_id, row.canonical_name


def _agreement(db: Session, a: int, b: int) -> dict:
    ea, eb = db.query(SemanticEntity).filter(SemanticEntity.assignment_id == a).all(), db.query(SemanticEntity).filter(SemanticEntity.assignment_id == b).all()
    sa, sb = {_entity_key(x) for x in ea}, {_entity_key(x) for x in eb}; match = len(sa & sb)
    precision = match / len(sb) if sb else (1 if not sa else 0); recall = match / len(sa) if sa else (1 if not sb else 0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    entity_keys = {x.id: _entity_key(x) for x in ea + eb}
    ra = {(x.type_id, entity_keys.get(x.source_entity_id), entity_keys.get(x.target_entity_id)) for x in db.query(SemanticRelation).filter(SemanticRelation.assignment_id == a).all()}
    rb = {(x.type_id, entity_keys.get(x.source_entity_id), entity_keys.get(x.target_entity_id)) for x in db.query(SemanticRelation).filter(SemanticRelation.assignment_id == b).all()}
    rmatch = len(ra & rb); rf1 = (2 * rmatch / (len(ra) + len(rb))) if ra or rb else 1
    total = max(len(sa | sb), 1); observed = match / total
    expected = ((len(sa) / total) * (len(sb) / total)) if total else 0
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1
    return {"entity_a": len(sa), "entity_b": len(sb), "matched": match, "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4), "relation_f1": round(rf1, 4), "kappa": round(kappa, 4)}


@router.post("/quality/double-assign")
def create_double_assignment(data: DoubleAssignIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, ADMIN_ROLES)
    page = db.get(BookPage, data.page_id)
    if not page or data.annotator_a_id == data.annotator_b_id: raise HTTPException(400, "页面无效或两名标注员重复")
    rows = []
    for uid in (data.annotator_a_id, data.annotator_b_id):
        target = db.get(User, uid)
        if not target or target.role != "annotator": raise HTTPException(400, "双标人员必须是有效标注员")
        row = PageAssignment(book_id=page.book_id, page_id=page.id, user_id=uid, status="assigned"); db.add(row); db.flush(); rows.append(row)
    record = AdjudicationRecord(book_id=page.book_id, page_id=page.id, assignment_a_id=rows[0].id, assignment_b_id=rows[1].id)
    db.add(record); db.commit(); return {"id": record.id, "assignment_a_id": rows[0].id, "assignment_b_id": rows[1].id, "status": record.status}


@router.get("/quality/adjudications")
def list_adjudications(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EXPERT_ROLES | ADMIN_ROLES)
    result = []
    for row in db.query(AdjudicationRecord).order_by(AdjudicationRecord.id.desc()).all():
        metrics = _agreement(db, row.assignment_a_id, row.assignment_b_id)
        if row.metrics_json != json.dumps(metrics): row.metrics_json = json.dumps(metrics)
        result.append({"id": row.id, "book_id": row.book_id, "page_id": row.page_id, "assignment_a_id": row.assignment_a_id, "assignment_b_id": row.assignment_b_id,
                       "status": row.status, "metrics": metrics, "decision": _json(row.decision_json, {}), "comment": row.comment, "expert_id": row.expert_id})
    db.commit(); return result


@router.post("/quality/adjudications/{record_id}")
def adjudicate(record_id: int, data: AdjudicateIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EXPERT_ROLES)
    row = db.get(AdjudicationRecord, record_id)
    if not row: raise HTTPException(404, "裁决任务不存在")
    if row.status == "decided": raise HTTPException(409, "裁决记录已锁定，不可覆盖")
    row.expert_id, row.status, row.decision_json, row.comment, row.decided_at = user.id, "decided", json.dumps(data.decision, ensure_ascii=False), data.comment, _now()
    for assignment_id in (row.assignment_a_id, row.assignment_b_id):
        db.query(SemanticEntity).filter(SemanticEntity.assignment_id == assignment_id, SemanticEntity.status == "approved").update({"status": "gold"})
        db.query(SemanticRelation).filter(SemanticRelation.assignment_id == assignment_id, SemanticRelation.status == "approved").update({"status": "gold"})
    db.commit(); return {"ok": True, "status": row.status}


@router.post("/semantic/review")
def review_semantic(data: SemanticReviewIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EXPERT_ROLES)
    target = "approved" if data.action == "approve" else "rejected"
    counts = {"entities": 0, "relations": 0, "cases": 0, "text_units": 0}
    for model, ids, key in ((SemanticEntity, data.entity_ids, "entities"), (SemanticRelation, data.relation_ids, "relations"), (MedicalCase, data.case_ids, "cases"), (TextUnit, data.text_unit_ids, "text_units")):
        if ids:
            counts[key] = db.query(model).filter(model.id.in_(ids)).update({"status": target}, synchronize_session=False)
    db.commit()
    return {"ok": True, "status": target, "counts": counts}


@router.post("/semantic/feedback")
def semantic_feedback(data: FeedbackIn, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EDITOR_ROLES)
    if bool(data.entity_id) == bool(data.relation_id): raise HTTPException(400, "必须且只能选择一个 AI 标注目标")
    row = db.get(SemanticEntity, data.entity_id) if data.entity_id else db.get(SemanticRelation, data.relation_id)
    if not row or row.source != "ai": raise HTTPException(404, "AI 标注不存在")
    before = _entity_out(row, db) if data.entity_id else _relation_out(row, db)
    if data.action == "reject": row.status = "rejected"
    elif data.action == "uncertain": row.uncertain = True
    else: row.status = "draft"
    db.add(AiFeedback(entity_id=data.entity_id, relation_id=data.relation_id, action=data.action,
                      before_json=json.dumps(before, ensure_ascii=False), after_json=json.dumps({"status": row.status, "uncertain": row.uncertain}), actor_id=user.id))
    db.commit(); return {"ok": True, "status": row.status, "uncertain": row.uncertain}


@router.get("/quality/report")
def quality_report(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], book_id: int | None = None):
    _require(user, EXPERT_ROLES | ADMIN_ROLES)
    eq, rq, cq = db.query(SemanticEntity), db.query(SemanticRelation), db.query(MedicalCase)
    if book_id:
        unit_ids = [x.id for x in db.query(TextUnit).filter(TextUnit.book_id == book_id)]
        eq, rq, cq = eq.filter(SemanticEntity.text_unit_id.in_(unit_ids)), rq.filter(SemanticRelation.text_unit_id.in_(unit_ids)), cq.filter(MedicalCase.text_unit_id.in_(unit_ids))
    entities, relations, cases = eq.all(), rq.all(), cq.all()
    return {"entities": len(entities), "relations": len(relations), "cases": len(cases), "uncertain": sum(x.uncertain for x in entities) + sum(x.uncertain for x in relations),
            "approved": sum(x.status in ("approved", "gold") for x in entities) + sum(x.status in ("approved", "gold") for x in relations),
            "duplicate_entities": len(entities) - len({_entity_key(x) for x in entities}), "adjudications": db.query(AdjudicationRecord).count(),
            "gold_records": db.query(AdjudicationRecord).filter(AdjudicationRecord.status == "decided").count()}


@router.post("/semantic/preannotate/{text_unit_id}")
def preannotate(text_unit_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EDITOR_ROLES)
    unit = db.get(TextUnit, text_unit_id)
    if not unit: raise HTTPException(404, "文本单元不存在")
    seed_ontology(db, unit.book_id); types = db.query(OntologyType).filter(OntologyType.book_id == unit.book_id).all()
    config = effective_semantic_config(db)
    if not all((config["api_key"], config["base_url"], config["model"])): raise HTTPException(409, "尚未配置语义模型")
    schema = {"entities": [{"type": "doctor", "text": "", "canonical_name": "", "start": 0, "end": 1, "confidence": 0.8}],
              "relations": [{"type": "teacher_of", "source_index": 0, "target_index": 1, "evidence": ""}], "case": {}}
    prompt = "你是中医古籍语义标注助手。仅输出JSON，不要解释。实体类型：" + ",".join(x.code for x in types if x.kind == "entity") + "；关系类型：" + ",".join(x.code for x in types if x.kind == "relation") + "。格式示例：" + json.dumps(schema, ensure_ascii=False) + "。文本：" + (unit.normalized_text or unit.original_text)
    job = PlatformJob(job_type="semantic_preannotation", book_id=unit.book_id, page_id=unit.page_id, created_by=user.id, status="running", progress=10, model=str(config["model"]), started_at=_now(), attempts=1, payload_json=json.dumps({"text_unit_id": unit.id}))
    db.add(job); db.commit(); db.refresh(job)
    try:
        raw = _openai_chat(config, [{"role": "user", "content": prompt}]); content = raw.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        if content.startswith("```"): content = content.strip("`").removeprefix("json").strip()
        parsed = json.loads(content)
        job.result_json = json.dumps(parsed, ensure_ascii=False); job.status, job.progress, job.completed_at = "succeeded", 100, _now()
    except Exception as exc:
        job.status, job.error, job.completed_at = "failed", str(exc), _now(); db.commit(); raise HTTPException(502, f"语义预标注失败：{exc}") from exc
    db.commit(); return _job_out(job, db)


@router.post("/semantic/preannotation/{job_id}/apply")
def apply_preannotation(job_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    job = db.get(PlatformJob, job_id)
    if not job or job.job_type != "semantic_preannotation" or job.status != "succeeded": raise HTTPException(400, "预标注任务无效")
    unit_id = int(_json(job.payload_json, {}).get("text_unit_id", 0)); unit = db.get(TextUnit, unit_id); result = _json(job.result_json, {})
    types = {x.code: x for x in db.query(OntologyType).filter(OntologyType.book_id == unit.book_id).all()}; created = []
    text = unit.normalized_text or unit.original_text
    for item in result.get("entities", []):
        type_row = types.get(str(item.get("type"))); start, end = int(item.get("start", -1)), int(item.get("end", -1))
        if not type_row or start < 0 or end <= start or end > len(text): continue
        row = SemanticEntity(text_unit_id=unit.id, type_id=type_row.id, canonical_name=str(item.get("canonical_name") or item.get("text") or text[start:end]), surface_text=text[start:end], start_offset=start, end_offset=end, source="ai", confidence=float(item.get("confidence", 0.5)), status="draft", created_by=user.id)
        db.add(row); db.flush(); created.append(row)
    for item in result.get("relations", []):
        type_row = types.get(str(item.get("type"))); si, ti = int(item.get("source_index", -1)), int(item.get("target_index", -1))
        if type_row and 0 <= si < len(created) and 0 <= ti < len(created) and si != ti:
            db.add(SemanticRelation(text_unit_id=unit.id, type_id=type_row.id, source_entity_id=created[si].id, target_entity_id=created[ti].id, evidence_text=str(item.get("evidence", "")), source="ai", confidence=float(item.get("confidence", 0.5)), status="draft", created_by=user.id))
    db.add(AiFeedback(job_id=job.id, action="accepted_batch", after_json=json.dumps({"entities": len(created)}), actor_id=user.id)); db.commit()
    return {"ok": True, "entities": len(created)}


@router.post("/graph/build/{book_id}")
def build_graph(book_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, EXPERT_ROLES | ADMIN_ROLES)
    unit_ids = [x.id for x in db.query(TextUnit).filter(TextUnit.book_id == book_id)]
    entities = db.query(SemanticEntity).filter(SemanticEntity.text_unit_id.in_(unit_ids), SemanticEntity.status.in_(["approved", "gold"])).all()
    db.query(GraphEdge).filter(GraphEdge.book_id == book_id).delete(); db.query(GraphNode).filter(GraphNode.book_id == book_id).delete(); db.flush()
    node_by_entity = {}; node_map = {}
    for entity in entities:
        type_row = db.get(OntologyType, entity.type_id); key = (type_row.code if type_row else "unknown", entity.canonical_name.strip())
        node = node_map.get(key)
        if not node:
            node = GraphNode(book_id=book_id, type_code=key[0], canonical_name=key[1], aliases_json=entity.aliases_json, evidence_count=0); db.add(node); db.flush(); node_map[key] = node
        node.evidence_count += 1; node_by_entity[entity.id] = node
    relations = db.query(SemanticRelation).filter(SemanticRelation.text_unit_id.in_(unit_ids), SemanticRelation.status.in_(["approved", "gold"])).all()
    edge_map = {}
    for relation in relations:
        source, target, type_row = node_by_entity.get(relation.source_entity_id), node_by_entity.get(relation.target_entity_id), db.get(OntologyType, relation.type_id)
        if not source or not target or not type_row: continue
        key = (type_row.code, source.id, target.id); evidence = {"text_unit_id": relation.text_unit_id, "text": relation.evidence_text, "relation_id": relation.id}
        edge = edge_map.get(key)
        if not edge:
            edge = GraphEdge(book_id=book_id, type_code=type_row.code, source_node_id=source.id, target_node_id=target.id, evidence_json="[]", evidence_count=0); db.add(edge); db.flush(); edge_map[key] = edge
        items = _json(edge.evidence_json, []); items.append(evidence); edge.evidence_json, edge.evidence_count = json.dumps(items, ensure_ascii=False), len(items)
    job = PlatformJob(job_type="graph_build", book_id=book_id, created_by=user.id, status="succeeded", progress=100, result_json=json.dumps({"nodes": len(node_map), "edges": len(edge_map)}), started_at=_now(), completed_at=_now())
    db.add(job); db.commit(); return _job_out(job, db)


@router.get("/graph/{book_id}")
def get_graph(book_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], q: str = ""):
    nodes = db.query(GraphNode).filter(GraphNode.book_id == book_id).all(); edges = db.query(GraphEdge).filter(GraphEdge.book_id == book_id).all()
    if q:
        matched = {n.id for n in nodes if q.lower() in n.canonical_name.lower()}; linked = {e.source_node_id for e in edges if e.target_node_id in matched} | {e.target_node_id for e in edges if e.source_node_id in matched}; keep = matched | linked
        nodes, edges = [n for n in nodes if n.id in keep], [e for e in edges if e.source_node_id in keep and e.target_node_id in keep]
    return {"nodes": [{"id": n.id, "type": n.type_code, "name": n.canonical_name, "aliases": _json(n.aliases_json, []), "evidence_count": n.evidence_count} for n in nodes],
            "edges": [{"id": e.id, "type": e.type_code, "source": e.source_node_id, "target": e.target_node_id, "evidence": _json(e.evidence_json, []), "evidence_count": e.evidence_count} for e in edges]}


@router.get("/graph/{book_id}/export")
def export_graph(book_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], format: Literal["json", "csv", "graphml"] = "json"):
    data = get_graph(book_id, user, db)
    if format == "json": return data
    if format == "csv":
        output = io.StringIO(); writer = csv.writer(output); writer.writerow(["source", "relation", "target", "evidence_count"]); names = {n["id"]: n["name"] for n in data["nodes"]}
        for edge in data["edges"]: writer.writerow([names.get(edge["source"]), edge["type"], names.get(edge["target"]), edge["evidence_count"]])
        return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=graph_{book_id}.csv"})
    nodes = "".join(f'<node id="n{x["id"]}"><data key="label">{x["name"]}</data></node>' for x in data["nodes"])
    edges = "".join(f'<edge source="n{x["source"]}" target="n{x["target"]}"><data key="type">{x["type"]}</data></edge>' for x in data["edges"])
    body = '<?xml version="1.0" encoding="UTF-8"?><graphml xmlns="http://graphml.graphdrawing.org/xmlns"><graph edgedefault="directed">' + nodes + edges + "</graph></graphml>"
    return Response(body, media_type="application/graphml+xml", headers={"Content-Disposition": f"attachment; filename=graph_{book_id}.graphml"})


@router.get("/research/cases")
def search_cases(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], book_id: int | None = None, disease: str = "", syndrome: str = "", formula: str = "", doctor: str = ""):
    query = db.query(MedicalCase).filter(MedicalCase.status.in_(["approved", "gold"]))
    if book_id:
        ids = [x.id for x in db.query(TextUnit).filter(TextUnit.book_id == book_id)]; query = query.filter(MedicalCase.text_unit_id.in_(ids))
    for field, value in ((MedicalCase.disease, disease), (MedicalCase.syndrome, syndrome), (MedicalCase.formula, formula), (MedicalCase.doctor, doctor)):
        if value: query = query.filter(field.contains(value))
    return [_case_out(x) for x in query.order_by(MedicalCase.id.desc()).limit(200).all()]


@router.get("/research/answer")
def research_answer(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], book_id: int, q: str = Query(min_length=1)):
    units = db.query(TextUnit).filter(TextUnit.book_id == book_id, TextUnit.status.in_(["approved", "gold"])).all()
    terms = [x for x in q.replace("？", " ").replace("?", " ").split() if x]
    hits = [u for u in units if any(term in (u.normalized_text or u.original_text or u.title) for term in terms or [q])][:8]
    evidence = [{"text_unit_id": u.id, "title": u.title, "source_page": u.source_page, "text": (u.normalized_text or u.original_text)[:500]} for u in hits]
    if not evidence: return {"answer": "现有已审核语料中未找到可支撑该问题的证据。", "evidence": [], "disclaimer": "仅供学术研究，不构成医疗建议。"}
    return {"answer": f"在已审核古籍中找到 {len(evidence)} 条相关证据，请结合下列原文进行研究判断。", "evidence": evidence, "disclaimer": "仅供学术研究，不构成医疗建议。"}


@router.get("/research/recommend")
def research_recommend(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], disease: str = Query(min_length=1)):
    rows = db.query(MedicalCase).filter(MedicalCase.status.in_(["approved", "gold"]), MedicalCase.disease.contains(disease)).limit(50).all()
    return {"query": disease, "cases": [_case_out(x) for x in rows], "summary": f"找到 {len(rows)} 条已审核医案证据。", "disclaimer": "仅供学术研究，不构成医疗建议。"}


@router.get("/books/{book_id}/semantic-export")
def semantic_export(book_id: int, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    book = db.get(Book, book_id)
    if not book: raise HTTPException(404, "书籍不存在")
    units = db.query(TextUnit).filter(TextUnit.book_id == book_id).order_by(TextUnit.order_no, TextUnit.id).all()
    unit_ids = [x.id for x in units]
    entities = db.query(SemanticEntity).filter(SemanticEntity.text_unit_id.in_(unit_ids)).all() if unit_ids else []
    relations = db.query(SemanticRelation).filter(SemanticRelation.text_unit_id.in_(unit_ids)).all() if unit_ids else []
    cases = db.query(MedicalCase).filter(MedicalCase.text_unit_id.in_(unit_ids)).all() if unit_ids else []
    adjudications = db.query(AdjudicationRecord).filter(AdjudicationRecord.book_id == book_id).all()
    ontology = db.query(OntologyType).filter(OntologyType.book_id == book_id).all()
    graph = get_graph(book_id, user, db)
    return {
        "schema_version": "3.0", "generated_at": _now().isoformat(),
        "book": {"id": book.id, "title": book.title, "page_count": book.page_count},
        "ontology": [_type_out(x) for x in ontology], "text_units": [_unit_out(x) for x in units],
        "entities": [_entity_out(x, db) for x in entities], "relations": [_relation_out(x, db) for x in relations],
        "medical_cases": [_case_out(x) for x in cases],
        "adjudications": [{"id": x.id, "page_id": x.page_id, "assignment_a_id": x.assignment_a_id, "assignment_b_id": x.assignment_b_id,
                           "status": x.status, "metrics": _json(x.metrics_json, {}), "decision": _json(x.decision_json, {}), "comment": x.comment} for x in adjudications],
        "guidelines": [{"id": x.id, "title": x.title, "content": x.content, "version": x.version, "status": x.status, "scope": x.scope,
                        "examples": _json(x.examples_json, [])} for x in db.query(Guideline).filter(Guideline.is_active.is_(True)).all()],
        "knowledge_graph": graph,
    }


@router.get("/ai-feedback/export")
def export_ai_feedback(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    _require(user, ADMIN_ROLES | EXPERT_ROLES)
    rows = db.query(AiFeedback).order_by(AiFeedback.id).all()
    return {"schema_version": "1.0", "items": [{"id": x.id, "job_id": x.job_id, "entity_id": x.entity_id, "relation_id": x.relation_id,
            "action": x.action, "before": _json(x.before_json, {}), "after": _json(x.after_json, {}), "actor_id": x.actor_id,
            "created_at": x.created_at.isoformat()} for x in rows]}
