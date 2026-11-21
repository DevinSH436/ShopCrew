"""Store settings, read once from environment variables (and ``.env``)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the store."""

    store_name: str
    database_url: str
    secret_key: str
    media_dir: Path
    free_shipping_threshold: int
    shipping_fee: int
    cod_fee: int
    return_window_days: int
    admin_email: str
    admin_password: str
    debug: bool


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings (cached)."""
    load_dotenv(PROJECT_ROOT / ".env")
    db_path = os.getenv("STORE_DB") or str(PROJECT_ROOT / "store.db")
    return Settings(
        store_name=os.getenv("STORE_NAME", "Northcart"),
        database_url=db_path if "://" in db_path else f"sqlite:///{db_path}",
        # A random key per process is safe for local demos; set STORE_SECRET_KEY to keep
        # sessions across restarts.
        secret_key=os.getenv("STORE_SECRET_KEY") or secrets.token_urlsafe(32),
        media_dir=Path(os.getenv("STORE_MEDIA_DIR") or PROJECT_ROOT / "media"),
        free_shipping_threshold=_int("FREE_SHIPPING_THRESHOLD", 35),
        shipping_fee=_int("SHIPPING_FEE", 5),
        cod_fee=_int("COD_FEE", 2),
        return_window_days=_int("RETURN_WINDOW_DAYS", 7),
        admin_email=os.getenv("ADMIN_EMAIL", "admin@northcart.test"),
        admin_password=os.getenv("ADMIN_PASSWORD", "admin1234"),
        debug=os.getenv("STORE_DEBUG", "false").lower() in {"1", "true", "yes"},
    )
