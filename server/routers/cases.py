"""Case lifecycle, analysis, review, results and deliverables."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import AUDIO_DIR, REPORT_DIR
from ..db import get_db
from ..models import (
    AgentEvent,
    Case,
    Claim,
    Document,
    Family,
    FamilyMember,
    Policy,
    Preauthorization,
    Report,
    ReviewItem,
    User,
    utcnow,
)
from ..schemas import CaseIn, CaseUpdateIn, ReviewIn, SimulateIn
from ..security import case_for_user, current_user, family_for_user
from ..serializers import case_out, document_out, member_out, policy_out, review_out
from ..services.insurer_mock import MockInsurerService
from ..services.results import build_gaps, build_results, build_trace, explain_line, simulate

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _versions_for_policies(db: Session, family_id: int, policy_ids: list[int]) -> list[int]:
    if not policy_ids:
        policies = db.query(Policy).filter(Policy.family_id == family_id).order_by(Policy.id).all()
        return [policy.current_version.id for policy in policies if policy.current_version]
    policies = db.query(Policy).filter(Policy.family_id == family_id, Policy.id.in_(policy_ids)).all()
    found = {policy.id for policy in policies}
    missing = [str(pid) for pid in policy_ids if pid not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"Policies not found in this household: {', '.join(missing)}")
    return [policy.current_version.id for policy in policies if policy.current_version]


def _validate_documents(db: Session, family_id: int, document_ids: list[int]) -> None:
    if not document_ids:
        return
    found = (
        db.query(Document)
        .filter(Document.family_id == family_id, Document.id.in_(document_ids))
        .count()
    )
    if found != len(set(document_ids)):
        raise HTTPException(status_code=422, detail="One or more documents do not belong to this household.")


@router.post("", status_code=201)
def create_case(payload: CaseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    family = family_for_user(db, payload.family_id, user)
    patient = db.get(FamilyMember, payload.patient_member_id)
    if not patient or patient.family_id != family.id:
        raise HTTPException(status_code=422, detail="The patient must be a member of this household.")
    _validate_documents(db, family.id, payload.document_ids)
    version_ids = _versions_for_policies(db, family.id, payload.policy_ids)
    if not version_ids:
        raise HTTPException(status_code=422, detail="Add at least one insurance policy before creating a case.")
    case = Case(
        family_id=family.id,
        title=payload.title.strip(),
        patient_member_id=patient.id,
        provider_name=payload.provider_name.strip(),
        provider_in_network=payload.provider_in_network,
        service_date=payload.service_date,
        narrative=payload.narrative,
        coordination_rule=payload.coordination_rule or family.coordination_rule,
        policy_version_ids=version_ids,
        document_ids=payload.document_ids,
        status="ready" if (payload.document_ids or payload.manual_lines) else "draft",
        workflow_state={
            "manual_lines": payload.manual_lines,
            "policy_order": payload.policy_order or (payload.policy_ids if (payload.coordination_rule or family.coordination_rule) == "manual" else []),
            "gaps": [],
            "assumptions": [],
            "stage": "draft",
        },
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return _detail(db, case)


@router.get("")
def list_cases(
    family_id: int | None = None,
    status: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    family_ids = [family.id for family in db.query(Family).filter(Family.owner_id == user.id).all()]
    if not family_ids:
        return {"cases": []}
    query = db.query(Case).filter(Case.family_id.in_(family_ids))
    if family_id:
        family_for_user(db, family_id, user)
        query = query.filter(Case.family_id == family_id)
    if status:
        query = query.filter(Case.status == status)
    cases = query.order_by(Case.updated_at.desc()).all()
    families = {family.id: family.name for family in db.query(Family).filter(Family.id.in_(family_ids))}
    return {
        "cases": [
            {
                **case_out(case),
                "family_name": families.get(case.family_id),
                "claim_count": len(case.claims),
                "evidence_count": len(case.document_ids or []),
            }
            for case in cases
        ]
    }


@router.get("/{case_id}")
def get_case(case_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    case = case_for_user(db, case_id, user)
    return _detail(db, case)


def _detail(db: Session, case: Case) -> dict:
    family = db.get(Family, case.family_id)
    patient = db.get(FamilyMember, case.patient_member_id) if case.patient_member_id else None
    claims = db.query(Claim).filter(Claim.case_id == case.id).order_by(Claim.id).all()
    documents = (
        db.query(Document).filter(Document.id.in_(case.document_ids or [])).order_by(Document.id).all()
        if case.document_ids
        else []
    )
    policies = []
    for version_id in case.policy_version_ids or []:
        from ..models import PolicyVersion

        version = db.get(PolicyVersion, int(version_id))
        if version:
            policy = db.get(Policy, version.policy_id)
            if policy:
                policies.append(policy_out(policy, detail=False))
    reviews = db.query(ReviewItem).filter(ReviewItem.case_id == case.id).order_by(ReviewItem.id).all()
    trace_count = db.query(AgentEvent).filter(AgentEvent.case_id == case.id).count()
    return {
        **case_out(case),
        "family": {"id": family.id, "name": family.name, "coordination_rule": family.coordination_rule} if family else None,
        "patient": member_out(patient) if patient else None,
        "claims": [
            {
                "id": claim.id,
                "patient": claim.patient_name,
                "member_id": claim.member_id,
                "provider": claim.provider_name,
                "service_date": claim.service_date.isoformat() if claim.service_date else None,
                "bill_number": claim.bill_number,
                "document_id": claim.document_id,
                "line_count": len(claim.lines),
                "billed": str(sum((line.billed_amount for line in claim.lines), 0)),
                "lines": [
                    {
                        "id": line.id,
                        "description": line.description,
                        "quantity": line.quantity,
                        "unit_rate": str(line.unit_rate),
                        "billed": str(line.billed_amount),
                        "cpt_code": line.cpt_code,
                        "category": line.category,
                        "icd_codes": line.icd_codes or [],
                        "code_source": line.code_source,
                        "code_confidence": float(line.code_confidence or 0),
                    }
                    for line in claim.lines
                ],
            }
            for claim in claims
        ],
        "documents": [document_out(document, include_fields=False) for document in documents],
        "policies": policies,
        "review_items": [review_out(item) for item in reviews],
        "review_pending": len([item for item in reviews if item.status == "pending"]),
        "gaps": (case.workflow_state or {}).get("gaps") or [],
        "assumptions": (case.workflow_state or {}).get("assumptions") or [],
        "trace": {
            "events": trace_count,
            "stage": (case.workflow_state or {}).get("stage"),
            "tasks": (case.workflow_state or {}).get("tasks") or {},
        },
    }


@router.patch("/{case_id}")
def update_case(
    case_id: int, payload: CaseUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    case = case_for_user(db, case_id, user)
    if payload.title is not None:
        case.title = payload.title.strip()
    if payload.provider_name is not None:
        case.provider_name = payload.provider_name
    if payload.provider_in_network is not None:
        case.provider_in_network = payload.provider_in_network
    if payload.service_date is not None:
        case.service_date = payload.service_date
    if payload.narrative is not None:
        case.narrative = payload.narrative
    if payload.coordination_rule is not None:
        case.coordination_rule = payload.coordination_rule
    if payload.document_ids is not None:
        _validate_documents(db, case.family_id, payload.document_ids)
        case.document_ids = payload.document_ids
        case.status = "ready" if payload.document_ids else case.status
    if payload.policy_ids is not None:
        case.policy_version_ids = _versions_for_policies(db, case.family_id, payload.policy_ids)
    if payload.policy_order is not None:
        case.workflow_state = {**(case.workflow_state or {}), "policy_order": payload.policy_order}
    if payload.review_confirmed is not None:
        case.review_confirmed = payload.review_confirmed
    db.add(case)
    db.commit()
    db.refresh(case)
    return _detail(db, case)


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    case = case_for_user(db, case_id, user)
    db.delete(case)
    db.commit()


@router.post("/{case_id}/analyze", status_code=202)
def analyze_case(case_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    case = case_for_user(db, case_id, user)
    if case.status in ("running", "queued"):
        raise HTTPException(status_code=409, detail="This case is already being analysed.")
    pending = (
        db.query(ReviewItem)
        .filter(ReviewItem.case_id == case.id, ReviewItem.status == "pending")
        .count()
    )
    if pending and not case.review_confirmed:
        raise HTTPException(
            status_code=409,
            detail=f"{pending} extracted field(s) still need confirmation before the analysis can run.",
        )
    if not case.document_ids and not (case.workflow_state or {}).get("manual_lines"):
        raise HTTPException(status_code=422, detail="Attach a bill or estimate before starting the analysis.")
    from ..agents.runtime import start_run_async

    run_id = start_run_async(case.id)
    return {"status": "queued", "run_id": run_id, "message": "The agent workflow has started."}


@router.get("/{case_id}/results")
def case_results(case_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    case = case_for_user(db, case_id, user)
    return build_results(db, case)


@router.get("/{case_id}/trace")
def case_trace(
    case_id: int,
    since: int = 0,
    limit: int = 400,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    case = case_for_user(db, case_id, user)
    return build_trace(db, case, since, min(limit, 1000))


@router.post("/{case_id}/review")
def submit_review(
    case_id: int, payload: ReviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    case = case_for_user(db, case_id, user)
    items = db.query(ReviewItem).filter(ReviewItem.case_id == case.id).all()
    by_id = {item.id: item for item in items}
    for update in payload.items:
        item = by_id.get(update.id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Review item {update.id} is not part of this case.")
        item.status = update.status
        item.corrected_value = update.value
        item.resolved_at = utcnow()
        db.add(item)
    db.commit()
    remaining = (
        db.query(ReviewItem)
        .filter(ReviewItem.case_id == case.id, ReviewItem.status == "pending")
        .count()
    )
    if payload.confirm and remaining == 0:
        case.review_confirmed = True
        case.status = "ready"
        for document in db.query(Document).filter(Document.id.in_(case.document_ids or [])).all():
            document.status = "confirmed"
            document.confirmed_at = document.confirmed_at or utcnow()
            db.add(document)
        db.add(case)
        db.commit()
    db.refresh(case)
    return {
        "review_pending": remaining,
        "review_confirmed": case.review_confirmed,
        "status": case.status,
        "items": [
            review_out(item)
            for item in db.query(ReviewItem).filter(ReviewItem.case_id == case.id).order_by(ReviewItem.id).all()
        ],
        "next": "Start the analysis." if case.review_confirmed else "Resolve the remaining fields.",
    }


@router.get("/{case_id}/gaps")
def case_gaps(case_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    case = case_for_user(db, case_id, user)
    return build_gaps(db, case)


@router.post("/{case_id}/simulate")
def case_simulate(
    case_id: int, payload: SimulateIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    case = case_for_user(db, case_id, user)
    return simulate(db, case, payload.policies and {"policies": payload.policies} or {})


@router.get("/{case_id}/lines/{line_id}/explain")
def explain(
    case_id: int, line_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    case = case_for_user(db, case_id, user)
    result = explain_line(db, case, line_id)
    if not result:
        raise HTTPException(status_code=404, detail="That line is not part of an adjudicated claim.")
    return result


@router.get("/{case_id}/reports")
def case_reports(case_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    case = case_for_user(db, case_id, user)
    reports = db.query(Report).filter(Report.case_id == case.id).order_by(Report.id).all()
    return {
        "reports": [
            {
                "id": report.id,
                "kind": report.kind,
                "title": report.title,
                "mime": report.mime,
                "meta": report.meta or {},
                "created_at": report.created_at.isoformat() if report.created_at else None,
                "size_bytes": Path(report.path).stat().st_size if Path(report.path).exists() else 0,
            }
            for report in reports
        ]
    }


@router.get("/{case_id}/reports/{report_id}/download")
def download_report(
    case_id: int, report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    case = case_for_user(db, case_id, user)
    report = db.get(Report, report_id)
    if not report or report.case_id != case.id:
        raise HTTPException(status_code=404, detail="Report not found.")
    path = Path(report.path).resolve()
    allowed_roots = [REPORT_DIR.resolve(), AUDIO_DIR.resolve()]
    if not any(root in path.parents for root in allowed_roots) or not path.exists():
        raise HTTPException(status_code=404, detail="The report file is missing.")
    suffix = path.suffix
    filename = f"{case.title[:60].replace(' ', '-')}-{report.kind}{suffix}"
    return FileResponse(
        path,
        media_type=report.mime,
        filename=filename,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{case_id}/letters")
def case_letters(case_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    case = case_for_user(db, case_id, user)
    preauths = db.query(Preauthorization).filter(Preauthorization.case_id == case.id).all()
    reports = db.query(Report).filter(Report.case_id == case.id, Report.kind == "pdf_letter").all()
    letters = []
    for report in reports:
        meta = report.meta or {}
        preauth = next((p for p in preauths if p.id == meta.get("preauth_id")), None)
        policy = db.get(Policy, meta.get("policy_id")) if meta.get("policy_id") else None
        letters.append(
            {
                "report_id": report.id,
                "title": report.title,
                "insurer": policy.insurer_name if policy else None,
                "policy_number": policy.policy_number if policy else None,
                "status": report.meta.get("status"),
                "preauth_id": preauth.id if preauth else None,
                "reference": preauth.reference if preauth else None,
                "download_url": f"/api/cases/{case.id}/reports/{report.id}/download",
                "created_at": report.created_at.isoformat() if report.created_at else None,
            }
        )
    return {"letters": letters}


@router.post("/{case_id}/preauth/{preauth_id}/refresh")
def refresh_preauth(
    case_id: int, preauth_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    case = case_for_user(db, case_id, user)
    preauth = db.get(Preauthorization, preauth_id)
    if not preauth or preauth.case_id != case.id:
        raise HTTPException(status_code=404, detail="Pre-authorisation request not found.")
    service = MockInsurerService(db)
    response = service.pre_authorization(dict(preauth.request or {}))
    preauth.status = str(response.get("status") or preauth.status)
    preauth.reference = str(response.get("reference") or preauth.reference)
    preauth.response = response
    preauth.reason = "; ".join(response.get("reasons") or [])
    db.add(preauth)
    db.commit()
    return {
        "preauth": {
            "id": preauth.id,
            "status": preauth.status,
            "reference": preauth.reference,
            "reason": preauth.reason,
            "response": response,
        },
        "message": "The simulated insurer response was refreshed. Run the analysis again to apply any change.",
        "simulated": True,
    }
