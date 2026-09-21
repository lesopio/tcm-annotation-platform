from __future__ import annotations

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock, Thread

import fitz
from PIL import Image
from sqlalchemy.orm import Session

from .database import PAGE_IMAGE_DIR, PDF_PATH, SessionLocal
from .models import Page
from .settings import settings

CACHE_JOB = {
    "running": False,
    "current": 0,
    "total": 0,
    "cached": 0,
    "error": "",
}
CACHE_JOB_LOCK = Lock()


def cleanup_temp_files() -> int:
    removed = 0
    for tmp in PAGE_IMAGE_DIR.glob("*.tmp.*"):
        try:
            tmp.unlink()
            removed += 1
        except OSError:
            pass
    for tmp in PAGE_IMAGE_DIR.glob("*.tmp"):
        try:
            tmp.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def page_image_path(page_id: str) -> Path:
    return PAGE_IMAGE_DIR / f"{page_id}.png"


def render_page_file(page_no: int, page_id: str) -> tuple[int, int, str]:
    target = page_image_path(page_id)
    if not target.exists() or target.stat().st_size <= 0:
        if not PDF_PATH.exists():
            raise FileNotFoundError(f"PDF 不存在: {PDF_PATH}")
        doc = fitz.open(PDF_PATH)
        try:
            pdf_page = doc.load_page(page_no - 1)
            matrix = fitz.Matrix(settings.render_dpi / 72, settings.render_dpi / 72)
            pixmap = pdf_page.get_pixmap(matrix=matrix, alpha=False)
            fd, tmp_name = tempfile.mkstemp(dir=PAGE_IMAGE_DIR, suffix=".png")
            os.close(fd)
            temp = Path(tmp_name)
            try:
                pixmap.save(str(temp))
                temp.replace(target)
            except BaseException:
                temp.unlink(missing_ok=True)
                raise
        finally:
            doc.close()

    with Image.open(target) as img:
        width, height = img.size
    return width, height, str(target)


def render_page(db: Session, page_no: int) -> Page:
    page = db.query(Page).filter(Page.page_no == page_no).first()
    if not page:
        raise ValueError(f"页面不存在: {page_no}")

    page.width, page.height, page.image_path = render_page_file(page_no, page.page_id)
    page.cached = True
    db.commit()
    db.refresh(page)
    return page


def ensure_cache_window(db: Session, center_page_no: int) -> None:
    half = max(1, settings.cache_window // 2)
    start = max(1, center_page_no - half)
    end = center_page_no + half - 1
    for page_no in range(start, end + 1):
        page = db.query(Page).filter(Page.page_no == page_no).first()
        if page and (not Path(page.image_path).exists() or Path(page.image_path).stat().st_size <= 0):
            render_page(db, page_no)


def cache_all_pages_worker() -> None:
    db = SessionLocal()
    try:
        pages = db.query(Page).order_by(Page.page_no).all()
        missing_pages = [
            page
            for page in pages
            if not page_image_path(page.page_id).exists() or page_image_path(page.page_id).stat().st_size <= 0
        ]
        with CACHE_JOB_LOCK:
            CACHE_JOB.update(
                {
                    "running": True,
                    "current": 0,
                    "total": len(pages),
                    "cached": len(pages) - len(missing_pages),
                    "error": "",
                }
            )

        max_workers = max(1, settings.cache_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(render_page_file, page.page_no, page.page_id): page.page_no
                for page in missing_pages
            }
            for future in as_completed(futures):
                page_no = futures[future]
                width, height, image_path = future.result()
                page = db.query(Page).filter(Page.page_no == page_no).first()
                if page:
                    page.width = width
                    page.height = height
                    page.image_path = image_path
                    page.cached = True
                    db.commit()
                with CACHE_JOB_LOCK:
                    CACHE_JOB["current"] = page_no
                    CACHE_JOB["cached"] += 1

        with CACHE_JOB_LOCK:
            CACHE_JOB["running"] = False
    except Exception as exc:  # pragma: no cover - surfaced through status endpoint
        with CACHE_JOB_LOCK:
            CACHE_JOB.update({"running": False, "error": str(exc)})
    finally:
        db.close()


def start_cache_all_pages() -> dict:
    with CACHE_JOB_LOCK:
        if CACHE_JOB["running"]:
            return dict(CACHE_JOB)
        CACHE_JOB.update({"running": True, "current": 0, "total": 0, "cached": 0, "error": ""})
    thread = Thread(target=cache_all_pages_worker, daemon=True)
    thread.start()
    return cache_all_status()


def cache_all_status() -> dict:
    with CACHE_JOB_LOCK:
        return dict(CACHE_JOB)
