"""
API route: Firms
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.db.database import get_db
from packages.db.models import Firm
from apps.api.authz import (
    RequestIdentity,
    assert_firm_access,
    get_request_identity,
    hipaa_enforcement_enabled,
)

router = APIRouter(prefix="/firms", tags=["firms"])


class CreateFirmRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class FirmResponse(BaseModel):
    id: str
    name: str
    created_at: str


@router.post("", response_model=FirmResponse, status_code=201)
def create_firm(
    req: CreateFirmRequest,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    if hipaa_enforcement_enabled():
        raise HTTPException(status_code=403, detail="Firm creation is disabled when HIPAA_ENFORCEMENT=true")
    firm = Firm(name=req.name)
    db.add(firm)
    db.flush()
    return FirmResponse(
        id=firm.id,
        name=firm.name,
        created_at=firm.created_at.isoformat(),
    )

@router.get("", response_model=list[FirmResponse])
def list_firms(
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """List all firms."""
    if identity is None:
        firms = db.query(Firm).all()
    else:
        firms = db.query(Firm).filter_by(id=identity.firm_id).all()
    return [
        FirmResponse(
            id=f.id,
            name=f.name,
            created_at=f.created_at.isoformat(),
        )
        for f in firms
    ]


@router.get("/{firm_id}", response_model=FirmResponse)
def get_firm(
    firm_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Get firm details."""
    assert_firm_access(identity, firm_id)
    firm = db.query(Firm).filter_by(id=firm_id).first()
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    return FirmResponse(
        id=firm.id,
        name=firm.name,
        created_at=firm.created_at.isoformat(),
    )
