from __future__ import annotations

from dataclasses import dataclass

from dotenv import load_dotenv
import os


@dataclass(frozen=True)
class Settings:
    db_url: str
    cors_allow_origins: list[str]


def load_settings() -> Settings:
    load_dotenv()

    db_url = os.getenv("DT_DB_URL")
    if not db_url:
        raise SystemExit("DT_DB_URL is required (PostgreSQL only). See backend/.env.example")
    cors = os.getenv("DT_CORS_ALLOW_ORIGINS", "http://localhost:3000")
    cors_allow_origins = [o.strip() for o in cors.split(",") if o.strip()]

    return Settings(db_url=db_url, cors_allow_origins=cors_allow_origins)
