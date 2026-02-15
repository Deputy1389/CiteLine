"""
CiteLine API — FastAPI application entry point.
"""
from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from packages.db.database import init_db

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("citeline")

app = FastAPI(
    title="CiteLine API",
    description="Citeable medical chronologies for PI law firms",
    version="0.1.0",
)

# CORS (permissive for MVP)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    """Initialize database tables on startup."""
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized")


# Register routes
from apps.api.routes.firms import router as firms_router       # noqa: E402
from apps.api.routes.matters import router as matters_router   # noqa: E402
from apps.api.routes.documents import router as docs_router    # noqa: E402
from apps.api.routes.runs import router as runs_router         # noqa: E402
from apps.api.routes.exports import router as exports_router   # noqa: E402

app.include_router(firms_router)
app.include_router(matters_router)
app.include_router(docs_router)
app.include_router(runs_router)
app.include_router(exports_router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("apps.api.main:app", host="0.0.0.0", port=8000, reload=True)
