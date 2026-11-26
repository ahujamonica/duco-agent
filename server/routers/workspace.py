"""Dashboard, metadata and account settings."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import ALLOWED_EXTENSIONS, DATA_DIR, DEMO_MODE, ENVIRONMENT, LLM_ENABLED, TTS_ENABLED
from ..db import get_db
from ..models import Case, Document, Family, Report, User
from ..schemas import ProfileIn
from ..security import current_user
from ..services.results import build_results, dashboard

router = APIRouter(prefix="/api", tags=["workspace"])


@router.get("/dashboard")
def get_dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return dashboard(db, user.id)


@router.get("/meta")
def meta():
    return {
        "name": "DuCO Agent",
        "version": "2.0.0",
        "environment": ENVIRONMENT,
        "demo_mode": DEMO_MODE,
        "database": "SQLite (local prototype; PostgreSQL via DUCO_DATABASE_URL)",
        "mock_insurers": True,
        "llm_enrichment": LLM_ENABLED,
        "tts": TTS_ENABLED,
        "accepted_extensions": sorted(ALLOWED_EXTENSIONS),
        "disclaimers": [
            "Insurer responses come from a local mock sandbox. They are not approvals.",
            "Calculations are estimates based on the policy terms you confirm.",
            "Pre-authorisation letters are requests, not guarantees of payment.",
            "This prototype is not a substitute for a licensed insurer, TPA or clinician.",
        ],
        "features": {
            "multi_policy_coordination": True,
            "deterministic_engine": True,
            "human_review": True,
            "what_if_simulator": True,
            "explain_my_bill": True,
            "hindi": True,
            "audio_briefing": TTS_ENABLED,
        },
    }


@router.get("/settings/profile")
def profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    families = db.query(Family).filter(Family.owner_id == user.id).all()
    cases = (
        db.query(Case).filter(Case.family_id.in_([family.id for family in families])).count() if families else 0
    )
    documents = (
        db.query(Document).filter(Document.family_id.in_([family.id for family in families])).count()
        if families
        else 0
    )
    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "locale": user.locale,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "counts": {"families": len(families), "cases": cases, "documents": documents},
    }


@router.patch("/settings/profile")
def update_profile(payload: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if payload.name:
        user.name = payload.name.strip()
    if payload.locale:
        user.locale = payload.locale
    db.add(user)
    db.commit()
    return {"user": {"id": user.id, "name": user.name, "email": user.email, "locale": user.locale}}


@router.get("/settings/security-notes")
def security_notes():
    return {
        "implemented": [
            "Passwords hashed with PBKDF2-HMAC-SHA256 and a per-user salt.",
            "Signed JWT bearer sessions with expiry.",
            "Every family, policy, document and case read is scoped to the signed-in owner.",
            "Medical files are stored outside the web root and served only through an authenticated route with no-cache headers.",
            "Uploads are validated by extension, MIME type and size, and stored under random names.",
            "Duplicate uploads are detected by SHA-256.",
            "SQL access goes through the ORM with parameterised queries.",
            "No secrets in the repository; configuration is read from environment variables.",
        ],
        "not_implemented": [
            "Field-level encryption or a KMS-backed key hierarchy.",
            "Audit logging of document reads.",
            "Rate limiting and abuse protection.",
            "Consent records and DPDP Act erasure workflows beyond account deletion.",
            "HTTPS termination and secure headers at the edge.",
            "Penetration testing and a formal threat model.",
        ],
        "note": "This is a local prototype. Do not put real medical records in it until the gaps above are closed.",
    }


@router.get("/settings/export")
def export_data(user: User = Depends(current_user), db: Session = Depends(get_db)):
    families = db.query(Family).filter(Family.owner_id == user.id).all()
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {"id": user.id, "name": user.name, "email": user.email},
        "families": [],
    }
    for family in families:
        family_data = {
            "id": family.id,
            "name": family.name,
            "coordination_rule": family.coordination_rule,
            "members": [
                {"id": member.id, "name": member.name, "date_of_birth": member.date_of_birth.isoformat() if member.date_of_birth else None, "relation": member.relation}
                for member in family.members
            ],
            "policies": [
                {
                    "id": policy.id,
                    "insurer_name": policy.insurer_name,
                    "plan_name": policy.plan_name,
                    "policy_number": policy.policy_number,
                    "status": policy.status,
                }
                for policy in family.policies
            ],
            "cases": [],
        }
        for case in family.cases:
            family_data["cases"].append(build_results(db, case))
        payload["families"].append(family_data)
    path = DATA_DIR / f"export-{user.id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return FileResponse(
        path,
        media_type="application/json",
        filename="duco-agent-export.json",
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete("/settings/account")
def delete_account(confirm: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass confirm=true to delete the account and its data.")
    families = db.query(Family).filter(Family.owner_id == user.id).all()
    for family in families:
        for document in family.documents:
            try:
                from ..config import UPLOAD_DIR

                (UPLOAD_DIR / document.stored_name).unlink(missing_ok=True)
            except OSError:
                pass
        for case in family.cases:
            for report in db.query(Report).filter(Report.case_id == case.id).all():
                try:
                    Path(report.path).unlink(missing_ok=True)
                except OSError:
                    pass
    db.delete(user)
    db.commit()
    return {"deleted": True}
