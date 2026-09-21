from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PAGE_IMAGE_DIR = DATA_DIR / "page_images"
EXPORT_DIR = DATA_DIR / "exports"
IMPORT_DIR = DATA_DIR / "imports"
CONFIG_DIR = ROOT / "config"
PDF_PATH = ROOT.parent / "raw_book" / "经史证类备急本草一到十二.pdf"
DB_PATH = DATA_DIR / "bencao_vsr.sqlite3"

for directory in (DATA_DIR, PAGE_IMAGE_DIR, EXPORT_DIR, IMPORT_DIR, CONFIG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH.as_posix()}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
