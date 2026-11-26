"""Demo seeding and reset."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import demo

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/seed")
def seed_demo(db: Session = Depends(get_db)):
    return demo.seed(db)


@router.get("/status")
def demo_status(db: Session = Depends(get_db)):
    return demo.status(db)


@router.post("/reset")
def reset_demo(db: Session = Depends(get_db)):
    return demo.reset(db)
