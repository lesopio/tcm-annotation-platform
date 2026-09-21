from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import fitz
from PIL import Image
from sqlalchemy.orm import Session

from .auth import hash_password
from .database import CONFIG_DIR, EXPORT_DIR, IMPORT_DIR, PAGE_IMAGE_DIR, PDF_PATH
from .models import Guideline, Page, User
from .settings import settings


USERS_CONFIG = CONFIG_DIR / "users.json"
VIEWER_PAGE_DIR = Path(__file__).resolve().parents[2] / "viewer" / "public" / "bencao-output" / "preprocessed_pages"

_MAX_AGE_HOURS = 48


def ensure_users_config() -> None:
    if USERS_CONFIG.exists():
        return
    USERS_CONFIG.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "username": "admin",
                        "password": "admin123",
                        "role": "admin",
                        "display_name": "管理员",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def seed_users(db: Session) -> None:
    ensure_users_config()
    if db.query(User).count() > 0:
        return
    data = json.loads(USERS_CONFIG.read_text(encoding="utf-8"))
    for item in data.get("users", []):
        db.add(
            User(
                username=item["username"],
                password_hash=hash_password(item["password"]),
                role=item.get("role", "annotator"),
                display_name=item.get("display_name", item["username"]),
                is_active=True,
            )
        )
    db.commit()


def ensure_ai_user(db: Session) -> None:
    user = db.query(User).filter(User.username == "1111").first()
    if user:
        user.password_hash = hash_password("1111")
        user.role = "annotator"
        user.display_name = "AI专家"
        user.is_active = True
        user.is_ai_expert = True
    else:
        db.add(
            User(
                username="1111",
                password_hash=hash_password("1111"),
                role="annotator",
                display_name="AI专家",
                is_active=True,
                is_ai_expert=True,
            )
        )
    db.commit()


def ensure_demo_users(db: Session) -> None:
    defaults = [
        ("annotator", "annotator123", "annotator", "标注员"),
        ("reviewer", "reviewer123", "reviewer", "审核员"),
    ]
    for username, password, role, display_name in defaults:
        user = db.query(User).filter(User.username == username).first()
        if user:
            user.role = role
            user.display_name = display_name
            user.is_active = True
            continue
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role=role,
                display_name=display_name,
                is_active=True,
            )
        )
    db.commit()


def seed_guidelines(db: Session) -> None:
    if db.query(Guideline).count() > 0:
        return
    db.add(
        Guideline(
            title="标注提醒",
            content="请先在右侧选择实体类型，再在图像中右键拖拽生成标注框。标注框应尽量贴合实体影像边界。",
            sort_order=1,
            is_active=True,
        )
    )
    db.commit()


def ensure_pages(db: Session) -> None:
    if not PDF_PATH.exists():
        return
    existing = {p.page_no for p in db.query(Page.page_no).all()}
    doc = fitz.open(PDF_PATH)
    try:
        for index in range(doc.page_count):
            page_no = index + 1
            if page_no in existing:
                continue
            page = doc.load_page(index)
            rect = page.rect
            width = round(rect.width * settings.render_dpi / 72)
            height = round(rect.height * settings.render_dpi / 72)
            page_id = f"page_{page_no:04d}"
            image_path = str(PAGE_IMAGE_DIR / f"{page_id}.png")
            db.add(
                Page(
                    page_id=page_id,
                    page_no=page_no,
                    width=width,
                    height=height,
                    dpi=settings.render_dpi,
                    source_pdf=str(PDF_PATH),
                    image_path=image_path,
                    cached=Path(image_path).exists(),
                )
            )
        db.commit()
    finally:
        doc.close()


def copy_viewer_seed_images(db: Session) -> None:
    if not VIEWER_PAGE_DIR.exists():
        return
    for src in VIEWER_PAGE_DIR.glob("page_*_preprocessed.png"):
        page_id = src.name.replace("_preprocessed.png", "")
        dst = PAGE_IMAGE_DIR / f"{page_id}.png"
        if not dst.exists():
            shutil.copy2(src, dst)
        page = db.query(Page).filter(Page.page_id == page_id).first()
        if page:
            with Image.open(dst) as img:
                page.width, page.height = img.size
            page.image_path = str(dst)
            page.cached = True
    db.commit()


def cleanup_stale_exports() -> int:
    removed = 0
    cutoff = time.time() - _MAX_AGE_HOURS * 3600
    for directory in (EXPORT_DIR, IMPORT_DIR):
        if not directory.exists():
            continue
        for f in directory.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


def bootstrap(db: Session) -> None:
    seed_users(db)
    ensure_demo_users(db)
    ensure_ai_user(db)
    seed_guidelines(db)
    ensure_pages(db)
    copy_viewer_seed_images(db)
