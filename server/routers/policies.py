"""Insurance policy endpoints, including document-assisted creation."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Adjudication, Family, FamilyMember, Policy, PolicyMember, User
from ..schemas import (
    PolicyExtractIn,
    PolicyIn,
    PolicyMemberIn,
    PolicyUpdateIn,
    PolicyVersionIn,
    TermsIn,
)
from ..security import current_user, document_for_user, family_for_user, policy_for_user
from ..serializers import policy_out
from ..services.policies import (
    apply_extraction_to_terms,
    create_version,
    decimal,
    ensure_policyholder_link,
    upsert_member_links,
)

router = APIRouter(prefix="/api", tags=["policies"])


def _check_policy_number(db: Session, family_id: int, policy_number: str, exclude_id: int | None = None) -> None:
    # Policy numbers are globally unique in this prototype: the mock insurer
    # API looks a policy up by number, so duplicates would be ambiguous.
    query = db.query(Policy).filter(Policy.policy_number == policy_number)
    if exclude_id:
        query = query.filter(Policy.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=409, detail="That policy number already exists in this household.")


def _validate_members(db: Session, family_id: int, member_ids: list[int]) -> dict[int, FamilyMember]:
    members = (
        db.query(FamilyMember).filter(FamilyMember.family_id == family_id, FamilyMember.id.in_(member_ids)).all()
        if member_ids
        else []
    )
    found = {member.id: member for member in members}
    missing = [str(member_id) for member_id in member_ids if member_id not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"Members not found in this household: {', '.join(missing)}")
    return found


@router.post("/policies", status_code=201)
def create_policy(payload: PolicyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    family = family_for_user(db, payload.family_id, user)
    _check_policy_number(db, family.id, payload.policy_number.strip())
    member_ids = [link.member_id for link in payload.members]
    if payload.policyholder_member_id and payload.policyholder_member_id not in member_ids:
        member_ids.append(payload.policyholder_member_id)
    _validate_members(db, family.id, member_ids)
    policy = Policy(
        family_id=family.id,
        insurer_name=payload.insurer_name.strip(),
        plan_name=payload.plan_name.strip(),
        policy_number=payload.policy_number.strip(),
        policyholder_member_id=payload.policyholder_member_id,
        status=payload.status,
        start_date=payload.start_date,
        end_date=payload.end_date,
        coordination_rule=payload.coordination_rule,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    links = [{"member_id": link.member_id, "role": link.role} for link in payload.members]
    if payload.policyholder_member_id and not any(
        link["member_id"] == payload.policyholder_member_id for link in links
    ):
        links.append({"member_id": payload.policyholder_member_id, "role": "policyholder"})
    upsert_member_links(db, policy, links)
    create_version(db, policy, payload.terms, source="manual", confirmed=True)
    db.refresh(policy)
    return policy_out(policy)


@router.get("/policies")
def list_policies(
    family_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    if family_id:
        family_for_user(db, family_id, user)
        policies = db.query(Policy).filter(Policy.family_id == family_id).order_by(Policy.id).all()
    else:
        family_ids = [family.id for family in db.query(Family).filter(Family.owner_id == user.id).all()]
        policies = (
            db.query(Policy).filter(Policy.family_id.in_(family_ids)).order_by(Policy.id).all()
            if family_ids
            else []
        )
    return {"policies": [policy_out(policy, detail=False) for policy in policies]}


@router.get("/policies/{policy_id}")
def get_policy(policy_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return policy_out(policy_for_user(db, policy_id, user))


@router.patch("/policies/{policy_id}")
def update_policy(
    policy_id: int, payload: PolicyUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    policy = policy_for_user(db, policy_id, user)
    if payload.policy_number:
        _check_policy_number(db, policy.family_id, payload.policy_number.strip(), exclude_id=policy.id)
    for field in ("insurer_name", "plan_name", "policy_number", "status", "start_date", "end_date", "coordination_rule"):
        value = getattr(payload, field)
        if value is not None:
            setattr(policy, field, value.strip() if isinstance(value, str) and field in ("insurer_name", "plan_name", "policy_number") else value)
    if payload.policyholder_member_id is not None:
        family = db.get(Family, policy.family_id)
        _validate_members(db, policy.family_id, [payload.policyholder_member_id])
        policy.policyholder_member_id = payload.policyholder_member_id
        ensure_policyholder_link(db, policy, {member.id: member for member in family.members})
    db.add(policy)
    db.commit()
    if payload.terms is not None:
        create_version(
            db,
            policy,
            payload.terms,
            source="manual",
            confirmed=True,
            change_note=payload.change_note or "Terms revised",
        )
    db.refresh(policy)
    return policy_out(policy)


@router.post("/policies/{policy_id}/versions", status_code=201)
def add_version(
    policy_id: int, payload: PolicyVersionIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    policy = policy_for_user(db, policy_id, user)
    version = create_version(
        db,
        policy,
        payload.terms,
        source="manual",
        confirmed=True,
        change_note=payload.change_note or "New version",
        effective_from=payload.effective_from,
    )
    return {"version": version.id, "policy": policy_out(policy)}


@router.post("/policies/{policy_id}/members", status_code=201)
def add_policy_member(
    policy_id: int, payload: PolicyMemberIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    policy = policy_for_user(db, policy_id, user)
    _validate_members(db, policy.family_id, [payload.member_id])
    existing = (
        db.query(PolicyMember)
        .filter(PolicyMember.policy_id == policy.id, PolicyMember.member_id == payload.member_id)
        .one_or_none()
    )
    if existing:
        existing.role = payload.role
    else:
        db.add(PolicyMember(policy_id=policy.id, member_id=payload.member_id, role=payload.role))
    db.commit()
    db.refresh(policy)
    return policy_out(policy)


@router.delete("/policies/{policy_id}/members/{member_id}", status_code=204)
def remove_policy_member(
    policy_id: int, member_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    policy = policy_for_user(db, policy_id, user)
    link = (
        db.query(PolicyMember)
        .filter(PolicyMember.policy_id == policy.id, PolicyMember.member_id == member_id)
        .one_or_none()
    )
    if not link:
        raise HTTPException(status_code=404, detail="That member is not linked to this policy.")
    if policy.policyholder_member_id == member_id:
        raise HTTPException(status_code=409, detail="Change the policyholder before removing this member.")
    db.delete(link)
    db.commit()


@router.delete("/policies/{policy_id}", status_code=204)
def delete_policy(policy_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    policy = policy_for_user(db, policy_id, user)
    if db.query(Adjudication).filter(Adjudication.policy_id == policy.id).first():
        raise HTTPException(
            status_code=409,
            detail="This policy has already been used in a case. Mark it inactive instead of deleting it so the claim stays reproducible.",
        )
    db.delete(policy)
    db.commit()


@router.get("/policies/{policy_id}/accumulators")
def policy_accumulators(policy_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..serializers import _s
    from ..services.accumulators import get_accumulator

    policy = policy_for_user(db, policy_id, user)
    version = policy.current_version
    if not version:
        return {"accumulators": []}
    rows = []
    for link in policy.member_links:
        accumulator = get_accumulator(db, policy, version, link.member_id)
        sublimits = []
        for item in version.sublimits or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or item.get("label"))
            sublimits.append(
                {
                    "key": key,
                    "label": item.get("label"),
                    "limit": _s(item.get("limit")),
                    "used": _s((accumulator.sublimits or {}).get(key, 0)),
                    "basis": item.get("basis") or "per_year",
                }
            )
        rows.append(
            {
                "member_id": link.member_id,
                "member": link.member.name if link.member else None,
                "role": link.role,
                "deductible_used": _s(accumulator.deductible_used),
                "deductible": _s(version.deductible),
                "oop_used": _s(accumulator.oop_used),
                "oop_max": _s(version.oop_max),
                "annual_limit_used": _s(accumulator.annual_limit_used),
                "annual_limit": _s(version.annual_limit),
                "sublimits": sublimits,
            }
        )
    return {"policy_id": policy.id, "version_id": version.id, "version": version.version, "accumulators": rows}


@router.post("/policies/extract")
def extract_policy(
    payload: PolicyExtractIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    document = document_for_user(db, payload.document_id, user)
    if document.doc_type != "policy":
        raise HTTPException(
            status_code=422,
            detail="That document was classified as something other than a policy. Change its type first.",
        )
    fields = document.fields or {}
    extracted = apply_extraction_to_terms(fields)
    missing = [
        key
        for key in ("insurer", "policy_number", "sum_insured", "coinsurance_member")
        if not (fields.get(key) or {}).get("value")
    ]
    return {
        "document": {
            "id": document.id,
            "filename": document.original_filename,
            "classification_confidence": float(document.classification_confidence or 0),
            "mean_ocr_confidence": float(document.mean_ocr_confidence) if document.mean_ocr_confidence is not None else None,
        },
        **extracted,
        "missing": missing,
        "note": "Review every extracted value against the policy schedule before saving. Nothing is saved yet.",
    }
