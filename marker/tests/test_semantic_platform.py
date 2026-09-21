from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from marker.backend.database import Base
from marker.backend.models import (
    Book, BookPage, GraphEdge, GraphNode, OntologyType, PageAssignment,
    SemanticEntity, SemanticRelation, TextUnit, User,
)
from marker.backend.semantic_api import (
    _agreement, build_graph, semantic_export, seed_ontology,
)


def _fixture(db: Session):
    admin = User(username="admin", password_hash="x", role="admin", display_name="管理员", is_active=True)
    a = User(username="a", password_hash="x", role="annotator", display_name="甲", is_active=True)
    b = User(username="b", password_hash="x", role="annotator", display_name="乙", is_active=True)
    db.add_all([admin, a, b]); db.flush()
    book = Book(title="测试医籍", created_by=admin.id, status="ready", page_count=1)
    db.add(book); db.flush()
    page = BookPage(book_id=book.id, page_no=1, page_id="test-page-1", width=1000, height=1400)
    db.add(page); db.flush()
    aa = PageAssignment(book_id=book.id, page_id=page.id, user_id=a.id, status="submitted")
    ab = PageAssignment(book_id=book.id, page_id=page.id, user_id=b.id, status="submitted")
    db.add_all([aa, ab]); db.flush()
    unit = TextUnit(book_id=book.id, page_id=page.id, stable_id="B1-P1-U1", unit_type="case", title="医案一",
                    original_text="张氏治中风用小续命汤。", normalized_text="张氏治中风用小续命汤。", source_page="1", status="approved")
    db.add(unit); db.commit()
    seed_ontology(db, book.id)
    return admin, a, b, book, page, aa, ab, unit


def test_double_annotation_agreement_matches_semantic_relation_not_database_ids():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _, a, b, book, _, aa, ab, unit = _fixture(db)
        doctor = db.query(OntologyType).filter_by(book_id=book.id, code="doctor").one()
        disease = db.query(OntologyType).filter_by(book_id=book.id, code="disease").one()
        treats = db.query(OntologyType).filter_by(book_id=book.id, code="treats").one()
        rows = []
        for assignment, user in ((aa, a), (ab, b)):
            e1 = SemanticEntity(text_unit_id=unit.id, assignment_id=assignment.id, type_id=doctor.id, canonical_name="张氏", surface_text="张氏", start_offset=0, end_offset=2, created_by=user.id)
            e2 = SemanticEntity(text_unit_id=unit.id, assignment_id=assignment.id, type_id=disease.id, canonical_name="中风", surface_text="中风", start_offset=3, end_offset=5, created_by=user.id)
            db.add_all([e1, e2]); db.flush()
            rows.append(SemanticRelation(text_unit_id=unit.id, assignment_id=assignment.id, type_id=treats.id, source_entity_id=e1.id, target_entity_id=e2.id, created_by=user.id))
        db.add_all(rows); db.commit()
        metrics = _agreement(db, aa.id, ab.id)
        assert metrics["f1"] == 1
        assert metrics["relation_f1"] == 1
        assert metrics["kappa"] == 1


def test_approved_semantics_build_traceable_graph_and_v3_export():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin, a, _, book, _, aa, _, unit = _fixture(db)
        doctor = db.query(OntologyType).filter_by(book_id=book.id, code="doctor").one()
        disease = db.query(OntologyType).filter_by(book_id=book.id, code="disease").one()
        treats = db.query(OntologyType).filter_by(book_id=book.id, code="treats").one()
        source = SemanticEntity(text_unit_id=unit.id, assignment_id=aa.id, type_id=doctor.id, canonical_name="张氏", surface_text="张氏", start_offset=0, end_offset=2, status="approved", created_by=a.id)
        target = SemanticEntity(text_unit_id=unit.id, assignment_id=aa.id, type_id=disease.id, canonical_name="中风", surface_text="中风", start_offset=3, end_offset=5, status="approved", created_by=a.id)
        db.add_all([source, target]); db.flush()
        db.add(SemanticRelation(text_unit_id=unit.id, assignment_id=aa.id, type_id=treats.id, source_entity_id=source.id, target_entity_id=target.id, evidence_text="张氏治中风", status="approved", created_by=a.id)); db.commit()

        result = build_graph(book.id, admin, db)
        assert result["result"] == {"nodes": 2, "edges": 1}
        assert db.query(GraphNode).count() == 2
        assert db.query(GraphEdge).one().evidence_count == 1

        exported = semantic_export(book.id, admin, db)
        assert exported["schema_version"] == "3.0"
        assert len(exported["entities"]) == 2
        assert exported["knowledge_graph"]["edges"][0]["evidence"][0]["text"] == "张氏治中风"


def test_draft_semantics_are_excluded_from_graph():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin, a, _, book, _, aa, _, unit = _fixture(db)
        doctor = db.query(OntologyType).filter_by(book_id=book.id, code="doctor").one()
        db.add(SemanticEntity(text_unit_id=unit.id, assignment_id=aa.id, type_id=doctor.id, canonical_name="未审核医家", surface_text="张氏", start_offset=0, end_offset=2, status="draft", created_by=a.id)); db.commit()
        result = build_graph(book.id, admin, db)
        assert result["result"] == {"nodes": 0, "edges": 0}
