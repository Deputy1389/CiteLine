"""
Feature-flagged API authn/authz helpers.

Default behavior is permissive for backwards compatibility. Set
`HIPAA_ENFORCEMENT=true` to require request identity headers and tenant checks.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request


def _env_true(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def hipaa_enforcement_enabled() -> bool:
    return _env_true("HIPAA_ENFORCEMENT", False)


@dataclass(frozen=True)
class RequestIdentity:
    user_id: str
    firm_id: str


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _verify_internal_jwt(token: str, *, secret: str, method: str, path: str) -> RequestIdentity:
    raw = token.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    parts = raw.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Invalid internal auth token format")

    signing_input = f"{parts[0]}.{parts[1]}".encode("utf-8")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        got_sig = _b64url_decode(parts[2])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid internal auth signature encoding") from exc
    if not hmac.compare_digest(expected_sig, got_sig):
        raise HTTPException(status_code=401, detail="Invalid internal auth signature")

    try:
        header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid internal auth token payload") from exc

    if header.get("alg") != "HS256":
        raise HTTPException(status_code=401, detail="Unsupported internal auth algorithm")

    now = int(time.time())
    exp = payload.get("exp")
    iat = payload.get("iat")
    if not isinstance(exp, int) or now > exp:
        raise HTTPException(status_code=401, detail="Internal auth token expired")
    if not isinstance(iat, int) or iat > now + 60:
        raise HTTPException(status_code=401, detail="Invalid internal auth token iat")

    if payload.get("mth") != method.upper():
        raise HTTPException(status_code=401, detail="Internal auth method mismatch")
    if payload.get("pth") != path:
        raise HTTPException(status_code=401, detail="Internal auth path mismatch")

    user_id = payload.get("sub")
    firm_id = payload.get("firm_id")
    if not user_id or not firm_id:
        raise HTTPException(status_code=401, detail="Internal auth token missing subject claims")

    return RequestIdentity(user_id=str(user_id), firm_id=str(firm_id))


def get_request_identity(
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_firm_id: str | None = Header(default=None, alias="X-Firm-Id"),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
    x_internal_auth: str | None = Header(default=None, alias="X-Internal-Auth"),
) -> RequestIdentity | None:
    """
    Resolve request identity from headers when HIPAA enforcement is enabled.
    Returns None when enforcement is disabled.
    """
    if not hipaa_enforcement_enabled():
        return None

    mode = os.getenv("API_INTERNAL_AUTH_MODE", "jwt").strip().lower()
    if mode not in {"jwt", "static", "either"}:
        raise HTTPException(status_code=500, detail="Invalid API_INTERNAL_AUTH_MODE")

    if mode in {"jwt", "either"} and x_internal_auth:
        secret = os.getenv("API_INTERNAL_JWT_SECRET", "").strip()
        if len(secret) < 32:
            raise HTTPException(
                status_code=500,
                detail="API is misconfigured: API_INTERNAL_JWT_SECRET must be set for JWT mode",
            )
        identity = _verify_internal_jwt(
            x_internal_auth,
            secret=secret,
            method=request.method,
            path=request.url.path,
        )
        if x_user_id and x_user_id != identity.user_id:
            raise HTTPException(status_code=401, detail="Identity header mismatch (user)")
        if x_firm_id and x_firm_id != identity.firm_id:
            raise HTTPException(status_code=401, detail="Identity header mismatch (firm)")
        return identity

    if mode in {"static", "either"}:
        expected_token = os.getenv("API_INTERNAL_TOKEN", "").strip()
        if len(expected_token) < 24:
            raise HTTPException(
                status_code=500,
                detail="API is misconfigured: API_INTERNAL_TOKEN must be set for static mode",
            )
        if x_internal_token != expected_token:
            raise HTTPException(status_code=401, detail="Invalid internal token")
        if not x_user_id or not x_firm_id:
            raise HTTPException(
                status_code=401,
                detail="Missing required identity headers: X-User-Id and X-Firm-Id",
            )
        return RequestIdentity(user_id=x_user_id, firm_id=x_firm_id)

    raise HTTPException(status_code=401, detail="Missing internal auth token")


def assert_firm_access(identity: RequestIdentity | None, firm_id: str) -> None:
    if identity is None:
        return
    if identity.firm_id != firm_id:
        raise HTTPException(status_code=403, detail="Forbidden: cross-firm access denied")
