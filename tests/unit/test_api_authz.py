from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from apps.api.authz import (
    RequestIdentity,
    assert_firm_access,
    get_request_identity,
    hipaa_enforcement_enabled,
)


def _request(method: str = "GET", path: str = "/firms/f1/matters") -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("utf-8"),
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
    }
    return Request(scope)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _make_jwt(secret: str, *, user_id: str, firm_id: str, method: str, path: str, ttl: int = 60) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "firm_id": firm_id,
        "iat": now,
        "exp": now + ttl,
        "mth": method.upper(),
        "pth": path,
    }
    h = _b64url(json.dumps(header).encode("utf-8"))
    p = _b64url(json.dumps(payload).encode("utf-8"))
    signing_input = f"{h}.{p}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


def test_hipaa_enforcement_disabled_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("HIPAA_ENFORCEMENT", raising=False)
    assert hipaa_enforcement_enabled() is False


def test_get_request_identity_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HIPAA_ENFORCEMENT", "false")
    identity = get_request_identity(_request(), x_user_id=None, x_firm_id=None)
    assert identity is None


def test_get_request_identity_requires_internal_auth_when_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HIPAA_ENFORCEMENT", "true")
    monkeypatch.setenv("API_INTERNAL_AUTH_MODE", "jwt")
    monkeypatch.setenv("API_INTERNAL_JWT_SECRET", "x" * 32)
    with pytest.raises(HTTPException) as exc:
        get_request_identity(_request(), x_internal_auth=None)
    assert exc.value.status_code == 401


def test_get_request_identity_resolves_from_jwt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HIPAA_ENFORCEMENT", "true")
    monkeypatch.setenv("API_INTERNAL_AUTH_MODE", "jwt")
    monkeypatch.setenv("API_INTERNAL_JWT_SECRET", "x" * 32)

    req = _request("GET", "/firms/f1/matters")
    token = _make_jwt("x" * 32, user_id="u1", firm_id="f1", method="GET", path="/firms/f1/matters")

    identity = get_request_identity(
        req,
        x_user_id=None,
        x_firm_id=None,
        x_internal_token=None,
        x_internal_auth=f"Bearer {token}",
    )
    assert identity == RequestIdentity(user_id="u1", firm_id="f1")


def test_get_request_identity_rejects_jwt_path_mismatch(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HIPAA_ENFORCEMENT", "true")
    monkeypatch.setenv("API_INTERNAL_AUTH_MODE", "jwt")
    monkeypatch.setenv("API_INTERNAL_JWT_SECRET", "x" * 32)

    req = _request("GET", "/firms/f1/matters")
    token = _make_jwt("x" * 32, user_id="u1", firm_id="f1", method="GET", path="/firms/f2/matters")

    with pytest.raises(HTTPException) as exc:
        get_request_identity(
            req,
            x_user_id=None,
            x_firm_id=None,
            x_internal_token=None,
            x_internal_auth=f"Bearer {token}",
        )
    assert exc.value.status_code == 401


def test_get_request_identity_static_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HIPAA_ENFORCEMENT", "true")
    monkeypatch.setenv("API_INTERNAL_AUTH_MODE", "static")
    monkeypatch.setenv("API_INTERNAL_TOKEN", "x" * 32)

    identity = get_request_identity(
        _request(),
        x_user_id="u1",
        x_firm_id="f1",
        x_internal_token="x" * 32,
    )
    assert identity == RequestIdentity(user_id="u1", firm_id="f1")


def test_assert_firm_access_allows_match():
    assert_firm_access(RequestIdentity(user_id="u1", firm_id="f1"), "f1")


def test_assert_firm_access_blocks_cross_firm():
    with pytest.raises(HTTPException) as exc:
        assert_firm_access(RequestIdentity(user_id="u1", firm_id="f1"), "f2")
    assert exc.value.status_code == 403
