from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from marker.backend import main, ocr_config
from marker.backend.database import Base
from marker.backend.models import OcrProviderSetting, User


def test_admin_can_save_encrypted_ocr_settings(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(ocr_config, "_KEY_PATH", tmp_path / ".ocr-settings.key")

    with Session(engine) as db:
        admin = User(username="admin", password_hash="x", role="admin", display_name="管理员", is_active=True)
        db.add(admin)
        db.commit()
        db.refresh(admin)

        result = main.update_ocr_settings(
            main.OcrSettingsIn(
                access_token="secret-token-1234",
                base_url="https://ocr.example.test/api/",
                model="PaddleOCR-VL-1.6",
            ),
            admin,
            db,
        )
        stored = db.get(OcrProviderSetting, 1)

        assert result["configured"] is True
        assert result["token_hint"] == "••••1234"
        assert result["base_url"] == "https://ocr.example.test/api"
        assert stored is not None
        assert stored.access_token_encrypted != "secret-token-1234"
        assert "secret-token-1234" not in stored.access_token_encrypted
        assert ocr_config.effective_ocr_config(db)["access_token"] == "secret-token-1234"


def test_updating_non_secret_fields_preserves_existing_token(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(ocr_config, "_KEY_PATH", tmp_path / ".ocr-settings.key")

    with Session(engine) as db:
        admin = User(username="admin", password_hash="x", role="admin", display_name="管理员", is_active=True)
        db.add(admin)
        db.commit()
        db.refresh(admin)
        ocr_config.save_ocr_config(db, access_token="keep-me", clear_access_token=False, base_url="", model="old", updated_by=admin.id)
        ocr_config.save_ocr_config(db, access_token=None, clear_access_token=False, base_url="", model="new", updated_by=admin.id)

        config = ocr_config.effective_ocr_config(db)
        assert config["access_token"] == "keep-me"
        assert config["model"] == "new"
