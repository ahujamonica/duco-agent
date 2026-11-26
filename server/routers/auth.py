"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Family, User
from ..schemas import LoginIn, RegisterIn
from ..security import create_token, current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "locale": user.locale,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/register", status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    if db.query(User).filter(User.email == email).one_or_none():
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    user = User(name=payload.name.strip(), email=email, password_hash=hash_password(payload.password), locale=payload.locale)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": create_token(user.id), "user": _user_out(user)}


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower().strip()).one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return {"token": create_token(user.id), "user": _user_out(user)}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    families = db.query(Family).filter(Family.owner_id == user.id).all()
    return {
        "user": _user_out(user),
        "families": [{"id": family.id, "name": family.name} for family in families],
    }
