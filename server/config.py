"""Runtime configuration for the DuCO Agent platform.

Secrets and deployment knobs come from the environment. The defaults are a
clearly labelled local prototype: SQLite on disk, local document storage and
the in-process mock insurer API. Nothing here is a production secret.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DUCO_DATA_DIR", ROOT / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
AUDIO_DIR = DATA_DIR / "audio"
FRONTEND_DIST = ROOT / "web" / "dist"

for _path in (DATA_DIR, UPLOAD_DIR, REPORT_DIR, AUDIO_DIR):
    _path.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get(
    "DUCO_DATABASE_URL",
    f"sqlite:///{(DATA_DIR / 'duco.db').as_posix()}",
)
JWT_SECRET = os.environ.get("DUCO_JWT_SECRET", "dev-only-change-me-in-production")
JWT_ALGORITHM = "HS256"
TOKEN_TTL_HOURS = int(os.environ.get("DUCO_TOKEN_TTL_HOURS", "12"))
MAX_UPLOAD_BYTES = int(os.environ.get("DUCO_MAX_UPLOAD_MB", "15")) * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".txt", ".mp3", ".m4a", ".wav"}
ALLOWED_MIME = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/tiff",
    "text/plain",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
}
DEMO_MODE = os.environ.get("DUCO_DEMO_MODE", "1") == "1"
ENVIRONMENT = os.environ.get("DUCO_ENV", "local-prototype")
MOCK_INSURERS_LABEL = "SIMULATED — mock insurer sandbox, not a real approval"
LLM_ENABLED = bool(os.environ.get("DUCO_LLM_API_KEY"))
LLM_MODEL = os.environ.get("DUCO_LLM_MODEL", "gpt-4o-mini")
LLM_BASE_URL = os.environ.get("DUCO_LLM_BASE_URL", "https://api.openai.com/v1")
TTS_ENABLED = os.environ.get("DUCO_TTS", "1") == "1"
