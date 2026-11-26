"""Response serialisers shared by the routers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .models import Case, Document, Family, FamilyMember, Policy, PolicyMember, PolicyVersion, ReviewItem


def _s(value) -> str:
    if value is None:
        return "0.00"
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def age_of(member: FamilyMember) -> int | None:
    if member.age_years is not None:
        return member.age_years
    if not member.date_of_birth:
        return None
    today = date.today()
    dob = member.date_of_birth
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def member_out(member: FamilyMember) -> dict:
    return {
        "id": member.id,
        "family_id": member.family_id,
        "name": member.name,
        "date_of_birth": member.date_of_birth.isoformat() if member.date_of_birth else None,
        "age": age_of(member),
        "relation": member.relation,
        "gender": member.gender,
        "phone": member.phone,
        "notes": member.notes,
        "policies": [
            {
                "policy_id": link.policy_id,
                "insurer": link.policy.insurer_name if link.policy else None,
                "plan_name": link.policy.plan_name if link.policy else None,
                "role": link.role,
            }
            for link in member.policy_links
        ],
    }


def version_out(version: PolicyVersion) -> dict:
    return {
        "id": version.id,
        "version": version.version,
        "effective_from": version.effective_from.isoformat() if version.effective_from else None,
        "terms": {
            "sum_insured": _s(version.sum_insured),
            "deductible": _s(version.deductible),
            "deductible_used": _s(version.deductible_used),
            "coinsurance_member": str(version.coinsurance_member),
            "oop_max": _s(version.oop_max),
            "oop_used": _s(version.oop_used),
            "annual_limit": _s(version.annual_limit),
            "annual_limit_used": _s(version.annual_limit_used),
            "preauth_threshold": _s(version.preauth_threshold),
            "preauth_penalty_rate": str(version.preauth_penalty_rate),
            "waiting_period_days": version.waiting_period_days,
            "allowed_factor": str(version.allowed_factor),
            "network_only": version.network_only,
            "preauth_always": version.preauth_always,
            "covers_primary_exclusions": version.covers_primary_exclusions,
            "sublimits": version.sublimits or [],
            "exclusions": version.exclusions or [],
            "preauth_cpt_codes": version.preauth_cpt_codes or [],
            "preauth_categories": version.preauth_categories or [],
        },
        "source": version.source,
        "confirmed": version.confirmed,
        "change_note": version.change_note,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "extraction": version.extraction or {},
    }


def policy_out(policy: Policy, detail: bool = True) -> dict:
    current = policy.current_version
    data = {
        "id": policy.id,
        "family_id": policy.family_id,
        "insurer_name": policy.insurer_name,
        "plan_name": policy.plan_name,
        "policy_number": policy.policy_number,
        "policyholder_member_id": policy.policyholder_member_id,
        "policyholder_name": next(
            (link.member.name for link in policy.member_links if link.role == "policyholder"),
            None,
        ),
        "status": policy.status,
        "start_date": policy.start_date.isoformat() if policy.start_date else None,
        "end_date": policy.end_date.isoformat() if policy.end_date else None,
        "coordination_rule": policy.coordination_rule,
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "current_version": version_out(current) if current else None,
        "members": [
            {
                "member_id": link.member_id,
                "name": link.member.name if link.member else None,
                "role": link.role,
                "relation": link.member.relation if link.member else None,
            }
            for link in policy.member_links
        ],
        "version_count": len(policy.versions),
    }
    if detail:
        data["versions"] = [version_out(version) for version in policy.versions]
    return data


def family_out(family: Family, detail: bool = True) -> dict:
    return {
        "id": family.id,
        "name": family.name,
        "coordination_rule": family.coordination_rule,
        "notes": family.notes,
        "created_at": family.created_at.isoformat() if family.created_at else None,
        "members": [member_out(member) for member in family.members],
        "policies": [policy_out(policy, detail=False) for policy in family.policies],
        "counts": {
            "members": len(family.members),
            "policies": len(family.policies),
            "documents": len(family.documents),
            "cases": len(family.cases),
        },
        "cases": [
            {
                "id": case.id,
                "title": case.title,
                "status": case.status,
                "patient_member_id": case.patient_member_id,
                "claim_count": len(case.claims),
                "procedure_count": sum(len(claim.lines) for claim in case.claims),
                "adjudication_count": len(case.adjudications),
                "totals": case.totals or {},
                "created_at": case.created_at.isoformat() if case.created_at else None,
            }
            for case in family.cases[:10]
        ],
        **({"documents": [document_out(doc, include_fields=False) for doc in family.documents]} if detail else {}),
    }


def document_out(document: Document, include_fields: bool = True) -> dict:
    fields = document.fields or {}
    lines = fields.get("_lines") or []
    visible_fields = {key: value for key, value in fields.items() if not key.startswith("_")}
    data = {
        "id": document.id,
        "family_id": document.family_id,
        "filename": document.original_filename,
        "mime": document.mime,
        "size_bytes": document.size_bytes,
        "doc_type": document.doc_type,
        "classification_confidence": float(document.classification_confidence or 0),
        "classification_evidence": (fields.get("_classification") or {}).get("evidence") or [],
        "status": document.status,
        "method": document.method,
        "pages": document.pages,
        "mean_ocr_confidence": float(document.mean_ocr_confidence) if document.mean_ocr_confidence is not None else None,
        "issues": document.issues or [],
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "confirmed_at": document.confirmed_at.isoformat() if document.confirmed_at else None,
        "lines": lines,
        "field_count": len(visible_fields),
    }
    if include_fields:
        data["fields"] = visible_fields
    return data


def review_out(item: ReviewItem) -> dict:
    return {
        "id": item.id,
        "case_id": item.case_id,
        "document_id": item.document_id,
        "field_key": item.field_key,
        "label": item.label,
        "extracted_value": item.extracted_value,
        "confidence": float(item.confidence or 0),
        "source_text": item.source_text,
        "reason": item.reason,
        "status": item.status,
        "corrected_value": item.corrected_value,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def case_out(case: Case) -> dict:
    return {
        "id": case.id,
        "family_id": case.family_id,
        "title": case.title,
        "status": case.status,
        "patient_member_id": case.patient_member_id,
        "provider_name": case.provider_name,
        "provider_in_network": case.provider_in_network,
        "service_date": case.service_date.isoformat() if case.service_date else None,
        "narrative": case.narrative,
        "coordination_rule": case.coordination_rule,
        "policy_version_ids": case.policy_version_ids or [],
        "document_ids": case.document_ids or [],
        "review_confirmed": case.review_confirmed,
        "totals": case.totals or {},
        "error": case.error,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        "completed_at": case.completed_at.isoformat() if case.completed_at else None,
    }
