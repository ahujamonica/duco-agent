"""Per-member benefit accumulators.

The policy schedule often states a deductible that has already been used this
year. That usage belongs to the policyholder, not to every insured person, so
each member gets their own accumulator row seeded on first use.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import Policy, PolicyAccumulator, PolicyVersion


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def get_accumulator(db: Session, policy: Policy, version: PolicyVersion, member_id: int) -> PolicyAccumulator:
    found = (
        db.query(PolicyAccumulator)
        .filter(
            PolicyAccumulator.policy_version_id == version.id,
            PolicyAccumulator.member_id == member_id,
        )
        .one_or_none()
    )
    if found:
        return found
    inherited = member_id == policy.policyholder_member_id
    sublimits = {}
    for item in version.sublimits or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("label") or "sub-limit")
        sublimits[key] = str(_dec(item.get("used")) if inherited else Decimal("0"))
    accumulator = PolicyAccumulator(
        policy_version_id=version.id,
        member_id=member_id,
        deductible_used=_dec(version.deductible_used) if inherited else Decimal("0"),
        oop_used=_dec(version.oop_used) if inherited else Decimal("0"),
        annual_limit_used=_dec(version.annual_limit_used) if inherited else Decimal("0"),
        sublimits=sublimits,
    )
    db.add(accumulator)
    db.commit()
    db.refresh(accumulator)
    return accumulator


def ensure_for_policy_members(db: Session, policy: Policy) -> None:
    version = policy.current_version
    if not version:
        return
    for link in policy.member_links:
        get_accumulator(db, policy, version, link.member_id)
