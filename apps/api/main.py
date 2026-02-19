"""
CiteLine API - FastAPI application entry point.
"""
from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apps.api.authz import hipaa_enforcement_enabled
from packages.db.database import DATABASE_URL, init_db
from packages.shared.storage import DATA_DIR


def _parse_csv_env(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return [value.strip() for value in raw.split(",") if value.strip()]


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("linecite")

app = FastAPI(
    title="Linecite API",
    description="Citeable medical chronologies for PI law firms",
    version="0.1.0",
)

# Security/runtime settings
cors_allow_origins = _parse_csv_env(
    "CORS_ALLOW_ORIGINS",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
)
cors_allow_credentials = _parse_bool_env("CORS_ALLOW_CREDENTIALS", True)
audit_logging_enabled = _parse_bool_env("HIPAA_AUDIT_LOGGING", True)
rate_limit_enabled = _parse_bool_env("RATE_LIMIT_ENABLED", True)
rate_limit_rpm = int(os.getenv("RATE_LIMIT_RPM", "180"))
max_request_bytes = int(os.getenv("MAX_REQUEST_BYTES", str(25 * 1024 * 1024)))
allowed_hosts = _parse_csv_env("ALLOWED_HOSTS", ["*"])
security_headers_enabled = _parse_bool_env("SECURITY_HEADERS_ENABLED", True)
_rate_windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _validate_hipaa_runtime() -> None:
    """Fail fast on unsafe defaults when HIPAA enforcement is enabled."""
    if not hipaa_enforcement_enabled():
        return

    if DATABASE_URL.startswith("sqlite"):
        raise RuntimeError(
            "HIPAA_ENFORCEMENT=true requires a managed database. "
            "Set DATABASE_URL to Postgres (sqlite is not allowed)."
        )

    if "*" in cors_allow_origins:
        raise RuntimeError(
            "HIPAA_ENFORCEMENT=true does not allow wildcard CORS origins."
        )

    if "*" in allowed_hosts:
        raise RuntimeError(
            "HIPAA_ENFORCEMENT=true does not allow wildcard ALLOWED_HOSTS."
        )

    auth_mode = os.getenv("API_INTERNAL_AUTH_MODE", "jwt").strip().lower()
    if auth_mode not in {"jwt", "static", "either"}:
        raise RuntimeError("API_INTERNAL_AUTH_MODE must be one of: jwt, static, either.")
    if auth_mode in {"jwt", "either"}:
        jwt_secret = os.getenv("API_INTERNAL_JWT_SECRET", "").strip()
        if len(jwt_secret) < 32:
            raise RuntimeError(
                "HIPAA_ENFORCEMENT=true with JWT auth requires API_INTERNAL_JWT_SECRET >= 32 chars."
            )
    if auth_mode in {"static", "either"}:
        internal_token = os.getenv("API_INTERNAL_TOKEN", "").strip()
        if len(internal_token) < 24:
            raise RuntimeError(
                "HIPAA_ENFORCEMENT=true with static auth requires API_INTERNAL_TOKEN >= 24 chars."
            )

    allow_default_local_storage = _parse_bool_env(
        "HIPAA_ALLOW_DEFAULT_LOCAL_STORAGE", False
    )
    if not allow_default_local_storage:
        default_data_dir = Path("C:/CiteLine/data").resolve()
        current_data_dir = DATA_DIR.resolve()
        if current_data_dir == default_data_dir:
            raise RuntimeError(
                "HIPAA_ENFORCEMENT=true cannot use default local DATA_DIR. "
                "Set DATA_DIR to managed encrypted storage mount."
            )


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-Id", "X-Firm-Id", "X-Internal-Token", "X-Request-Id"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)


def _request_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _rate_limit_key(request: Request) -> tuple[str, str]:
    return (_request_ip(request), request.url.path)


def _is_rate_limited(request: Request) -> bool:
    now = time.time()
    key = _rate_limit_key(request)
    window = _rate_windows[key]
    while window and (now - window[0]) > 60.0:
        window.popleft()
    if len(window) >= rate_limit_rpm:
        return True
    window.append(now)
    return False


@app.middleware("http")
async def request_security_and_audit_middleware(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    user_id = request.headers.get("X-User-Id", "anonymous")
    firm_id = request.headers.get("X-Firm-Id", "unknown")

    if request.url.path != "/health":
        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > max_request_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request entity too large"},
                    )
            except ValueError:
                pass

        if rate_limit_enabled and _is_rate_limited(request):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": "60", "X-Request-Id": request_id},
            )

    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id

    if security_headers_enabled:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )

    if audit_logging_enabled:
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "request_audit request_id=%s method=%s path=%s status=%s duration_ms=%s user_id=%s firm_id=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            user_id,
            firm_id,
        )

    return response


@app.on_event("startup")
def startup():
    """Initialize database tables on startup."""
    _validate_hipaa_runtime()
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized")


# Register routes
from apps.api.routes.documents import router as docs_router  # noqa: E402
from apps.api.routes.exports import router as exports_router  # noqa: E402
from apps.api.routes.firms import router as firms_router  # noqa: E402
from apps.api.routes.matters import router as matters_router  # noqa: E402
from apps.api.routes.runs import router as runs_router  # noqa: E402

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
