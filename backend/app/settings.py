from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os


@dataclass(frozen=True)
class Settings:
    db_path: Path
    db_url: str | None
    cors_allow_origins: list[str]


def load_settings() -> Settings:
    load_dotenv()

    db_url = os.getenv("DT_DB_URL")
    db_path = Path(os.getenv("DT_DB_PATH", str(Path(__file__).resolve().parents[1] / "data" / "telemetry.db")))
    cors = os.getenv("DT_CORS_ALLOW_ORIGINS", "http://localhost:3000")
    cors_allow_origins = [o.strip() for o in cors.split(",") if o.strip()]

    return Settings(db_path=db_path, db_url=db_url, cors_allow_origins=cors_allow_origins)
