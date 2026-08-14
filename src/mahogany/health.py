"""Health sidecar for deploy smoke — port 3004."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from mahogany.config import BUILD_ID, HEALTH_PORT, ROOT

app = FastAPI(title="mahogany-health", docs_url=None, redoc_url=None)


def _resolve_build_id() -> str:
    for candidate in (
        os.getenv("MAHOGANY_BUILD_ID"),
        Path("/opt/mahogany/BUILD_ID").read_text(encoding="utf-8").strip()
        if Path("/opt/mahogany/BUILD_ID").is_file()
        else None,
        (ROOT / "BUILD_ID").read_text(encoding="utf-8").strip()
        if (ROOT / "BUILD_ID").is_file()
        else None,
        BUILD_ID,
    ):
        if candidate:
            return candidate
    return "dev"


@app.get("/api/build-id")
def build_id() -> dict[str, str]:
    return {
        "buildId": _resolve_build_id(),
        "service": "mahogany",
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    uvicorn.run(
        "mahogany.health:app",
        host="127.0.0.1",
        port=HEALTH_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
