from io import BytesIO

import fitz
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from marker.backend import main
from marker.backend.database import Base
from marker.backend.models import Book, User


def _pdf_bytes(page_count: int = 2) -> bytes:
    document = fitz.open()
    for _ in range(page_count):
        document.new_page(width=120, height=160)
    payload = document.tobytes()
    document.close()
    return payload


def test_create_book_returns_before_page_rendering(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    started: list[tuple[object, tuple[object, ...]]] = []

    class DeferredThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args

        def start(self):
            started.append((self.target, self.args))

    def temporary_book_dir(book_id: int):
        path = tmp_path / "books" / str(book_id)
        (path / "pages").mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(main, "Thread", DeferredThread)
    monkeypatch.setattr(main, "book_dir", temporary_book_dir)

    with Session(engine) as db:
        admin = User(username="admin", password_hash="x", role="admin", display_name="管理员", is_active=True)
        db.add(admin)
        db.commit()
        db.refresh(admin)
        upload = UploadFile(filename="sample.pdf", file=BytesIO(_pdf_bytes()))
        result = main.create_book(admin, db, upload, "", "测试上传")
        book = db.get(Book, result["id"])

        assert result["status"] == "processing"
        assert result["page_count"] == 2
        assert book is not None
        assert book.pdf_path.endswith("source.pdf")
        assert len(started) == 1
        assert started[0][0] is main.process_uploaded_book

        upload_key = started[0][1][1]
        with main.ACTIVE_UPLOADS_LOCK:
            main.ACTIVE_UPLOADS.discard(upload_key)
