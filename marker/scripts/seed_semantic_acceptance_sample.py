"""Create one clearly marked, non-historical acceptance sample in the first book."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from marker.backend.database import SessionLocal
from marker.backend.models import Guideline, MedicalCase, OntologyType, SemanticEntity, SemanticRelation, TextUnit, User, Book, BookPage
from marker.backend.semantic_api import build_graph, seed_ontology


SAMPLE_ID = "ACCEPTANCE-SAMPLE-NON-HISTORICAL"


def main() -> None:
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.role == "admin").order_by(User.id).first()
        book = db.query(Book).order_by(Book.id).first()
        if not admin or not book:
            raise RuntimeError("需要至少一名管理员和一本书")
        page = db.query(BookPage).filter(BookPage.book_id == book.id).order_by(BookPage.page_no).first()
        unit = db.query(TextUnit).filter(TextUnit.book_id == book.id, TextUnit.stable_id == SAMPLE_ID).first()
        if unit:
            print(f"sample-exists:{unit.id}")
            return
        seed_ontology(db, book.id)
        text = "验收示例医家甲治疾病甲，采用治法甲并使用方剂甲，病情改善。"
        unit = TextUnit(book_id=book.id, page_id=page.id if page else None, stable_id=SAMPLE_ID, unit_type="case",
                        title="系统验收示例（非真实史料）", order_no=999999, source_page=str(page.page_no if page else ""),
                        original_text=text, normalized_text=text, text_type="case", status="approved", updated_by=admin.id)
        db.add(unit); db.flush()
        types = {x.code: x for x in db.query(OntologyType).filter(OntologyType.book_id == book.id).all()}
        specs = [("doctor", "医家甲"), ("disease", "疾病甲"), ("treatment", "治法甲"), ("formula", "方剂甲")]
        entities = {}
        for code, value in specs:
            start = text.index(value)
            row = SemanticEntity(text_unit_id=unit.id, type_id=types[code].id, canonical_name=value, surface_text=value,
                                 start_offset=start, end_offset=start + len(value), source="manual", confidence=1,
                                 status="approved", created_by=admin.id, attributes_json=json.dumps({"sample": True}))
            db.add(row); db.flush(); entities[code] = row
        for relation_code, source_code, target_code, evidence in (
            ("treats", "doctor", "disease", "医家甲治疾病甲"),
            ("uses", "doctor", "formula", "医家甲使用方剂甲"),
        ):
            db.add(SemanticRelation(text_unit_id=unit.id, type_id=types[relation_code].id,
                                    source_entity_id=entities[source_code].id, target_entity_id=entities[target_code].id,
                                    evidence_text=evidence, source="manual", confidence=1, status="approved", created_by=admin.id))
        db.add(MedicalCase(text_unit_id=unit.id, source="系统验收示例（非真实史料）", doctor="医家甲", disease="疾病甲",
                           symptoms="症状甲", diagnosis="示例诊断", syndrome="证候甲", treatment="治法甲", formula="方剂甲",
                           medicines="药物甲", outcome="病情改善", note="仅用于验证平台闭环，不得作为史料引用。",
                           status="approved", created_by=admin.id))
        if not db.query(Guideline).filter(Guideline.title == "孟河医派语义标注验收规范").first():
            db.add(Guideline(title="孟河医派语义标注验收规范", content="标注须对应原文证据；实体边界准确；关系方向明确；不确定项必须标记并提交专家裁决。",
                             version=1, status="published", scope="语义实体、关系与医案", examples_json=json.dumps([{"kind":"example","text":"示例仅用于演示数据结构，不代表真实史料。"}], ensure_ascii=False),
                             is_active=True, sort_order=1, published_at=datetime.now(timezone.utc)))
        db.commit()
        result = build_graph(book.id, admin, db)
        print(json.dumps({"text_unit_id": unit.id, "graph": result["result"]}, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
