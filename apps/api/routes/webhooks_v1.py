"""
API route: Versioned webhooks facade (/v1/webhooks/*)
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.authz import RequestIdentity, assert_firm_access, get_request_identity
from packages.db.database import get_db
from packages.db.models import Firm, WebhookEndpoint, WebhookEvent

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks-v1"])


def _v1_webhooks_enabled() -> bool:
    raw = os.getenv("API_V1_WEBHOOKS_ENABLED", "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _assert_v1_webhooks_enabled() -> None:
    if not _v1_webhooks_enabled():
        raise HTTPException(status_code=404, detail="Not found")


def _validate_callback_url(value: str) -> str:
    url = (value or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="callback_url is required")
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        raise HTTPException(status_code=400, detail="callback_url must be http(s)")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise HTTPException(status_code=400, detail="callback_url must use https")
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="callback_url is invalid")
    return url


class WebhookEndpointCreateRequest(BaseModel):
    firm_id: str
    callback_url: str
    secret: str = Field(min_length=12, max_length=255)
    description: str | None = Field(default=None, max_length=255)


class WebhookEndpointResponse(BaseModel):
    endpoint_id: str
    firm_id: str
    callback_url: str
    active: bool
    description: str | None
    created_at: str | None
    updated_at: str | None
    secret_last4: str


class WebhookEndpointsListResponse(BaseModel):
    endpoints: list[WebhookEndpointResponse]


class WebhookEventResponse(BaseModel):
    event_id: str
    endpoint_id: str
    event_type: str
    delivery_status: str
    attempt_count: int
    last_attempt_at: str | None
    created_at: str | None
    payload: dict


def _to_endpoint_response(row: WebhookEndpoint) -> WebhookEndpointResponse:
    secret = row.secret or ""
    return WebhookEndpointResponse(
        endpoint_id=row.id,
        firm_id=row.firm_id,
        callback_url=row.callback_url,
        active=bool(row.active),
        description=row.description,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        secret_last4=secret[-4:] if len(secret) >= 4 else secret,
    )


@router.post("/endpoints", response_model=WebhookEndpointResponse, status_code=201)
def create_webhook_endpoint(
    req: WebhookEndpointCreateRequest,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    _assert_v1_webhooks_enabled()

    firm = db.query(Firm).filter_by(id=req.firm_id).first()
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    assert_firm_access(identity, firm.id)

    callback_url = _validate_callback_url(req.callback_url)
    row = WebhookEndpoint(
        firm_id=req.firm_id,
        callback_url=callback_url,
        secret=req.secret,
        description=req.description,
        active=True,
    )
    db.add(row)
    db.flush()
    return _to_endpoint_response(row)


@router.get("/endpoints", response_model=WebhookEndpointsListResponse)
def list_webhook_endpoints(
    firm_id: str,
    active_only: bool = True,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    _assert_v1_webhooks_enabled()

    firm = db.query(Firm).filter_by(id=firm_id).first()
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    assert_firm_access(identity, firm.id)

    query = db.query(WebhookEndpoint).filter_by(firm_id=firm_id)
    if active_only:
        query = query.filter_by(active=True)
    rows = query.order_by(WebhookEndpoint.created_at.desc()).all()
    return WebhookEndpointsListResponse(endpoints=[_to_endpoint_response(r) for r in rows])


@router.get("/endpoints/{endpoint_id}", response_model=WebhookEndpointResponse)
def get_webhook_endpoint(
    endpoint_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    _assert_v1_webhooks_enabled()

    row = db.query(WebhookEndpoint).filter_by(id=endpoint_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    assert_firm_access(identity, row.firm_id)
    return _to_endpoint_response(row)


@router.delete("/endpoints/{endpoint_id}", response_model=WebhookEndpointResponse)
def deactivate_webhook_endpoint(
    endpoint_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    _assert_v1_webhooks_enabled()

    row = db.query(WebhookEndpoint).filter_by(id=endpoint_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    assert_firm_access(identity, row.firm_id)

    row.active = False
    db.flush()
    return _to_endpoint_response(row)


@router.get("/events/{event_id}", response_model=WebhookEventResponse)
def get_webhook_event(
    event_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    _assert_v1_webhooks_enabled()

    event = db.query(WebhookEvent).filter_by(id=event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Webhook event not found")
    endpoint = db.query(WebhookEndpoint).filter_by(id=event.endpoint_id).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    assert_firm_access(identity, endpoint.firm_id)

    payload = event.payload_json if isinstance(event.payload_json, dict) else {}
    return WebhookEventResponse(
        event_id=event.id,
        endpoint_id=event.endpoint_id,
        event_type=event.event_type,
        delivery_status=event.delivery_status,
        attempt_count=event.attempt_count,
        last_attempt_at=event.last_attempt_at.isoformat() if event.last_attempt_at else None,
        created_at=event.created_at.isoformat() if event.created_at else None,
        payload=payload,
    )
