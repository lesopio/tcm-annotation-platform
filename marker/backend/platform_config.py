from __future__ import annotations

from sqlalchemy.orm import Session

from .models import PlatformSetting
from .settings import settings


def is_test_mode(db: Session) -> bool:
    """全站测试模式：开启后 OCR 与语义模型改用根目录 .env 中的真实测试凭据调用。"""
    row = db.get(PlatformSetting, 1)
    return bool(row and row.test_mode)


def set_test_mode(db: Session, enabled: bool, updated_by: int) -> dict[str, object]:
    row = db.get(PlatformSetting, 1)
    if not row:
        row = PlatformSetting(id=1)
        db.add(row)
    row.test_mode = bool(enabled)
    row.updated_by = updated_by
    db.commit()
    return public_platform_setting(db)


def public_platform_setting(db: Session) -> dict[str, object]:
    row = db.get(PlatformSetting, 1)
    return {
        "test_mode": bool(row and row.test_mode),
        "test_env_ready": bool(settings.test_ocr_token and settings.test_semantic_api_key),
    }
