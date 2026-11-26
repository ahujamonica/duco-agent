"""The mock insurer HTTP API requested by the brief.

Mounted outside /api exactly as specified. Every response is generated from the
stored policy record and labelled simulated. There is no authentication here by
design (it is a sandbox); docs/SECURITY.md records that for production.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import MockApiLog, User
from ..security import current_user
from ..services.insurer_mock import MockInsurerService

router = APIRouter(prefix="/mock-insurers", tags=["mock-insurers"])


@router.post("/eligibility")
def eligibility(payload: dict = Body(...), db: Session = Depends(get_db)):
    return MockInsurerService(db).eligibility(payload)


@router.post("/benefits")
def benefits(payload: dict = Body(...), db: Session = Depends(get_db)):
    return MockInsurerService(db).benefits(payload)


@router.post("/claims")
def claims(payload: dict = Body(...), db: Session = Depends(get_db)):
    return MockInsurerService(db).submit_claim(payload)


@router.get("/claims/{claim_id}")
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    return MockInsurerService(db).get_claim(claim_id)


@router.post("/pre-authorization")
def pre_authorization(payload: dict = Body(...), db: Session = Depends(get_db)):
    return MockInsurerService(db).pre_authorization(payload)


@router.get("/logs")
def logs(
    case_id: int | None = None,
    limit: int = 100,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    from ..models import Case, Family

    family_ids = [family.id for family in db.query(Family).filter(Family.owner_id == user.id).all()]
    case_ids = [
        case.id for case in db.query(Case).filter(Case.family_id.in_(family_ids)).all()
    ] if family_ids else []
    query = db.query(MockApiLog)
    if case_id:
        if case_id not in case_ids:
            return {"logs": []}
        query = query.filter(MockApiLog.case_id == case_id)
    elif case_ids:
        query = query.filter(MockApiLog.case_id.in_(case_ids))
    else:
        return {"logs": []}
    rows = query.order_by(MockApiLog.id.desc()).limit(min(limit, 300)).all()
    return {
        "logs": [
            {
                "id": row.id,
                "case_id": row.case_id,
                "endpoint": row.endpoint,
                "method": row.method,
                "request": row.request,
                "response": row.response,
                "status_code": row.status_code,
                "simulated": row.simulated,
                "duration_ms": row.duration_ms,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }
