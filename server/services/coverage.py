"""Glue between the database and the pure coordination engine.

Two responsibilities:

* turn a stored policy version into an :class:`InsurancePlan`;
* decide the payer order for one claim using a *configurable* rule, with the
  evidence for every placement and an explicit assumption when the rule cannot
  be satisfied from the data.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from duco_agent.engines.coordination import (
    ClaimInput,
    Exclusion,
    InsurancePlan,
    LineInput,
    OrderDecision,
    Sublimit,
    money,
)

from ..models import Case, Claim, Family, FamilyMember, Policy, PolicyMember, PolicyVersion

COB_RULES = {
    "policyholder": "The policy on which the patient is the policyholder pays first",
    "birthday": "The policyholder with the earlier birthday in the year pays first",
    "longest_coverage": "The policy that has been in force longest pays first",
    "manual": "The order chosen for this case pays first",
}


def _dec(value) -> Decimal:
    return money(value or 0)


def plan_key(policy: Policy, version: PolicyVersion) -> str:
    return f"P{policy.id}V{version.id}"


def plan_from_version(
    policy: Policy,
    version: PolicyVersion,
    link: PolicyMember | None,
    rule: str,
    accumulator=None,
) -> InsurancePlan:
    sublimits = []
    for item in version.sublimits or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("label") or "sub-limit")
        used = _dec(item.get("used"))
        if accumulator is not None:
            used = _dec((accumulator.sublimits or {}).get(key, used))
        sublimits.append(
            Sublimit(
                key=key,
                label=str(item.get("label") or "Sub-limit"),
                limit=_dec(item.get("limit")),
                used=used,
                applies_to_codes=[str(code) for code in item.get("applies_to_codes") or []],
                applies_to_categories=[str(cat) for cat in item.get("applies_to_categories") or []],
                basis=str(item.get("basis") or "per_year"),
            )
        )
    exclusions = []
    for item in version.exclusions or []:
        if isinstance(item, str):
            exclusions.append(Exclusion(label=item, keyword=item))
        elif isinstance(item, dict):
            exclusions.append(
                Exclusion(
                    label=str(item.get("label") or item.get("keyword") or item.get("code") or "Excluded benefit"),
                    code=str(item.get("code")) if item.get("code") else None,
                    keyword=str(item.get("keyword") or item.get("label") or "") or None,
                )
            )
    return InsurancePlan(
        key=plan_key(policy, version),
        policy_id=policy.id,
        version_id=version.id,
        insurer=policy.insurer_name,
        plan_name=policy.plan_name,
        policy_number=policy.policy_number,
        status=policy.status,
        start_date=policy.start_date,
        end_date=policy.end_date,
        sum_insured=_dec(version.sum_insured),
        deductible_total=_dec(version.deductible),
        deductible_used=_dec(accumulator.deductible_used if accumulator is not None else version.deductible_used),
        coinsurance_member=_dec(version.coinsurance_member),
        oop_max=_dec(version.oop_max),
        oop_used=_dec(accumulator.oop_used if accumulator is not None else version.oop_used),
        annual_limit=_dec(version.annual_limit),
        annual_limit_used=_dec(
            accumulator.annual_limit_used if accumulator is not None else version.annual_limit_used
        ),
        sublimits=sublimits,
        exclusions=exclusions,
        preauth_threshold=_dec(version.preauth_threshold),
        preauth_penalty_rate=_dec(version.preauth_penalty_rate),
        preauth_cpt_codes=[str(code) for code in version.preauth_cpt_codes or []],
        preauth_categories=[str(cat) for cat in version.preauth_categories or []],
        preauth_always=bool(version.preauth_always),
        waiting_period_days=int(version.waiting_period_days or 0),
        allowed_factor=_dec(version.allowed_factor) or Decimal("1"),
        network_only=bool(version.network_only),
        covers_primary_exclusions=bool(version.covers_primary_exclusions),
        coordination_rule=rule,
        policyholder_name="",
        member_role=(link.role if link else "not_covered"),
    )


def version_for(db: Session, policy: Policy, version_id: int | None) -> PolicyVersion | None:
    if version_id:
        found = db.get(PolicyVersion, version_id)
        if found and found.policy_id == policy.id:
            return found
    return policy.current_version


def selected_policies(db: Session, case: Case) -> list[tuple[Policy, PolicyVersion]]:
    pairs: list[tuple[Policy, PolicyVersion]] = []
    for policy_id in case.policy_version_ids or []:
        # policy_version_ids stores version ids; resolve to their policies.
        version = db.get(PolicyVersion, int(policy_id))
        if not version:
            policy = db.get(Policy, int(policy_id))
            if policy and policy.current_version:
                pairs.append((policy, policy.current_version))
            continue
        policy = db.get(Policy, version.policy_id)
        if policy:
            pairs.append((policy, version))
    # de-duplicate by policy, keeping the selected version
    seen: set[int] = set()
    unique: list[tuple[Policy, PolicyVersion]] = []
    for policy, version in pairs:
        if policy.id in seen:
            continue
        seen.add(policy.id)
        unique.append((policy, version))
    return unique


def member_policies_for_claim(
    db: Session, family_id: int, member_id: int
) -> list[tuple[Policy, PolicyVersion, PolicyMember | None]]:
    policies = (
        db.query(Policy)
        .filter(Policy.family_id == family_id)
        .order_by(Policy.id)
        .all()
    )
    out = []
    for policy in policies:
        version = policy.current_version
        if not version:
            continue
        link = (
            db.query(PolicyMember)
            .filter(PolicyMember.policy_id == policy.id, PolicyMember.member_id == member_id)
            .one_or_none()
        )
        out.append((policy, version, link))
    return out


def _years_old(dob: date | None, on: date | None) -> int | None:
    if not dob:
        return None
    ref = on or date.today()
    return ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))


def determine_order(
    db: Session,
    case: Case,
    claim_member: FamilyMember,
    selected: list[tuple[Policy, PolicyVersion]],
    rule: str,
    explicit_order: list[int] | None = None,
    service_date: date | None = None,
) -> tuple[list[InsurancePlan], list[OrderDecision], list[str], list[str]]:
    """Return plans in payer order, the decisions, and assumptions/warnings."""
    assumptions: list[str] = []
    warnings: list[str] = []
    candidates: list[dict] = []

    for policy, version in selected:
        link = (
            db.query(PolicyMember)
            .filter(PolicyMember.policy_id == policy.id, PolicyMember.member_id == claim_member.id)
            .one_or_none()
        )
        role = link.role if link else "not_covered"
        if role == "not_covered":
            continue
        policyholder = db.get(FamilyMember, policy.policyholder_member_id) if policy.policyholder_member_id else None
        candidates.append(
            {
                "policy": policy,
                "version": version,
                "link": link,
                "role": role,
                "policyholder": policyholder,
                "start": policy.start_date or date(1970, 1, 1),
                "active": policy.status == "active",
            }
        )

    if not candidates:
        warnings.append(
            f"No selected policy covers {claim_member.name}. Add a policy that lists this member before adjudication."
        )
        return [], [], assumptions, warnings

    def sort_key(item: dict):
        policy = item["policy"]
        if rule == "manual" and explicit_order:
            try:
                return (explicit_order.index(policy.id), 0, policy.id)
            except ValueError:
                return (len(explicit_order), 0, policy.id)
        if rule == "birthday":
            holder = item["policyholder"]
            dob = holder.date_of_birth if holder else None
            if dob:
                return (0, dob.month * 100 + dob.day, item["start"])
            return (1, 0, item["start"])
        if rule == "longest_coverage":
            return (0, item["start"], policy.id)
        # policyholder rule: their own plan first, then the earliest plan.
        return (0 if item["role"] == "policyholder" else 1, item["start"], policy.id)

    active = [c for c in candidates if c["active"]]
    inactive = [c for c in candidates if not c["active"]]
    ordered_active = sorted(active, key=sort_key)
    if rule == "manual" and explicit_order:
        ordered_active = sorted(
            active,
            key=lambda c: (
                explicit_order.index(c["policy"].id) if c["policy"].id in explicit_order else len(explicit_order)
            ),
        )
    ordered = ordered_active + sorted(inactive, key=sort_key)

    role_names = ["primary", "secondary", "tertiary", "quaternary"]
    decisions: list[OrderDecision] = []
    plans: list[InsurancePlan] = []
    for index, item in enumerate(ordered):
        policy: Policy = item["policy"]
        version: PolicyVersion = item["version"]
        role = role_names[min(index, len(role_names) - 1)]
        evidence = [
            f"{claim_member.name} is listed as {item['role']} on {policy.insurer_name} {policy.plan_name}",
            f"policy status: {policy.status}",
        ]
        if item["policyholder"]:
            holder = item["policyholder"]
            evidence.append(f"policyholder: {holder.name}")
            if rule == "birthday" and holder.date_of_birth:
                evidence.append(f"policyholder date of birth: {holder.date_of_birth.isoformat()}")
            if rule == "longest_coverage" and policy.start_date:
                evidence.append(f"in force since {policy.start_date.isoformat()}")
        assumption = None
        if rule == "policyholder" and item["role"] != "policyholder":
            if all(c["role"] != "policyholder" for c in candidates):
                assumption = (
                    f"{claim_member.name} is a dependent on every selected policy, so the rule cannot pick an "
                    "own-employer plan. The earliest effective policy was placed first; confirm this order."
                )
        if rule == "birthday" and not (item["policyholder"] and item["policyholder"].date_of_birth):
            assumption = (
                "A policyholder date of birth is missing, so the birthday rule could not be applied to every "
                "policy. The earliest effective policy was used as the tie-breaker."
            )
        if not item["active"]:
            evidence.append("this policy is inactive and will not pay until it is corrected")
        decisions.append(
            OrderDecision(
                plan_key=plan_key(policy, version),
                role=role,
                order=index + 1,
                rule=rule,
                evidence=evidence,
                assumption=assumption,
            )
        )
        if assumption:
            assumptions.append(assumption)
        accumulator = None
        if item["link"] is not None:
            from .accumulators import get_accumulator

            accumulator = get_accumulator(db, policy, version, item["link"].member_id)
        plans.append(plan_from_version(policy, version, item["link"], rule, accumulator))
        if item["policyholder"]:
            plans[-1].policyholder_name = item["policyholder"].name

    if rule == "manual" and not explicit_order:
        warnings.append("Manual order was requested but no order was supplied; policies were ordered by start date.")
    if rule == "birthday":
        assumptions.append(
            "The birthday rule is a US coordination convention. Indian insurers may settle multiple indemnity "
            "policies on a contribution basis instead; confirm with both insurers."
        )
    if len(plans) > 1:
        assumptions.append(
            "Primary/secondary ordering is a modelling choice. Under a contribution clause the insurers may "
            "share the claim pro-rata instead; the calculated patient share can differ."
        )
    return plans, decisions, assumptions, warnings


def claim_input(claim: Claim, service_date: date | None) -> ClaimInput:
    lines = [
        LineInput(
            line_id=line.id,
            description=line.description,
            billed=_dec(line.billed_amount),
            quantity=line.quantity or 1,
            unit_rate=_dec(line.unit_rate),
            cpt_code=line.cpt_code,
            icd_codes=line.icd_codes or [],
            category=line.category,
            excluded=bool(line.excluded),
            evidence=line.evidence or "",
        )
        for line in claim.lines
    ]
    return ClaimInput(
        claim_id=claim.id,
        patient_name=claim.patient_name,
        member_key=str(claim.member_id),
        provider_name=claim.provider_name,
        service_date=claim.service_date or service_date,
        lines=lines,
        bill_number=claim.bill_number,
        provider_in_network=True,
    )
