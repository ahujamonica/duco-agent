"""Family and member endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Case, Claim, Family, FamilyMember, User
from ..schemas import FamilyIn, FamilyUpdateIn, MemberIn, MemberUpdateIn
from ..security import current_user, family_for_user
from ..serializers import family_out, member_out

router = APIRouter(prefix="/api", tags=["families"])


@router.post("/families", status_code=201)
def create_family(payload: FamilyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    family = Family(
        owner_id=user.id,
        name=payload.name.strip(),
        coordination_rule=payload.coordination_rule,
        notes=payload.notes,
    )
    db.add(family)
    db.commit()
    db.refresh(family)
    return family_out(family)


@router.get("/families")
def list_families(user: User = Depends(current_user), db: Session = Depends(get_db)):
    families = db.query(Family).filter(Family.owner_id == user.id).order_by(Family.id).all()
    return {"families": [family_out(family, detail=False) for family in families]}


@router.get("/families/{family_id}")
def get_family(family_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return family_out(family_for_user(db, family_id, user))


@router.patch("/families/{family_id}")
def update_family(
    family_id: int, payload: FamilyUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    family = family_for_user(db, family_id, user)
    for field in ("name", "coordination_rule", "notes"):
        value = getattr(payload, field)
        if value is not None:
            setattr(family, field, value)
    db.add(family)
    db.commit()
    db.refresh(family)
    return family_out(family)


@router.delete("/families/{family_id}", status_code=204)
def delete_family(family_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    family = family_for_user(db, family_id, user)
    db.delete(family)
    db.commit()


@router.post("/families/{family_id}/members", status_code=201)
def add_member(
    family_id: int, payload: MemberIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    family = family_for_user(db, family_id, user)
    member = FamilyMember(
        family_id=family.id,
        name=payload.name,
        date_of_birth=payload.date_of_birth,
        age_years=payload.age_years,
        relation=payload.relation,
        gender=payload.gender,
        phone=payload.phone,
        notes=payload.notes,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member_out(member)


@router.get("/families/{family_id}/members")
def list_members(family_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    family = family_for_user(db, family_id, user)
    return {"members": [member_out(member) for member in family.members]}


@router.patch("/members/{member_id}")
def update_member(
    member_id: int, payload: MemberUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    member = db.get(FamilyMember, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")
    family_for_user(db, member.family_id, user)
    for field in ("name", "date_of_birth", "age_years", "relation", "gender", "phone", "notes"):
        value = getattr(payload, field)
        if value is not None:
            setattr(member, field, value)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member_out(member)


@router.delete("/members/{member_id}", status_code=204)
def delete_member(member_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    member = db.get(FamilyMember, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")
    family_for_user(db, member.family_id, user)
    if len(member.family.members) <= 1:
        raise HTTPException(status_code=409, detail="A family needs at least one member.")
    used = (
        db.query(Case).filter(Case.patient_member_id == member.id).first()
        or db.query(Claim).filter(Claim.member_id == member.id).first()
    )
    if used:
        raise HTTPException(
            status_code=409,
            detail="This member is part of an existing case. Keep the record so the claim stays reproducible.",
        )
    db.delete(member)
    db.commit()
