from __future__ import annotations

from pathlib import Path
from threading import Lock

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from .database import DATA_DIR
from .models import SemanticProviderSetting


_KEY_PATH = DATA_DIR / ".semantic-settings.key"
_LOCK = Lock()


def _cipher() -> Fernet:
    with _LOCK:
        if not _KEY_PATH.exists():
            temporary = Path(f"{_KEY_PATH}.tmp")
            temporary.write_bytes(Fernet.generate_key())
            temporary.replace(_KEY_PATH)
        return Fernet(_KEY_PATH.read_bytes().strip())


def _decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, OSError):
        return ""


def effective_semantic_config(db: Session) -> dict[str, object]:
    """测试模式开启时优先使用根目录 .env 的真实测试凭据，否则使用数据库中的正式配置。"""
    from .platform_config import is_test_mode
    from .settings import settings

    if is_test_mode(db) and settings.test_semantic_api_key:
        return {
            "api_key": settings.test_semantic_api_key,
            "base_url": settings.test_semantic_base_url,
            "model": settings.test_semantic_model,
            "timeout_seconds": 180,
        }
    row = db.get(SemanticProviderSetting, 1)
    if not row:
        return {"api_key": "", "base_url": "", "model": "", "timeout_seconds": 120}
    return {
        "api_key": _decrypt(row.api_key_encrypted),
        "base_url": row.base_url,
        "model": row.model,
        "timeout_seconds": row.timeout_seconds,
    }


def public_semantic_config(db: Session) -> dict[str, object]:
    config = effective_semantic_config(db)
    key = str(config["api_key"])
    return {
        "configured": bool(key and config["base_url"] and config["model"]),
        "key_hint": f"••••{key[-4:]}" if key else "",
        "base_url": config["base_url"],
        "model": config["model"],
        "timeout_seconds": config["timeout_seconds"],
    }


def save_semantic_config(
    db: Session,
    *,
    api_key: str | None,
    clear_api_key: bool,
    base_url: str,
    model: str,
    timeout_seconds: int,
    updated_by: int,
) -> dict[str, object]:
    row = db.get(SemanticProviderSetting, 1)
    if not row:
        row = SemanticProviderSetting(id=1)
        db.add(row)
    if clear_api_key:
        row.api_key_encrypted = ""
    elif api_key:
        row.api_key_encrypted = _cipher().encrypt(api_key.encode("utf-8")).decode("ascii")
    row.base_url = base_url.strip().rstrip("/")
    row.model = model.strip()
    row.timeout_seconds = timeout_seconds
    row.updated_by = updated_by
    db.commit()
    return public_semantic_config(db)
