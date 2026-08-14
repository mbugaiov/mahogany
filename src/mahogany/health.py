"""Health sidecar for deploy smoke — port 3004."""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from mahogany.config import BUILD_ID, HEALTH_PORT

app = FastAPI(title="mahogany-health", docs_url=None, redoc_url=None)


@app.get("/api/build-id")
def build_id() -> dict[str, str]:
    return {
        "buildId": os.getenv("MAHOGANY_BUILD_ID", BUILD_ID),
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
