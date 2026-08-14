"""Runtime configuration — env only, no secrets in code."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
load_dotenv("/etc/mahogany.env")

DATA_DIR = Path(os.getenv("MAHOGANY_DATA_DIR", str(ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

LANDING_SRC = Path(os.getenv("MAHOGANY_LANDING_SRC", str(ROOT / "landing" / "index.html")))
LANDING_DEST = Path(os.getenv("MAHOGANY_LANDING_DEST", "/var/www/mahogany/index.html"))

BUILD_ID = os.getenv("MAHOGANY_BUILD_ID", "dev")
HEALTH_PORT = int(os.getenv("MAHOGANY_HEALTH_PORT", "3004"))


def data_path(name: str) -> Path:
    return DATA_DIR / name
