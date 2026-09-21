from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="annotator")
    display_name: Mapped[str] = mapped_column(String(120), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_ai_expert: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    annotations: Mapped[list["Annotation"]] = relationship(back_populates="user")


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    task_prompt: Mapped[str] = mapped_column(Text, default="")
    pdf_path: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    pages: Mapped[list["BookPage"]] = relationship(back_populates="book")
    entities: Mapped[list["BookEntity"]] = relationship(back_populates="book")


class BookPage(Base):
    __tablename__ = "book_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    page_no: Mapped[int] = mapped_column(Integer, index=True)
    page_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    dpi: Mapped[int] = mapped_column(Integer, default=300)
    image_path: Mapped[str] = mapped_column(String(500), default="")
    recognition_status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    book: Mapped[Book] = relationship(back_populates="pages")


class BookEntity(Base):
    __tablename__ = "book_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(180))
    color: Mapped[str] = mapped_column(String(16), default="#2563eb")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    book: Mapped[Book] = relationship(back_populates="entities")


class PageAssignment(Base):
    __tablename__ = "page_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("book_pages.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="assigned")
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    review_comment: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    page: Mapped[BookPage] = relationship()
    user: Mapped[User] = relationship()


class LayoutRegion(Base):
    __tablename__ = "layout_regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("page_assignments.id"), index=True)
    region_type: Mapped[str] = mapped_column(String(32), default="text")
    label_id: Mapped[int | None] = mapped_column(ForeignKey("label_definitions.id"), nullable=True, index=True)
    order_no: Mapped[int] = mapped_column(Integer, default=1)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class TextLine(Base):
    __tablename__ = "text_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("page_assignments.id"), index=True)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("layout_regions.id"), nullable=True, index=True)
    layout_label_id: Mapped[int | None] = mapped_column(ForeignKey("label_definitions.id"), nullable=True, index=True)
    stratum_label_id: Mapped[int | None] = mapped_column(ForeignKey("label_definitions.id"), nullable=True, index=True)
    order_no: Mapped[int] = mapped_column(Integer, index=True)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    char_size: Mapped[float] = mapped_column(Float, default=0)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_char_split: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_text: Mapped[str] = mapped_column(Text, default="")


class TextChar(Base):
    __tablename__ = "text_chars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("page_assignments.id"), index=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey("text_lines.id"), nullable=True, index=True)
    custom_char_id: Mapped[int | None] = mapped_column(ForeignKey("character_entries.id"), nullable=True, index=True)
    order_no: Mapped[int] = mapped_column(Integer, index=True)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    raw_text: Mapped[str] = mapped_column(String(20), default="")
    corrected_text: Mapped[str] = mapped_column(String(20), default="")
    candidates_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(32), default="unchecked")


class EntityAnnotation(Base):
    __tablename__ = "entity_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("page_assignments.id"), index=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("book_entities.id"), index=True)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    entity: Mapped[BookEntity] = relationship()


class ReviewRecord(Base):
    __tablename__ = "review_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("page_assignments.id"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RecognitionJob(Base):
    __tablename__ = "recognition_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    current_page: Mapped[int] = mapped_column(Integer, default=0)
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class OcrProviderSetting(Base):
    __tablename__ = "ocr_provider_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String(32), default="paddleocr")
    access_token_encrypted: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    model: Mapped[str] = mapped_column(String(120), default="PaddleOCR-VL-1.6")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    test_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class LabelDefinition(Base):
    __tablename__ = "label_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    group: Mapped[str] = mapped_column(String(24), index=True)  # region/layout/stratum
    code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(160))
    color: Mapped[str] = mapped_column(String(16), default="#2563eb")
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkflowRevision(Base):
    __tablename__ = "workflow_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("page_assignments.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(32), default="save")
    snapshot_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class CharacterEntry(Base):
    __tablename__ = "character_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"), nullable=True, index=True)
    unicode_codepoint: Mapped[str] = mapped_column(String(20), default="", index=True)
    character: Mapped[str] = mapped_column(String(20), default="", index=True)
    ids: Mapped[str] = mapped_column(String(255), default="")
    radical: Mapped[str] = mapped_column(String(32), default="")
    strokes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    readings: Mapped[str] = mapped_column(String(255), default="")
    aliases: Mapped[str] = mapped_column(String(255), default="")
    glyph_path: Mapped[str] = mapped_column(String(500), default="")
    source_page_id: Mapped[int | None] = mapped_column(ForeignKey("book_pages.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="book")  # book/pending/global/rejected
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class OcrPageJob(Base):
    __tablename__ = "ocr_page_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("recognition_jobs.id"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("book_pages.id"), index=True)
    image_sha256: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(64), default="PaddleOCR-VL-1.6")
    params_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    provider_job_id: Mapped[str] = mapped_column(String(120), default="")
    raw_path: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_workflow_template_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("workflow_templates.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    graph_json: Mapped[str] = mapped_column(Text, default='{"nodes":[],"edges":[]}')
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class BookWorkflowRun(Base):
    __tablename__ = "book_workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), unique=True, index=True)
    workflow_version_id: Mapped[int] = mapped_column(ForeignKey("workflow_versions.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    pending_version_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_versions.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class WorkflowNodeRun(Base):
    __tablename__ = "workflow_node_runs"
    __table_args__ = (UniqueConstraint("run_id", "node_key", name="uq_workflow_run_node"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("book_workflow_runs.id"), index=True)
    node_key: Mapped[str] = mapped_column(String(80), index=True)
    node_type: Mapped[str] = mapped_column(String(40), index=True)
    label: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(24), default="system")
    status: Mapped[str] = mapped_column(String(24), default="blocked", index=True)
    completed_pages: Mapped[int] = mapped_column(Integer, default=0)
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class WorkflowPageTask(Base):
    __tablename__ = "workflow_page_tasks"
    __table_args__ = (UniqueConstraint("node_run_id", "page_id", name="uq_workflow_node_page"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("book_workflow_runs.id"), index=True)
    node_run_id: Mapped[int] = mapped_column(ForeignKey("workflow_node_runs.id"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("book_pages.id"), index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="blocked", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    page_no: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    dpi: Mapped[int] = mapped_column(Integer, default=300)
    source_pdf: Mapped[str] = mapped_column(String(500), default="")
    image_path: Mapped[str] = mapped_column(String(500), default="")
    cached: Mapped[bool] = mapped_column(Boolean, default=False)


class PageSegment(Base):
    __tablename__ = "page_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[str] = mapped_column(String(32), index=True)
    segment_no: Mapped[int] = mapped_column(Integer, index=True)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    rule_version: Mapped[str] = mapped_column(String(40), default="vertical-rule-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class EntityType(Base):
    __tablename__ = "entity_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    color: Mapped[str] = mapped_column(String(16), default="#2563eb")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entity_types.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="draft")
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    user: Mapped[User] = relationship(back_populates="annotations")
    entity: Mapped[EntityType] = relationship()


class AnnotationRevision(Base):
    __tablename__ = "annotation_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    annotation_id: Mapped[int] = mapped_column(ForeignKey("annotations.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(32))
    snapshot_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Guideline(Base):
    __tablename__ = "guidelines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    scope: Mapped[str] = mapped_column(String(240), default="全平台")
    examples_json: Mapped[str] = mapped_column(Text, default="[]")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    imported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source_user_id: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# Semantic annotation, quality control and integrated knowledge-graph models.
# JSON payloads intentionally remain Text on SQLite so the same public contract can
# later be migrated to PostgreSQL JSONB without changing the API.
class SemanticProviderSetting(Base):
    __tablename__ = "semantic_provider_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    model: Mapped[str] = mapped_column(String(160), default="")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class OntologyType(Base):
    __tablename__ = "ontology_types"
    __table_args__ = (UniqueConstraint("book_id", "kind", "code", name="uq_ontology_book_kind_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)  # entity/relation
    code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(160))
    color: Mapped[str] = mapped_column(String(16), default="#2563eb")
    description: Mapped[str] = mapped_column(Text, default="")
    source_types_json: Mapped[str] = mapped_column(Text, default="[]")
    target_types_json: Mapped[str] = mapped_column(Text, default="[]")
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class TextUnit(Base):
    __tablename__ = "text_units"
    __table_args__ = (UniqueConstraint("book_id", "stable_id", name="uq_text_unit_book_stable"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("book_pages.id"), nullable=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("text_units.id"), nullable=True, index=True)
    stable_id: Mapped[str] = mapped_column(String(120), index=True)
    unit_type: Mapped[str] = mapped_column(String(32), default="article", index=True)
    title: Mapped[str] = mapped_column(String(240), default="")
    order_no: Mapped[int] = mapped_column(Integer, default=1)
    source_page: Mapped[str] = mapped_column(String(80), default="")
    original_text: Mapped[str] = mapped_column(Text, default="")
    normalized_text: Mapped[str] = mapped_column(Text, default="")
    text_type: Mapped[str] = mapped_column(String(32), default="article")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class SemanticEntity(Base):
    __tablename__ = "semantic_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text_unit_id: Mapped[int] = mapped_column(ForeignKey("text_units.id"), index=True)
    assignment_id: Mapped[int | None] = mapped_column(ForeignKey("page_assignments.id"), nullable=True, index=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("ontology_types.id"), index=True)
    canonical_name: Mapped[str] = mapped_column(String(240), index=True)
    surface_text: Mapped[str] = mapped_column(String(500), default="")
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    bbox_json: Mapped[str] = mapped_column(Text, default="[]")
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    attributes_json: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[str] = mapped_column(String(24), default="manual", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1)
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class SemanticRelation(Base):
    __tablename__ = "semantic_relations"
    __table_args__ = (UniqueConstraint("assignment_id", "type_id", "source_entity_id", "target_entity_id", name="uq_semantic_relation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text_unit_id: Mapped[int] = mapped_column(ForeignKey("text_units.id"), index=True)
    assignment_id: Mapped[int | None] = mapped_column(ForeignKey("page_assignments.id"), nullable=True, index=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("ontology_types.id"), index=True)
    source_entity_id: Mapped[int] = mapped_column(ForeignKey("semantic_entities.id"), index=True)
    target_entity_id: Mapped[int] = mapped_column(ForeignKey("semantic_entities.id"), index=True)
    evidence_text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(24), default="manual")
    confidence: Mapped[float] = mapped_column(Float, default=1)
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MedicalCase(Base):
    __tablename__ = "medical_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text_unit_id: Mapped[int] = mapped_column(ForeignKey("text_units.id"), index=True)
    assignment_id: Mapped[int | None] = mapped_column(ForeignKey("page_assignments.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(500), default="")
    doctor: Mapped[str] = mapped_column(String(240), default="", index=True)
    disease: Mapped[str] = mapped_column(String(240), default="", index=True)
    symptoms: Mapped[str] = mapped_column(Text, default="")
    diagnosis: Mapped[str] = mapped_column(Text, default="")
    syndrome: Mapped[str] = mapped_column(String(500), default="", index=True)
    treatment: Mapped[str] = mapped_column(String(500), default="")
    formula: Mapped[str] = mapped_column(String(500), default="", index=True)
    medicines: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PlatformJob(Base):
    __tablename__ = "platform_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), index=True)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"), nullable=True, index=True)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("book_pages.id"), nullable=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(160), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class AdjudicationRecord(Base):
    __tablename__ = "adjudication_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("book_pages.id"), index=True)
    assignment_a_id: Mapped[int] = mapped_column(ForeignKey("page_assignments.id"), index=True)
    assignment_b_id: Mapped[int] = mapped_column(ForeignKey("page_assignments.id"), index=True)
    expert_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    decision_json: Mapped[str] = mapped_column(Text, default="{}")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AiFeedback(Base):
    __tablename__ = "ai_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("platform_jobs.id"), nullable=True, index=True)
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("semantic_entities.id"), nullable=True)
    relation_id: Mapped[int | None] = mapped_column(ForeignKey("semantic_relations.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(24), index=True)
    before_json: Mapped[str] = mapped_column(Text, default="{}")
    after_json: Mapped[str] = mapped_column(Text, default="{}")
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (UniqueConstraint("book_id", "type_code", "canonical_name", name="uq_graph_node"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    type_code: Mapped[str] = mapped_column(String(64), index=True)
    canonical_name: Mapped[str] = mapped_column(String(240), index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (UniqueConstraint("book_id", "type_code", "source_node_id", "target_node_id", name="uq_graph_edge"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    type_code: Mapped[str] = mapped_column(String(64), index=True)
    source_node_id: Mapped[int] = mapped_column(ForeignKey("graph_nodes.id"), index=True)
    target_node_id: Mapped[int] = mapped_column(ForeignKey("graph_nodes.id"), index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
