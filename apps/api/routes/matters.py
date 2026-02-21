"""
API route: Matters
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.authz import RequestIdentity, assert_firm_access, get_request_identity
from packages.db.database import get_db
from packages.db.models import Firm, Matter

router = APIRouter(tags=["matters"])


class CreateMatterRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    timezone: str = "America/Los_Angeles"
    client_ref: str | None = None


class MatterResponse(BaseModel):
    id: str
    firm_id: str
    title: str
    timezone: str
    client_ref: str | None
    created_at: str


@router.post("/firms/{firm_id}/matters", response_model=MatterResponse, status_code=201)
def create_matter(
    firm_id: str,
    req: CreateMatterRequest,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    assert_firm_access(identity, firm_id)

    firm = db.query(Firm).filter_by(id=firm_id).first()
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")

    matter = Matter(
        firm_id=firm_id,
        title=req.title,
        timezone=req.timezone,
        client_ref=req.client_ref,
    )
    db.add(matter)
    db.flush()
    return MatterResponse(
        id=matter.id,
        firm_id=matter.firm_id,
        title=matter.title,
        timezone=matter.timezone,
        client_ref=matter.client_ref,
        created_at=matter.created_at.isoformat(),
    )


@router.get("/firms/{firm_id}/matters", response_model=list[MatterResponse])
def list_matters(
    firm_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """List matters for a firm."""
    assert_firm_access(identity, firm_id)

    matters = db.query(Matter).filter_by(firm_id=firm_id).all()
    return [
        MatterResponse(
            id=m.id,
            firm_id=m.firm_id,
            title=m.title,
            timezone=m.timezone,
            client_ref=m.client_ref,
            created_at=m.created_at.isoformat(),
        )
        for m in matters
    ]


@router.get("/matters/{matter_id}", response_model=MatterResponse)
def get_matter(
    matter_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Get matter details."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")

    assert_firm_access(identity, matter.firm_id)
    return MatterResponse(
        id=matter.id,
        firm_id=matter.firm_id,
        title=matter.title,
        timezone=matter.timezone,
        client_ref=matter.client_ref,
        created_at=matter.created_at.isoformat(),
    )


@router.delete("/matters/{matter_id}", status_code=204)
def delete_matter(
    matter_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Delete a matter and its related records."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")

    assert_firm_access(identity, matter.firm_id)
    from packages.db.models import Run
    has_active = (
        db.query(Run)
        .filter(Run.matter_id == matter_id)
        .filter(Run.status.in_(["pending", "running"]))
        .first()
        is not None
    )
    if has_active:
        raise HTTPException(status_code=409, detail="Cannot delete matter with active runs")
    db.delete(matter)
    db.flush()
