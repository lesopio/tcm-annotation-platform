from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


try:
    load_dotenv(encoding="utf-8")
except UnicodeDecodeError:
    # 根目录 .env 可能由 Windows 记事本以 GBK 编码保存（如全角引号），回退解码避免阻塞启动。
    load_dotenv(encoding="gbk")


_DEFAULT_CORS = [
    "http://127.0.0.1:5174",
    "http://localhost:5174",
    "http://127.0.0.1:30080",
    "http://localhost:30080",
    "http://127.0.0.1:5175",
    "http://localhost:5175",
]


@dataclass(frozen=True)
class Settings:
    secret_key: str = os.getenv("BENCAO_SECRET_KEY", "change-this-bencao-vsr-secret")
    token_hours: int = int(os.getenv("BENCAO_TOKEN_HOURS", "24"))
    render_dpi: int = int(os.getenv("BENCAO_RENDER_DPI", "300"))
    cache_window: int = int(os.getenv("BENCAO_CACHE_WINDOW", "20"))
    cache_workers: int = int(os.getenv("BENCAO_CACHE_WORKERS", "8"))

    ocr_det_model: str = os.getenv("BENCAO_OCR_DET_MODEL", "")
    ocr_rec_model: str = os.getenv("BENCAO_OCR_REC_MODEL", "")
    recognizer: str = os.getenv("BENCAO_RECOGNIZER", "mock")
    vl_server_url: str = os.getenv("BENCAO_VL_SERVER_URL", "")
    v5_server_url: str = os.getenv("BENCAO_V5_SERVER_URL", "")
    paddleocr_access_token: str = os.getenv("PADDLEOCR_ACCESS_TOKEN", "")
    paddleocr_base_url: str = os.getenv("PADDLEOCR_BASE_URL", "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs")
    paddleocr_model: str = "PaddleOCR-VL-1.6"
    paddleocr_request_timeout: float = float(os.getenv("PADDLEOCR_REQUEST_TIMEOUT", "300"))
    paddleocr_poll_timeout: float = float(os.getenv("PADDLEOCR_POLL_TIMEOUT", "900"))

    # 全站测试模式凭据：开启测试模式后，OCR 与语义模型改用这些真实测试账号调用。
    test_ocr_base_url: str = os.getenv("BENCAO_TEST_OCR_BASE_URL", "")
    test_ocr_token: str = os.getenv("BENCAO_TEST_OCR_TOKEN", "")
    test_ocr_model: str = os.getenv("BENCAO_TEST_OCR_MODEL", "")
    test_semantic_base_url: str = os.getenv("BENCAO_TEST_SEMANTIC_BASE_URL", "")
    test_semantic_api_key: str = os.getenv("BENCAO_TEST_SEMANTIC_API_KEY", "")
    test_semantic_model: str = os.getenv("BENCAO_TEST_SEMANTIC_MODEL", "")

    cors_origins: list[str] = field(
        default_factory=lambda: (
            [o.strip() for o in os.getenv("BENCAO_CORS_ORIGINS", "").split(",") if o.strip()]
            if os.getenv("BENCAO_CORS_ORIGINS")
            else list(_DEFAULT_CORS)
        )
    )


settings = Settings()
