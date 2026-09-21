from __future__ import annotations

from pathlib import Path
from threading import Lock

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from .database import DATA_DIR, SessionLocal
from .models import OcrProviderSetting
from .platform_config import is_test_mode
from .settings import settings


_KEY_PATH = DATA_DIR / ".ocr-settings.key"
_KEY_LOCK = Lock()


def _cipher() -> Fernet:
    with _KEY_LOCK:
        if not _KEY_PATH.exists():
            key = Fernet.generate_key()
            temporary = Path(f"{_KEY_PATH}.tmp")
            temporary.write_bytes(key)
            temporary.replace(_KEY_PATH)
        return Fernet(_KEY_PATH.read_bytes().strip())


def _decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, OSError):
        return ""


def effective_ocr_config(db: Session | None = None) -> dict[str, str]:
    """测试模式开启时优先使用根目录 .env 的真实测试凭据，否则使用数据库中的正式配置。"""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        if is_test_mode(session) and settings.test_ocr_token:
            return {
                "provider": "paddleocr",
                "access_token": settings.test_ocr_token,
                "base_url": settings.test_ocr_base_url or settings.paddleocr_base_url,
                "model": settings.test_ocr_model or settings.paddleocr_model,
            }
        row = session.get(OcrProviderSetting, 1)
        if not row:
            return {
                "provider": "paddleocr",
                "access_token": settings.paddleocr_access_token,
                "base_url": settings.paddleocr_base_url,
                "model": settings.paddleocr_model,
            }
        return {
            "provider": row.provider,
            "access_token": _decrypt(row.access_token_encrypted),
            "base_url": row.base_url or settings.paddleocr_base_url,
            "model": row.model or settings.paddleocr_model,
        }
    finally:
        if owns_session:
            session.close()


def public_ocr_config(db: Session) -> dict[str, object]:
    config = effective_ocr_config(db)
    token = config["access_token"]
    return {
        "provider": config["provider"],
        "configured": bool(token),
        "token_hint": f"••••{token[-4:]}" if token else "",
        "base_url": config["base_url"],
        "model": config["model"],
    }


def save_ocr_config(
    db: Session,
    *,
    access_token: str | None,
    clear_access_token: bool,
    base_url: str,
    model: str,
    updated_by: int,
) -> dict[str, object]:
    row = db.get(OcrProviderSetting, 1)
    if not row:
        row = OcrProviderSetting(id=1)
        db.add(row)
    if clear_access_token:
        row.access_token_encrypted = ""
    elif access_token:
        row.access_token_encrypted = _cipher().encrypt(access_token.encode("utf-8")).decode("ascii")
    elif not row.access_token_encrypted and settings.paddleocr_access_token:
        row.access_token_encrypted = _cipher().encrypt(settings.paddleocr_access_token.encode("utf-8")).decode("ascii")
    row.provider = "paddleocr"
    row.base_url = base_url.strip()
    row.model = model.strip()
    row.updated_by = updated_by
    db.commit()
    db.refresh(row)
    return public_ocr_config(db)
