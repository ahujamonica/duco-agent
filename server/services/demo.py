"""Demo household, policies, documents and scenarios.

Everything here is generated or copied from `fixtures/`; no real patient data
is used. The demo uses exactly the same tables, agents, engine and mock APIs as
a live case — there is no separate result page and no hardcoded outcome.
"""

from __future__ import annotations

import io
import secrets
from datetime import date
from pathlib import Path

from PIL import Image, ImageFilter
from sqlalchemy.orm import Session

from ..config import ROOT, UPLOAD_DIR
from ..models import Case, Document, Family, FamilyMember, Policy, PolicyMember, PolicyVersion, User
from ..schemas import TermsIn
from ..security import create_token, hash_password
from ..services.document_intel import analyse_file, checksum, store_bytes
from ..services.policies import create_version

DEMO_EMAIL = "demo@duco.health"
DEMO_PASSWORD = "DuCOdemo!23"
FIXTURES = ROOT / "fixtures"

SCENARIOS = [
    {
        "key": "main",
        "title": "Aarav's ACL reconstruction and Priya's physiotherapy",
        "description": "Two claims, two policies, two different coordination outcomes. The full workflow: OCR, review, eligibility, pre-auth and dual adjudication.",
    },
    {
        "key": "excluded",
        "title": "Therapy with an excluded equipment item",
        "description": "A physiotherapy bill that includes home traction equipment the policy excludes. Shows a partially covered claim.",
    },
    {
        "key": "missing_docs",
        "title": "Surgery estimate with missing clinical documents",
        "description": "Only the surgeon's estimate is supplied. The pre-authorisation is rejected for a missing diagnosis, and the case shows what to upload.",
    },
    {
        "key": "inactive",
        "title": "A second policy that has lapsed",
        "description": "Priya has two policies on paper, but one is inactive. The engine keeps it in the trace and refuses to pay from it.",
    },
    {
        "key": "uncertain",
        "title": "A poor-quality scan that needs human review",
        "description": "A deliberately degraded photo of the invoice. The confidence gate pauses the run before any money is calculated.",
    },
]


def _or_create_user(db: Session) -> User:
    user = db.query(User).filter(User.email == DEMO_EMAIL).one_or_none()
    if user:
        return user
    user = User(
        name="Demo household",
        email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PASSWORD),
        locale="en",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _or_create_family(db: Session, user: User) -> Family:
    family = db.query(Family).filter(Family.owner_id == user.id, Family.name == "Sen household").one_or_none()
    if family:
        return family
    family = Family(
        owner_id=user.id,
        name="Sen household",
        coordination_rule="policyholder",
        notes="Demo household. All names, policies and amounts are fictional.",
    )
    db.add(family)
    db.commit()
    db.refresh(family)
    return family


def _or_create_members(db: Session, family: Family) -> dict[str, FamilyMember]:
    existing = {member.name: member for member in family.members}
    specs = [
        ("Priya Sen", date(1995, 4, 18), "self", "F"),
        ("Aarav Sen", date(1993, 9, 2), "spouse", "M"),
        ("Meera Sen", date(2016, 6, 12), "child", "F"),
    ]
    for name, dob, relation, gender in specs:
        if name in existing:
            continue
        member = FamilyMember(
            family_id=family.id,
            name=name,
            date_of_birth=dob,
            relation=relation,
            gender=gender,
        )
        db.add(member)
        db.commit()
        existing[name] = member
    return existing


def _terms(**overrides) -> TermsIn:
    values = dict(
        sum_insured="500000",
        deductible="5000",
        deductible_used="0",
        coinsurance_member="0.20",
        oop_max="60000",
        oop_used="0",
        annual_limit="500000",
        annual_limit_used="0",
        preauth_threshold="50000",
        preauth_penalty_rate="0.20",
        waiting_period_days=0,
        allowed_factor="1",
        network_only=False,
        preauth_always=False,
        covers_primary_exclusions=False,
        sublimits=[],
        exclusions=[],
        preauth_cpt_codes=["29888"],
        preauth_categories=[],
    )
    values.update(overrides)
    return TermsIn(**values)


def _or_create_policies(db: Session, family: Family, members: dict[str, FamilyMember]) -> dict[str, Policy]:
    existing = {policy.policy_number: policy for policy in family.policies}
    specs = [
        {
            "policy_number": "ICL-SEN-2024-001",
            "insurer_name": "ICICI Lombard",
            "plan_name": "SecureShield Corporate Health",
            "policyholder": "Priya Sen",
            "status": "active",
            "start": date(2024, 1, 1),
            "end": date(2027, 3, 31),
            "members": [("Priya Sen", "policyholder"), ("Aarav Sen", "spouse"), ("Meera Sen", "dependent")],
            "terms": _terms(
                deductible_used="1500",
                oop_used="1500",
                sublimits=[
                    {
                        "key": "therapy",
                        "label": "Annual physiotherapy limit",
                        "limit": "20000",
                        "used": "0",
                        "applies_to_codes": [],
                        "applies_to_categories": ["therapy"],
                        "basis": "per_year",
                    }
                ],
                exclusions=[
                    {
                        "label": "Home traction and durable equipment",
                        "keyword": "equipment",
                    }
                ],
            ),
        },
        {
            "policy_number": "HDE-SEN-2024-778",
            "insurer_name": "HDFC ERGO",
            "plan_name": "HealthGuard Plus Family Floater",
            "policyholder": "Aarav Sen",
            "status": "active",
            "start": date(2024, 6, 1),
            "end": date(2027, 5, 31),
            "members": [("Aarav Sen", "policyholder"), ("Priya Sen", "spouse"), ("Meera Sen", "dependent")],
            "terms": _terms(
                coinsurance_member="0.10",
                oop_max="80000",
                oop_used="2000",
                deductible_used="2000",
                annual_limit="400000",
                sum_insured="400000",
                preauth_penalty_rate="0.25",
                preauth_threshold="50000",
                sublimits=[
                    {
                        "key": "therapy",
                        "label": "Annual physiotherapy limit",
                        "limit": "15000",
                        "used": "0",
                        "applies_to_codes": [],
                        "applies_to_categories": ["therapy"],
                        "basis": "per_year",
                    }
                ],
                exclusions=[{"label": "Durable medical equipment", "keyword": "equipment"}],
            ),
        },
        {
            "policy_number": "STA-SEN-2022-311",
            "insurer_name": "Star Health",
            "plan_name": "Individual Top-up",
            "policyholder": "Priya Sen",
            "status": "inactive",
            "start": date(2022, 4, 1),
            "end": date(2025, 3, 31),
            "members": [("Priya Sen", "policyholder")],
            "terms": _terms(
                sum_insured="300000",
                annual_limit="300000",
                deductible="10000",
                coinsurance_member="0.20",
                oop_max="50000",
                preauth_threshold="30000",
            ),
        },
    ]
    for spec in specs:
        if spec["policy_number"] in existing:
            continue
        holder = members[spec["policyholder"]]
        policy = Policy(
            family_id=family.id,
            insurer_name=spec["insurer_name"],
            plan_name=spec["plan_name"],
            policy_number=spec["policy_number"],
            policyholder_member_id=holder.id,
            status=spec["status"],
            start_date=spec["start"],
            end_date=spec["end"],
            coordination_rule="policyholder",
        )
        db.add(policy)
        db.commit()
        db.refresh(policy)
        for name, role in spec["members"]:
            db.add(PolicyMember(policy_id=policy.id, member_id=members[name].id, role=role))
        db.commit()
        version: PolicyVersion = create_version(
            db, policy, spec["terms"], source="manual", confirmed=True, change_note="Demo schedule"
        )
        policy.policyholder_member_id = holder.id
        db.add(policy)
        db.commit()
        existing[spec["policy_number"]] = policy
    return existing


def _ensure_document(
    db: Session,
    user: User,
    family: Family,
    filename: str,
    doc_type: str,
    content: bytes,
    *,
    confirmed: bool = True,
    display_name: str | None = None,
) -> Document:
    digest = checksum(content)
    existing = (
        db.query(Document).filter(Document.family_id == family.id, Document.sha256 == digest).one_or_none()
    )
    if existing:
        return existing
    stored_name, path = store_bytes(content, Path(filename).suffix.lower() or ".png")
    document = Document(
        family_id=family.id,
        uploaded_by=user.id,
        original_filename=display_name or filename,
        stored_name=stored_name,
        mime="application/pdf" if filename.endswith(".pdf") else ("text/plain" if filename.endswith(".txt") else "image/png"),
        size_bytes=len(content),
        sha256=digest,
        doc_type=doc_type,
        status="uploaded",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    result = analyse_file(path, document.original_filename, hint=doc_type)
    document.doc_type = result["doc_type"]
    document.classification_confidence = result["classification_confidence"]
    document.method = result["method"]
    document.pages = result["pages"]
    document.mean_ocr_confidence = result["mean_ocr_confidence"]
    document.raw_text = result["text"][:20000]
    fields = dict(result["fields"])
    fields["_lines"] = result["lines"]
    fields["_classification"] = {
        "confidence": result["classification_confidence"],
        "evidence": result["classification_evidence"],
    }
    document.fields = fields
    document.issues = result["issues"]
    document.status = "confirmed" if confirmed else ("needs_review" if result["needs_review"] else "processed")
    if confirmed:
        from ..models import utcnow

        document.confirmed_at = utcnow()
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _degraded_invoice() -> bytes:
    source = FIXTURES / "priya_pt_invoice.png"
    image = Image.open(source).convert("RGB")
    image = image.rotate(2.2, expand=True, fillcolor=(235, 233, 228))
    image = image.resize((int(image.width * 0.72), int(image.height * 0.72)))
    image = image.filter(ImageFilter.GaussianBlur(0.9))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=28)
    return buffer.getvalue()


def _snapshot_version(db: Session, policy: Policy, note: str) -> PolicyVersion:
    """Give a demo scenario its own benefit-year snapshot.

    Scenarios would otherwise consume each other's deductibles and sub-limits
    because a policy's accumulators are shared across cases for the same
    benefit year. A real household would live with that; a demo needs each
    scenario to be reproducible, and versioning is the honest way to isolate it.
    """
    import copy

    source = policy.current_version
    clone = PolicyVersion(
        policy_id=policy.id,
        version=max((v.version for v in policy.versions), default=0) + 1,
        effective_from=source.effective_from if source else None,
        sum_insured=source.sum_insured,
        deductible=source.deductible,
        deductible_used=source.deductible_used,
        coinsurance_member=source.coinsurance_member,
        oop_max=source.oop_max,
        oop_used=source.oop_used,
        annual_limit=source.annual_limit,
        annual_limit_used=source.annual_limit_used,
        preauth_threshold=source.preauth_threshold,
        preauth_penalty_rate=source.preauth_penalty_rate,
        waiting_period_days=source.waiting_period_days,
        allowed_factor=source.allowed_factor,
        network_only=source.network_only,
        preauth_always=source.preauth_always,
        covers_primary_exclusions=source.covers_primary_exclusions,
        sublimits=copy.deepcopy(source.sublimits or []),
        exclusions=copy.deepcopy(source.exclusions or []),
        preauth_cpt_codes=list(source.preauth_cpt_codes or []),
        preauth_categories=list(source.preauth_categories or []),
        extraction={"demo": True},
        source="demo",
        confirmed=True,
        change_note=note,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return clone


def _ensure_case(
    db: Session,
    family: Family,
    title: str,
    *,
    patient: FamilyMember,
    provider: str,
    documents: list[Document],
    policies: list[Policy],
    narrative: str | None,
    review_confirmed: bool,
    manual_lines: list[dict] | None = None,
    snapshot: bool = False,
) -> Case:
    existing = db.query(Case).filter(Case.family_id == family.id, Case.title == title).one_or_none()
    if existing:
        return existing
    if snapshot:
        versions = [_snapshot_version(db, policy, f"Demo snapshot — {title}") for policy in policies]
        version_ids = [version.id for version in versions]
    else:
        version_ids = [policy.current_version.id for policy in policies if policy.current_version]
    case = Case(
        family_id=family.id,
        title=title,
        patient_member_id=patient.id,
        provider_name=provider,
        provider_in_network=True,
        service_date=date(2026, 11, 12),
        narrative=narrative,
        coordination_rule="policyholder",
        policy_version_ids=version_ids,
        document_ids=[document.id for document in documents],
        review_confirmed=review_confirmed,
        status="ready",
        workflow_state={
            "manual_lines": manual_lines or [],
            "gaps": [],
            "assumptions": [],
            "stage": "ready",
            "demo": True,
        },
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def seed(db: Session) -> dict:
    user = _or_create_user(db)
    family = _or_create_family(db, user)
    members = _or_create_members(db, family)
    policies = _or_create_policies(db, family, members)

    invoice_bytes = (FIXTURES / "priya_pt_invoice.png").read_bytes()
    mri_bytes = (FIXTURES / "aarav_mri_report.pdf").read_bytes()
    estimate_bytes = (FIXTURES / "surgeon_estimate.jpg").read_bytes()
    query_text = (FIXTURES / "user_query.txt").read_text(encoding="utf-8")

    invoice_doc = _ensure_document(db, user, family, "priya_pt_invoice.png", "invoice", invoice_bytes)
    if invoice_doc and not (invoice_doc.fields or {}).get("provider", {}).get("value"):
        invoice_fields = dict(invoice_doc.fields or {})
        invoice_fields["provider"] = {
            "value": "Lakshmi Physiotherapy",
            "confidence": 0.99,
            "source": "demo fixture",
            "evidence": "Provider name is fixed in the demo invoice fixture.",
            "status": "ok",
        }
        invoice_doc.fields = invoice_fields
        db.add(invoice_doc)
        db.commit()
    mri_doc = _ensure_document(db, user, family, "aarav_mri_report.pdf", "radiology", mri_bytes)
    estimate_doc = _ensure_document(db, user, family, "surgeon_estimate.jpg", "estimate", estimate_bytes)
    query_doc = _ensure_document(
        db, user, family, "user_query.txt", "transcript", query_text.encode("utf-8")
    )
    degraded_doc = _ensure_document(
        db,
        user,
        family,
        "priya_pt_invoice_degraded.jpg",
        "invoice",
        _degraded_invoice(),
        confirmed=False,
        display_name="priya_pt_invoice_scan.jpg",
    )

    policy_a = policies["ICL-SEN-2024-001"]
    policy_b = policies["HDE-SEN-2024-778"]
    policy_c = policies["STA-SEN-2022-311"]

    main_case = _ensure_case(
        db,
        family,
        SCENARIOS[0]["title"],
        patient=members["Aarav Sen"],
        provider="Sunrise Multispecialty Hospital",
        documents=[mri_doc, estimate_doc, invoice_doc, query_doc],
        policies=[policy_a, policy_b],
        narrative=query_text[:4000],
        review_confirmed=True,
    )
    excluded_case = _ensure_case(
        db,
        family,
        SCENARIOS[1]["title"],
        patient=members["Priya Sen"],
        provider="Lakshmi Physiotherapy",
        documents=[invoice_doc],
        policies=[policy_a],
        narrative=None,
        review_confirmed=True,
        snapshot=True,
    )
    missing_case = _ensure_case(
        db,
        family,
        SCENARIOS[2]["title"],
        patient=members["Aarav Sen"],
        provider="Sunrise Multispecialty Hospital",
        documents=[estimate_doc],
        policies=[policy_b],
        narrative="Planned ACL reconstruction. Radiology report not supplied yet.",
        review_confirmed=True,
        snapshot=True,
    )
    inactive_case = _ensure_case(
        db,
        family,
        SCENARIOS[3]["title"],
        patient=members["Priya Sen"],
        provider="Lakshmi Physiotherapy",
        documents=[invoice_doc],
        policies=[policy_a, policy_c],
        narrative=None,
        review_confirmed=True,
        snapshot=True,
    )
    uncertain_case = _ensure_case(
        db,
        family,
        SCENARIOS[4]["title"],
        patient=members["Priya Sen"],
        provider="Lakshmi Physiotherapy",
        documents=[degraded_doc],
        policies=[policy_a],
        narrative=None,
        review_confirmed=False,
        snapshot=True,
    )

    mapping = {
        "main": main_case,
        "excluded": excluded_case,
        "missing_docs": missing_case,
        "inactive": inactive_case,
        "uncertain": uncertain_case,
    }
    return {
        "token": create_token(user.id),
        "user": {"id": user.id, "name": user.name, "email": user.email},
        "family_id": family.id,
        "case_id": main_case.id,
        "scenarios": [
            {
                **scenario,
                "case_id": mapping[scenario["key"]].id,
                "status": mapping[scenario["key"]].status,
            }
            for scenario in SCENARIOS
        ],
        "credentials": {"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
        "note": "All names, policies and amounts in this demo are fictional. Insurer responses are simulated.",
    }


def reset(db: Session) -> dict:
    user = db.query(User).filter(User.email == DEMO_EMAIL).one_or_none()
    if not user:
        return {"reset": False, "message": "The demo was not seeded."}
    for family in user.families:
        for document in family.documents:
            (UPLOAD_DIR / document.stored_name).unlink(missing_ok=True)
    db.delete(user)
    db.commit()
    return {"reset": True, "message": "Demo data removed. Seed it again to start over."}


def status(db: Session) -> dict:
    user = db.query(User).filter(User.email == DEMO_EMAIL).one_or_none()
    if not user:
        return {"seeded": False}
    family = db.query(Family).filter(Family.owner_id == user.id).first()
    cases = db.query(Case).filter(Case.family_id == family.id).all() if family else []
    return {
        "seeded": True,
        "email": DEMO_EMAIL,
        "family_id": family.id if family else None,
        "cases": [
            {"id": case.id, "title": case.title, "status": case.status} for case in cases
        ],
    }
