from __future__ import annotations

import json

from .models import (
    Annotation,
    Book,
    BookEntity,
    BookPage,
    CharacterEntry,
    EntityAnnotation,
    EntityType,
    Guideline,
    LayoutRegion,
    LabelDefinition,
    OcrPageJob,
    Page,
    PageAssignment,
    PageSegment,
    RecognitionJob,
    TextChar,
    TextLine,
    User,
    WorkflowRevision,
)


def user_out(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
        "is_active": user.is_active,
        "is_ai_expert": getattr(user, "is_ai_expert", False),
    }


def page_out(page: Page) -> dict:
    return {
        "id": page.id,
        "page_id": page.page_id,
        "page_no": page.page_no,
        "width": page.width,
        "height": page.height,
        "dpi": page.dpi,
        "source_pdf": page.source_pdf,
        "cached": page.cached,
        "image_url": f"/api/pages/{page.page_no}/image",
    }


def page_segment_out(segment: PageSegment) -> dict:
    return {
        "id": segment.id,
        "page_id": segment.page_id,
        "segment_no": segment.segment_no,
        "bbox": [segment.x1, segment.y1, segment.x2, segment.y2],
        "rule_version": segment.rule_version,
        "created_at": segment.created_at.isoformat(),
    }


def entity_out(entity: EntityType) -> dict:
    return {
        "id": entity.id,
        "name": entity.name,
        "color": entity.color,
        "description": entity.description,
        "is_active": entity.is_active,
    }


def guideline_out(item: Guideline) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "content": item.content,
        "sort_order": item.sort_order,
        "is_active": item.is_active,
        "version": item.version,
        "status": item.status,
        "scope": item.scope,
        "examples": json.loads(item.examples_json or "[]"),
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "updated_at": item.updated_at.isoformat(),
    }


def annotation_out(annotation: Annotation) -> dict:
    return {
        "id": annotation.id,
        "page_id": annotation.page_id,
        "entity_id": annotation.entity_id,
        "entity_name": annotation.entity.name if annotation.entity else "",
        "color": annotation.entity.color if annotation.entity else "#2563eb",
        "user_id": annotation.user_id,
        "username": annotation.user.username if annotation.user else "",
        "bbox": [annotation.x1, annotation.y1, annotation.x2, annotation.y2],
        "note": annotation.note,
        "status": annotation.status,
        "is_deleted": annotation.is_deleted,
        "created_at": annotation.created_at.isoformat(),
        "updated_at": annotation.updated_at.isoformat(),
    }


def book_out(book: Book) -> dict:
    return {
        "id": book.id,
        "title": book.title,
        "task_prompt": book.task_prompt,
        "status": book.status,
        "page_count": book.page_count,
        "created_by": book.created_by,
        "created_at": book.created_at.isoformat(),
        "updated_at": book.updated_at.isoformat(),
    }


def book_page_out(page: BookPage) -> dict:
    return {
        "id": page.id,
        "book_id": page.book_id,
        "page_no": page.page_no,
        "page_id": page.page_id,
        "width": page.width,
        "height": page.height,
        "dpi": page.dpi,
        "recognition_status": page.recognition_status,
        "image_url": f"/api/book-pages/{page.id}/image",
    }


def book_entity_out(entity: BookEntity) -> dict:
    return {
        "id": entity.id,
        "book_id": entity.book_id,
        "code": entity.code,
        "name": entity.name,
        "color": entity.color,
        "description": entity.description,
        "is_active": entity.is_active,
    }


def assignment_out(item: PageAssignment) -> dict:
    return {
        "id": item.id,
        "book_id": item.book_id,
        "page_id": item.page_id,
        "page_no": item.page.page_no if item.page else 0,
        "user_id": item.user_id,
        "username": item.user.username if item.user else "",
        "status": item.status,
        "current_step": item.current_step,
        "version": getattr(item, "version", 1),
        "review_comment": item.review_comment,
        "submitted_at": item.submitted_at.isoformat() if item.submitted_at else None,
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def layout_region_out(item: LayoutRegion) -> dict:
    return {
        "id": item.id,
        "assignment_id": item.assignment_id,
        "region_type": item.region_type,
        "label_id": getattr(item, "label_id", None),
        "order_no": item.order_no,
        "bbox": [item.x1, item.y1, item.x2, item.y2],
        "confirmed": item.confirmed,
    }


def text_line_out(item: TextLine) -> dict:
    return {
        "id": item.id,
        "assignment_id": item.assignment_id,
        "region_id": getattr(item, "region_id", None),
        "layout_label_id": getattr(item, "layout_label_id", None),
        "stratum_label_id": getattr(item, "stratum_label_id", None),
        "order_no": item.order_no,
        "bbox": [item.x1, item.y1, item.x2, item.y2],
        "char_size": item.char_size,
        "confirmed": item.confirmed,
        "needs_char_split": getattr(item, "needs_char_split", False),
        "ocr_text": getattr(item, "ocr_text", ""),
    }


def text_char_out(item: TextChar) -> dict:
    try:
        candidates = json.loads(item.candidates_json or "[]")
    except json.JSONDecodeError:
        candidates = []
    return {
        "id": item.id,
        "assignment_id": item.assignment_id,
        "line_id": item.line_id,
        "custom_char_id": getattr(item, "custom_char_id", None),
        "order_no": item.order_no,
        "bbox": [item.x1, item.y1, item.x2, item.y2],
        "raw_text": item.raw_text,
        "corrected_text": item.corrected_text,
        "candidates": candidates,
        "confidence": item.confidence,
        "status": item.status,
    }


def entity_annotation_out(item: EntityAnnotation) -> dict:
    return {
        "id": item.id,
        "assignment_id": item.assignment_id,
        "entity_id": item.entity_id,
        "entity_code": item.entity.code if item.entity else "",
        "entity_name": item.entity.name if item.entity else "",
        "color": item.entity.color if item.entity else "#2563eb",
        "bbox": [item.x1, item.y1, item.x2, item.y2],
        "note": item.note,
    }


def recognition_job_out(item: RecognitionJob) -> dict:
    return {
        "id": item.id,
        "book_id": item.book_id,
        "status": item.status,
        "current_page": item.current_page,
        "total_pages": item.total_pages,
        "error": item.error,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def label_definition_out(item: LabelDefinition) -> dict:
    return {
        "id": item.id, "book_id": item.book_id, "group": item.group,
        "code": item.code, "name": item.name, "color": item.color,
        "description": item.description, "sort_order": item.sort_order,
        "is_active": item.is_active,
    }


def character_entry_out(item: CharacterEntry) -> dict:
    return {
        "id": item.id, "book_id": item.book_id,
        "unicode_codepoint": item.unicode_codepoint, "character": item.character,
        "ids": item.ids, "radical": item.radical, "strokes": item.strokes,
        "readings": item.readings, "aliases": item.aliases,
        "glyph_url": f"/api/characters/{item.id}/glyph" if item.glyph_path else "",
        "source_page_id": item.source_page_id, "status": item.status,
        "created_by": item.created_by, "reviewed_by": item.reviewed_by,
        "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat(),
    }


def workflow_revision_out(item: WorkflowRevision) -> dict:
    return {
        "id": item.id, "assignment_id": item.assignment_id,
        "version": item.version, "actor_id": item.actor_id,
        "action": item.action, "created_at": item.created_at.isoformat(),
    }


def ocr_page_job_out(item: OcrPageJob) -> dict:
    return {
        "id": item.id, "batch_id": item.batch_id, "page_id": item.page_id,
        "image_sha256": item.image_sha256, "model": item.model,
        "status": item.status, "provider_job_id": item.provider_job_id,
        "error": item.error, "attempts": item.attempts,
        "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat(),
    }
