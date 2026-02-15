"""
API route: Firms
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.db.database import get_db
from packages.db.models import Firm

router = APIRouter(prefix="/firms", tags=["firms"])


class CreateFirmRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class FirmResponse(BaseModel):
    id: str
    name: str
    created_at: str


@router.post("", response_model=FirmResponse, status_code=201)
def create_firm(req: CreateFirmRequest, db: Session = Depends(get_db)):
    firm = Firm(name=req.name)
    db.add(firm)
    db.flush()
    return FirmResponse(
        id=firm.id,
        name=firm.name,
        created_at=firm.created_at.isoformat(),
    )
