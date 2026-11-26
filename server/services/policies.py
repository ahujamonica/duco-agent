"""Policy helpers: term application, versioning and extraction hand-off."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import Document, FamilyMember, Policy, PolicyMember, PolicyVersion
from ..schemas import TermsIn


def decimal(value, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def apply_terms(version: PolicyVersion, terms: TermsIn) -> None:
    version.sum_insured = decimal(terms.sum_insured)
    version.deductible = decimal(terms.deductible)
    version.deductible_used = decimal(terms.deductible_used)
    version.coinsurance_member = decimal(terms.coinsurance_member)
    version.oop_max = decimal(terms.oop_max)
    version.oop_used = decimal(terms.oop_used)
    version.annual_limit = decimal(terms.annual_limit)
    version.annual_limit_used = decimal(terms.annual_limit_used)
    version.preauth_threshold = decimal(terms.preauth_threshold)
    version.preauth_penalty_rate = decimal(terms.preauth_penalty_rate)
    version.waiting_period_days = int(terms.waiting_period_days or 0)
    version.allowed_factor = decimal(terms.allowed_factor, "1") or Decimal("1")
    version.network_only = bool(terms.network_only)
    version.preauth_always = bool(terms.preauth_always)
    version.covers_primary_exclusions = bool(terms.covers_primary_exclusions)
    version.sublimits = [
        {
            "key": item.key,
            "label": item.label,
            "limit": str(decimal(item.limit)),
            "used": str(decimal(item.used)),
            "applies_to_codes": item.applies_to_codes,
            "applies_to_categories": item.applies_to_categories,
            "basis": item.basis,
        }
        for item in terms.sublimits
    ]
    version.exclusions = [
        item.model_dump() if hasattr(item, "model_dump") else {"label": str(item), "keyword": str(item)}
        for item in terms.exclusions
    ]
    version.preauth_cpt_codes = terms.preauth_cpt_codes
    version.preauth_categories = terms.preauth_categories


def next_version_number(policy: Policy) -> int:
    return max((version.version for version in policy.versions), default=0) + 1


def create_version(
    db: Session,
    policy: Policy,
    terms: TermsIn,
    source: str = "manual",
    confirmed: bool = False,
    extraction: dict | None = None,
    change_note: str | None = None,
    effective_from: date | None = None,
) -> PolicyVersion:
    version = PolicyVersion(
        policy_id=policy.id,
        version=next_version_number(policy),
        effective_from=effective_from or policy.start_date or date.today(),
        source=source,
        confirmed=confirmed,
        extraction=extraction or {},
        change_note=change_note,
    )
    apply_terms(version, terms)
    db.add(version)
    db.flush()
    policy.updated_at = policy.updated_at
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return version


def upsert_member_links(db: Session, policy: Policy, links: list[dict]) -> None:
    """Replace the policy's member list with the supplied links."""
    db.query(PolicyMember).filter(PolicyMember.policy_id == policy.id).delete()
    db.commit()
    seen = set()
    for link in links:
        member_id = int(link["member_id"])
        if member_id in seen:
            continue
        seen.add(member_id)
        db.add(PolicyMember(policy_id=policy.id, member_id=member_id, role=str(link.get("role") or "dependent")))
    db.commit()
    db.refresh(policy)


def ensure_policyholder_link(db: Session, policy: Policy, family_members: dict[int, FamilyMember]) -> None:
    if policy.policyholder_member_id and policy.policyholder_member_id in family_members:
        existing = next(
            (link for link in policy.member_links if link.member_id == policy.policyholder_member_id), None
        )
        if existing:
            existing.role = "policyholder"
        else:
            db.add(
                PolicyMember(
                    policy_id=policy.id,
                    member_id=policy.policyholder_member_id,
                    role="policyholder",
                )
            )
        db.commit()


def apply_extraction_to_terms(fields: dict) -> tuple[dict, dict]:
    """Turn stored policy-document fields into policy data plus confidence map."""
    def value(key: str, default=None):
        field = fields.get(key) or {}
        return field.get("value", default)

    def confidence(key: str) -> float:
        return float((fields.get(key) or {}).get("confidence") or 0)

    def money_value(key: str, default: str = "0") -> str:
        raw = value(key)
        if raw in (None, ""):
            return default
        try:
            return f"{float(str(raw).replace(',', '')):.2f}"
        except ValueError:
            return default

    coinsurance_raw = value("coinsurance_member")
    coinsurance = "0"
    if coinsurance_raw not in (None, ""):
        try:
            number = float(str(coinsurance_raw))
            coinsurance = f"{number:.4f}" if number <= 1 else f"{number/100:.4f}"
        except ValueError:
            coinsurance = "0"

    terms = {
        "sum_insured": money_value("sum_insured"),
        "deductible": money_value("deductible"),
        "deductible_used": "0.00",
        "coinsurance_member": coinsurance,
        "oop_max": money_value("oop_max"),
        "oop_used": "0.00",
        "annual_limit": money_value("sum_insured"),
        "annual_limit_used": "0.00",
        "preauth_threshold": money_value("preauth_threshold"),
        "preauth_penalty_rate": "0",
        "waiting_period_days": int(value("waiting_period_days") or 0),
        "allowed_factor": "1",
        "network_only": bool(value("network_only") or False),
        "preauth_always": False,
        "covers_primary_exclusions": False,
        "sublimits": value("sublimits") or [],
        "exclusions": value("exclusions") or [],
        "preauth_cpt_codes": [],
        "preauth_categories": [],
    }
    confidence_map = {
        key: confidence(key)
        for key in (
            "insurer",
            "policy_number",
            "plan_name",
            "sum_insured",
            "deductible",
            "coinsurance_member",
            "oop_max",
            "preauth_threshold",
            "waiting_period_days",
        )
    }
    basics = {
        "insurer_name": value("insurer") or "",
        "plan_name": value("plan_name") or "",
        "policy_number": value("policy_number") or "",
        "start_date": value("policy_start"),
        "end_date": value("policy_end"),
        "policyholder_name": value("policyholder"),
    }
    return {"terms": terms, "basics": basics, "confidence": confidence_map}
