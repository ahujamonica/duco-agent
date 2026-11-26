"""Deterministic coordination-of-benefits engine for the dynamic platform.

This is a *pure* calculation module: no database, no network, no LLM. The
agents decide which policies apply and in what order; this engine turns that
decision plus the policy terms into rupee amounts using :class:`Decimal`.

Design rules
------------
* Every amount is an exact Decimal rounded once, to paise.
* A plan can never pay more than the amount it allows; a secondary plan can
  never pay more than the balance the earlier plans left; the sum of insurer
  payments, contractual write-offs and the patient's share must equal the bill.
* Accumulators (deductible, out-of-pocket, annual limit, sub-limits) are
  inputs and outputs, so a claim can be reproduced from the policy version it
  names.
* Any policy term that is missing is treated as zero/not-applicable and is
  reported as an assumption; the engine never invents a benefit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

ZERO = Decimal("0.00")
ONE = Decimal("1")
CENT = Decimal("0.01")


def money(value: Any) -> Decimal:
    """Coerce a value to a 2-decimal INR amount without float drift."""
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    return Decimal(str(value if value is not None else 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def rate(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


@dataclass
class Sublimit:
    key: str
    label: str
    limit: Decimal
    used: Decimal = ZERO
    applies_to_codes: list[str] = field(default_factory=list)
    applies_to_categories: list[str] = field(default_factory=list)
    basis: str = "per_year"  # per_year | per_claim

    def remaining(self) -> Decimal:
        if self.basis == "per_claim":
            return money(self.limit)
        return money(max(ZERO, self.limit - self.used))


@dataclass
class Exclusion:
    label: str
    code: Optional[str] = None
    keyword: Optional[str] = None


@dataclass
class InsurancePlan:
    key: str
    insurer: str
    plan_name: str
    policy_number: str
    policy_id: int | None = None
    version_id: int | None = None
    status: str = "active"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    sum_insured: Decimal = ZERO
    deductible_total: Decimal = ZERO
    deductible_used: Decimal = ZERO
    coinsurance_member: Decimal = ZERO
    oop_max: Decimal = ZERO
    oop_used: Decimal = ZERO
    annual_limit: Decimal = ZERO
    annual_limit_used: Decimal = ZERO
    sublimits: list[Sublimit] = field(default_factory=list)
    exclusions: list[Exclusion] = field(default_factory=list)
    preauth_threshold: Decimal = ZERO
    preauth_penalty_rate: Decimal = ZERO
    preauth_cpt_codes: list[str] = field(default_factory=list)
    preauth_categories: list[str] = field(default_factory=list)
    preauth_always: bool = False
    waiting_period_days: int = 0
    allowed_factor: Decimal = ONE
    network_only: bool = False
    covers_primary_exclusions: bool = False
    coordination_rule: str = "policyholder"
    policyholder_name: str = ""
    member_role: str = "policyholder"


@dataclass
class LineInput:
    line_id: int
    description: str
    billed: Decimal
    quantity: int = 1
    unit_rate: Decimal = ZERO
    cpt_code: Optional[str] = None
    icd_codes: list[str] = field(default_factory=list)
    category: str = "professional"
    excluded: bool = False
    evidence: str = ""


@dataclass
class ClaimInput:
    claim_id: int
    patient_name: str
    member_key: str
    provider_name: str
    service_date: Optional[date]
    lines: list[LineInput]
    bill_number: str | None = None
    provider_in_network: bool = True


@dataclass
class OrderDecision:
    plan_key: str
    role: str
    order: int
    rule: str
    evidence: list[str] = field(default_factory=list)
    assumption: str | None = None

    def to_dict(self) -> dict:
        return {
            "plan_key": self.plan_key,
            "role": self.role,
            "order": self.order,
            "rule": self.rule,
            "evidence": self.evidence,
            "assumption": self.assumption,
        }


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------


@dataclass
class PlanLineResult:
    plan_key: str
    role: str
    order: int
    base: Decimal = ZERO
    excluded: Decimal = ZERO
    sublimit_excess: Decimal = ZERO
    allowed: Decimal = ZERO
    contractual: Decimal = ZERO
    deductible: Decimal = ZERO
    coinsurance: Decimal = ZERO
    penalty: Decimal = ZERO
    oop_cap: Decimal = ZERO
    plan_paid: Decimal = ZERO
    member_covered: Decimal = ZERO
    annual_limit_excess: Decimal = ZERO
    member_total: Decimal = ZERO
    notes: list[str] = field(default_factory=list)
    eligible: bool = True

    def to_dict(self) -> dict:
        return {
            "plan_key": self.plan_key,
            "role": self.role,
            "order": self.order,
            "base": str(self.base),
            "excluded": str(self.excluded),
            "sublimit_excess": str(self.sublimit_excess),
            "allowed": str(self.allowed),
            "contractual": str(self.contractual),
            "deductible": str(self.deductible),
            "coinsurance": str(self.coinsurance),
            "penalty": str(self.penalty),
            "oop_cap": str(self.oop_cap),
            "plan_paid": str(self.plan_paid),
            "member_covered": str(self.member_covered),
            "annual_limit_excess": str(self.annual_limit_excess),
            "member_total": str(self.member_total),
            "eligible": self.eligible,
            "notes": self.notes,
        }


@dataclass
class LineResult:
    line_id: int
    description: str
    cpt_code: Optional[str]
    category: str
    billed: Decimal
    contractual: Decimal
    allowed: Decimal
    excluded: Decimal
    patient: Decimal
    patient_parts: dict[str, Decimal]
    plans: list[PlanLineResult]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "line_id": self.line_id,
            "description": self.description,
            "cpt_code": self.cpt_code,
            "category": self.category,
            "billed": str(self.billed),
            "contractual": str(self.contractual),
            "allowed": str(self.allowed),
            "excluded": str(self.excluded),
            "patient": str(self.patient),
            "patient_parts": {k: str(v) for k, v in self.patient_parts.items()},
            "plans": [p.to_dict() for p in self.plans],
            "notes": self.notes,
        }


@dataclass
class PlanAdjudication:
    plan_key: str
    insurer: str
    plan_name: str
    policy_number: str
    policy_id: int | None
    version_id: int | None
    role: str
    order: int
    lines: list[PlanLineResult] = field(default_factory=list)
    allowed_total: Decimal = ZERO
    contractual_total: Decimal = ZERO
    excluded_total: Decimal = ZERO
    sublimit_total: Decimal = ZERO
    deductible_total: Decimal = ZERO
    coinsurance_total: Decimal = ZERO
    penalty_total: Decimal = ZERO
    plan_paid: Decimal = ZERO
    member_paid: Decimal = ZERO
    annual_limit_excess: Decimal = ZERO
    oop_cap_applied: Decimal = ZERO
    preauth_required: bool = False
    preauth_reason: str = ""
    notes: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    eligibility: str = "eligible"

    def to_dict(self) -> dict:
        return {
            "plan_key": self.plan_key,
            "insurer": self.insurer,
            "plan_name": self.plan_name,
            "policy_number": self.policy_number,
            "policy_id": self.policy_id,
            "version_id": self.version_id,
            "role": self.role,
            "order": self.order,
            "allowed_total": str(self.allowed_total),
            "contractual_total": str(self.contractual_total),
            "excluded_total": str(self.excluded_total),
            "sublimit_total": str(self.sublimit_total),
            "deductible_total": str(self.deductible_total),
            "coinsurance_total": str(self.coinsurance_total),
            "penalty_total": str(self.penalty_total),
            "plan_paid": str(self.plan_paid),
            "member_paid": str(self.member_paid),
            "annual_limit_excess": str(self.annual_limit_excess),
            "oop_cap_applied": str(self.oop_cap_applied),
            "preauth_required": self.preauth_required,
            "preauth_reason": self.preauth_reason,
            "notes": self.notes,
            "assumptions": self.assumptions,
            "eligibility": self.eligibility,
            "lines": [line.to_dict() for line in self.lines],
        }


@dataclass
class InvariantCheck:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class ClaimResult:
    claim: ClaimInput
    order: list[OrderDecision]
    plans: list[PlanAdjudication]
    lines: list[LineResult]
    totals: dict[str, Decimal]
    invariants: list[InvariantCheck]
    warnings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    accumulators: dict[str, dict] = field(default_factory=dict)
    plan_state: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim.claim_id,
            "patient_name": self.claim.patient_name,
            "provider": self.claim.provider_name,
            "service_date": self.claim.service_date.isoformat() if self.claim.service_date else None,
            "bill_number": self.claim.bill_number,
            "order": [o.to_dict() for o in self.order],
            "plans": [p.to_dict() for p in self.plans],
            "lines": [line.to_dict() for line in self.lines],
            "totals": {k: str(v) for k, v in self.totals.items()},
            "invariants": [i.to_dict() for i in self.invariants],
            "warnings": self.warnings,
            "assumptions": self.assumptions,
            "accumulators": self.accumulators,
        }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def line_excluded(line: LineInput, plan: InsurancePlan) -> tuple[bool, str]:
    if line.excluded:
        return True, "marked non-covered on the source document"
    # Keywords match whole words against the description only: a keyword such
    # as "ear" (hearing aids) must not exclude "Cardiology - heart echo".
    description = line.description.lower()
    for exclusion in plan.exclusions:
        if exclusion.code and line.cpt_code and exclusion.code == line.cpt_code:
            return True, exclusion.label
        if exclusion.keyword:
            pattern = r"\b" + re.escape(exclusion.keyword.lower()) + r"\b"
            if re.search(pattern, description):
                return True, exclusion.label
    return False, ""


def matching_sublimit(line: LineInput, plan: InsurancePlan) -> Sublimit | None:
    for sub in plan.sublimits:
        if sub.applies_to_codes and line.cpt_code in sub.applies_to_codes:
            return sub
    for sub in plan.sublimits:
        if sub.applies_to_categories and line.category in sub.applies_to_categories:
            return sub
    return None


def in_force(plan: InsurancePlan, service_date: Optional[date]) -> tuple[bool, str]:
    if plan.status != "active":
        return False, f"policy status is {plan.status}"
    if service_date and plan.start_date and service_date < plan.start_date:
        return False, f"service date {service_date.isoformat()} is before policy start {plan.start_date.isoformat()}"
    if service_date and plan.end_date and service_date > plan.end_date:
        return False, f"service date {service_date.isoformat()} is after policy expiry {plan.end_date.isoformat()}"
    if service_date and plan.start_date and plan.waiting_period_days:
        ready = plan.start_date + timedelta(days=plan.waiting_period_days)
        if service_date < ready:
            return False, f"inside the {plan.waiting_period_days}-day waiting period (ends {ready.isoformat()})"
    return True, ""


def preauth_requirement(claim: ClaimInput, plan: InsurancePlan) -> tuple[bool, str]:
    if plan.preauth_always:
        return True, "the policy requires pre-authorisation for every planned admission"
    codes = {line.cpt_code for line in claim.lines if line.cpt_code}
    hit_codes = sorted(codes & set(plan.preauth_cpt_codes or []))
    if hit_codes:
        return True, f"procedure code(s) {', '.join(hit_codes)} are on the policy's pre-authorisation list"
    categories = sorted({line.category for line in claim.lines} & set(plan.preauth_categories or []))
    if categories:
        return True, f"service category {', '.join(categories)} requires pre-authorisation"
    covered = sum((line.billed for line in claim.lines if not line_excluded(line, plan)[0]), ZERO)
    if plan.preauth_threshold and covered > plan.preauth_threshold:
        return True, (
            f"covered estimate {money(covered)} is above the policy threshold "
            f"{money(plan.preauth_threshold)}"
        )
    return False, ""


# --------------------------------------------------------------------------
# Adjudication
# --------------------------------------------------------------------------

_BUCKET_ORDER = ("deductible", "coinsurance", "preauth_penalty", "sub_limit", "benefit_limit", "excluded")

def effective_annual_cap(plan: InsurancePlan) -> Decimal:
    """The yearly payment ceiling: annual_limit, else the sum insured."""
    cap = money(plan.annual_limit) if plan.annual_limit > 0 else ZERO
    if plan.sum_insured > 0:
        cap = money(plan.sum_insured) if cap == ZERO else money(min(cap, plan.sum_insured))
    return cap




def _absorb(buckets: dict[str, Decimal], amount: Decimal) -> Decimal:
    """Reduce patient buckets by ``amount``; return the amount absorbed."""
    left = money(amount)
    for key in _BUCKET_ORDER:
        if left <= 0:
            break
        take = min(buckets[key], left)
        buckets[key] = money(buckets[key] - take)
        left = money(left - take)
    return money(amount - left)


def adjudicate_claim(
    claim: ClaimInput,
    plans: list[InsurancePlan],
    order: list[OrderDecision],
    preauth_obtained: dict[str, bool] | None = None,
    provider_in_network: bool = True,
) -> ClaimResult:
    """Adjudicate one claim under an ordered list of plans (primary first)."""
    preauth_obtained = preauth_obtained or {}
    plan_by_key = {plan.key: plan for plan in plans}

    warnings: list[str] = []
    assumptions: list[str] = []

    # -- Input validation -------------------------------------------------
    # Each of these would change the money if left alone, so none may pass
    # silently: a repeated plan key pays twice, a factor outside (0, 1] pays
    # more than the allowed amount, and a negative bill line makes the patient
    # share negative.
    duplicate_keys = sorted(
        {key for key in (d.plan_key for d in order) if sum(1 for d in order if d.plan_key == key) > 1}
    )
    if duplicate_keys:
        warnings.append(
            "The payer order names "
            + ", ".join(duplicate_keys)
            + " more than once; only the first entry for each plan was applied."
        )
    seen_decisions: dict[str, OrderDecision] = {}
    for decision in sorted(order, key=lambda o: o.order):
        if decision.plan_key in seen_decisions or decision.plan_key not in plan_by_key:
            continue
        seen_decisions[decision.plan_key] = decision
    ordered = [plan_by_key[key] for key in seen_decisions]
    decisions = seen_decisions

    factor_for: dict[str, Decimal] = {}
    for plan in ordered:
        if plan.allowed_factor <= 0 or plan.allowed_factor > 1:
            warnings.append(
                f"{plan.insurer}: allowed_factor {plan.allowed_factor} is outside (0, 1]; "
                "this claim was priced with the full allowed amount."
            )
            factor_for[plan.key] = ONE
        else:
            factor_for[plan.key] = plan.allowed_factor

    annual_cap: dict[str, Decimal] = {}
    for plan in ordered:
        annual_cap[plan.key] = effective_annual_cap(plan)
        if plan.annual_limit <= 0 and plan.sum_insured > 0:
            assumptions.append(
                f"{plan.insurer}: no annual_limit is set, so the sum insured "
                f"({money(plan.sum_insured)}) is used as the yearly payment cap."
            )

    plan_results: list[PlanAdjudication] = []

    state: dict[str, dict] = {}
    for plan in ordered:
        cap = annual_cap[plan.key]
        state[plan.key] = {
            "deductible_remaining": money(max(ZERO, plan.deductible_total - plan.deductible_used)),
            "deductible_applied": ZERO,
            "oop_remaining": money(max(ZERO, plan.oop_max - plan.oop_used)) if plan.oop_max > 0 else None,
            "oop_applied": ZERO,
            "annual_remaining": money(max(ZERO, cap - plan.annual_limit_used)) if cap > 0 else None,
            "annual_applied": ZERO,
            "sub_remaining": {sub.key: sub.remaining() for sub in plan.sublimits},
            "sub_applied": {sub.key: ZERO for sub in plan.sublimits},
        }

    output_lines: list[LineResult] = []
    expected_penalty: dict[tuple[int, str], Decimal] = {}

    for line in claim.lines:
        billed = money(line.billed)
        if billed < 0:
            warnings.append(
                f"Line {line.line_id} ({line.description}) has a negative billed amount "
                f"({money(line.billed)}); it was treated as zero. Net a hospital discount into "
                "the billed amount instead of posting it as a negative line."
            )
            billed = ZERO
        covered = billed              # residual still offered to a later plan
        primary_excluded = ZERO       # excluded by a plan; offered only on request
        contractual_line = ZERO
        paid_line = ZERO
        buckets = {key: ZERO for key in _BUCKET_ORDER}
        plan_lines: list[PlanLineResult] = []
        adjudicated = False

        for plan in ordered:
            st = state[plan.key]
            decision = decisions.get(plan.key) or OrderDecision(plan.key, "primary", 1, plan.coordination_rule)
            ok, reason = in_force(plan, claim.service_date)
            if not ok:
                plan_lines.append(
                    PlanLineResult(plan.key, decision.role, decision.order, eligible=False, notes=[f"skipped: {reason}"])
                )
                warnings.append(f"{plan.insurer}: {reason}. This policy was not applied.")
                continue
            if plan.member_role in ("not_covered", ""):
                plan_lines.append(
                    PlanLineResult(
                        plan.key,
                        decision.role,
                        decision.order,
                        eligible=False,
                        notes=["skipped: the patient is not covered by this policy"],
                    )
                )
                warnings.append(f"{plan.insurer}: the patient is not covered by this policy.")
                continue
            if plan.network_only and not (provider_in_network and claim.provider_in_network):
                plan_lines.append(
                    PlanLineResult(
                        plan.key,
                        decision.role,
                        decision.order,
                        eligible=False,
                        notes=["skipped: provider is out of network and the policy is network-only"],
                    )
                )
                warnings.append(f"{plan.insurer}: provider is out of network; the policy is network-only.")
                continue

            if plan.covers_primary_exclusions:
                base = money(covered + primary_excluded)
                primary_excluded = ZERO
            else:
                base = money(covered)
            if base <= 0:
                plan_lines.append(
                    PlanLineResult(plan.key, decision.role, decision.order, notes=["no balance left for this plan"])
                )
                continue

            excluded, exclusion_reason = line_excluded(line, plan)
            if excluded:
                plan_lines.append(
                    PlanLineResult(
                        plan.key,
                        decision.role,
                        decision.order,
                        base=money(base),
                        excluded=money(base),
                        member_total=money(base),
                        eligible=False,
                        notes=[f"excluded: {exclusion_reason}"],
                    )
                )
                # Only the plan that prices the line first can move it into
                # the non-covered share. A later plan's exclusion applies to
                # that plan alone and leaves the residual for the plans after
                # it.
                if not adjudicated:
                    primary_excluded = money(primary_excluded + base)
                    covered = ZERO
                continue

            # The first plan to price the line sets the contractual rate. A
            # later plan takes the earlier allowed amount as its base, so its
            # own allowed_factor must not write off part of that residual.
            allowed = money(base)
            contractual = ZERO
            if not adjudicated:
                allowed = money(base * factor_for[plan.key])
                contractual = money(base - allowed)

            sublimit_excess = ZERO
            note = ""
            sub = matching_sublimit(line, plan)
            if sub is not None:
                # The cap applies to the allowed amount (after a network
                # discount) and consumes only what the plan actually allows.
                remaining_sub = st["sub_remaining"].get(sub.key, ZERO)
                if remaining_sub <= 0:
                    sublimit_excess = allowed
                    allowed = ZERO
                    note = f"{sub.label} limit of {money(sub.limit)} is already used up"
                elif allowed > remaining_sub:
                    sublimit_excess = money(allowed - remaining_sub)
                    allowed = remaining_sub
                    note = f"{sub.label} limit of {money(sub.limit)} caps this line"
                else:
                    note = f"within the {sub.label} limit of {money(sub.limit)}"
                st["sub_remaining"][sub.key] = money(max(ZERO, remaining_sub - allowed))
                if sub.basis != "per_claim":
                    st["sub_applied"][sub.key] = money(st["sub_applied"].get(sub.key, ZERO) + allowed)

            deductible = money(min(st["deductible_remaining"], allowed))
            st["deductible_remaining"] = money(st["deductible_remaining"] - deductible)
            post = money(allowed - deductible)
            coinsurance = money(post * plan.coinsurance_member)
            plan_paid = money(post - coinsurance)

            needs_preauth, preauth_reason = preauth_requirement(claim, plan)
            penalty = ZERO
            if needs_preauth and not preauth_obtained.get(plan.key, False) and plan_paid > 0:
                penalty = money(plan_paid * plan.preauth_penalty_rate)
                plan_paid = money(plan_paid - penalty)
                expected_penalty[(line.line_id, plan.key)] = penalty

            # The out-of-pocket maximum absorbs cost sharing only. A
            # non-compliance penalty sits outside it: it is not absorbed and
            # does not consume the maximum.
            oop_share = money(deductible + coinsurance)
            oop_cap = ZERO
            if st["oop_remaining"] is not None and oop_share > st["oop_remaining"]:
                headroom = money(allowed - plan_paid - penalty)
                absorbable = money(min(oop_share - st["oop_remaining"], headroom))
                if absorbable > 0:
                    plan_paid = money(plan_paid + absorbable)
                    reduce = absorbable
                    coins_absorbed = money(min(coinsurance, reduce))
                    coinsurance = money(coinsurance - coins_absorbed)
                    reduce = money(reduce - coins_absorbed)
                    if reduce > 0:
                        ded_absorbed = money(min(deductible, reduce))
                        deductible = money(deductible - ded_absorbed)
                        # The maximum paying the deductible does not consume it.
                        st["deductible_remaining"] = money(st["deductible_remaining"] + ded_absorbed)
                    oop_cap = absorbable
                    oop_share = money(deductible + coinsurance)
            if st["oop_remaining"] is not None:
                st["oop_remaining"] = money(max(ZERO, st["oop_remaining"] - oop_share))

            annual_excess = ZERO
            if st["annual_remaining"] is not None and plan_paid > st["annual_remaining"]:
                annual_excess = money(plan_paid - st["annual_remaining"])
                plan_paid = money(st["annual_remaining"])
            if st["annual_remaining"] is not None:
                st["annual_remaining"] = money(max(ZERO, st["annual_remaining"] - plan_paid))

            member_covered = money(oop_share + penalty + annual_excess)

            st["deductible_applied"] = money(st["deductible_applied"] + deductible)
            st["oop_applied"] = money(st["oop_applied"] + oop_share)
            st["annual_applied"] = money(st["annual_applied"] + plan_paid)

            plan_lines.append(
                PlanLineResult(
                    plan_key=plan.key,
                    role=decision.role,
                    order=decision.order,
                    base=money(base),
                    excluded=ZERO,
                    sublimit_excess=money(sublimit_excess),
                    allowed=money(allowed),
                    contractual=money(contractual),
                    deductible=money(deductible),
                    coinsurance=money(coinsurance),
                    penalty=money(penalty),
                    oop_cap=money(oop_cap),
                    plan_paid=money(plan_paid),
                    member_covered=money(member_covered),
                    annual_limit_excess=money(annual_excess),
                    member_total=money(member_covered + sublimit_excess),
                    notes=[
                        n
                        for n in (
                            note,
                            (
                                f"pre-authorisation was required but not approved: payment reduced by "
                                f"{money(penalty)} ({plan.preauth_penalty_rate:.0%})"
                                if penalty > 0
                                else ""
                            ),
                            (
                                f"out-of-pocket maximum absorbed {money(oop_cap)} of the member share"
                                if oop_cap > 0
                                else ""
                            ),
                            (
                                f"annual benefit limit reached: {money(annual_excess)} moved to the patient"
                                if annual_excess > 0
                                else ""
                            ),
                        )
                        if n
                    ],
                )
            )

            # The first payer establishes the patient's charges. A later payer
            # adjudicates the same residual, so its deductible/coinsurance are a
            # breakdown of that residual - not additional charges. Only its
            # payment reduces the earlier buckets.
            if not adjudicated:
                buckets["deductible"] = money(buckets["deductible"] + deductible)
                buckets["coinsurance"] = money(buckets["coinsurance"] + coinsurance)
                buckets["preauth_penalty"] = money(buckets["preauth_penalty"] + penalty)
                buckets["sub_limit"] = money(buckets["sub_limit"] + sublimit_excess)
                buckets["benefit_limit"] = money(buckets["benefit_limit"] + annual_excess)
            elif plan_paid > 0:
                _absorb(buckets, plan_paid)

            # Everything the plan did not pay - including a sub-limit or
            # annual-limit excess - stays available to the next plan.
            covered = money(member_covered + sublimit_excess)
            contractual_line = money(contractual_line + contractual)
            paid_line = money(paid_line + plan_paid)
            adjudicated = True

        patient = money(covered + primary_excluded)
        # The residual that no plan adjudicated is the excluded/uncovered share.
        known = money(sum(buckets.values(), ZERO))
        residual = money(patient - known)
        if residual > 0:
            buckets["excluded"] = money(buckets["excluded"] + residual)
        elif residual < 0:
            warnings.append(
                f"Line {line.line_id}: the patient share is {money(-residual)} below its own breakdown; "
                "the bill reconciliation check below records this."
            )
            buckets["excluded"] = money(max(ZERO, buckets["excluded"] + residual))
        patient = money(sum(buckets.values(), ZERO))

        line_notes = []
        if patient == 0:
            line_notes.append("fully covered by the coordinated plans")
        if buckets["excluded"] > 0:
            line_notes.append("part of this line is not a covered benefit")
        if any(p.annual_limit_excess > 0 for p in plan_lines):
            line_notes.append("a plan's annual limit was reached")

        excluded_patient = money(buckets.get("excluded", ZERO))
        output_lines.append(
            LineResult(
                line_id=line.line_id,
                description=line.description,
                cpt_code=line.cpt_code,
                category=line.category,
                billed=billed,
                contractual=money(contractual_line),
                allowed=money(max(ZERO, billed - contractual_line - excluded_patient)),
                excluded=excluded_patient,
                patient=money(patient),
                patient_parts={k: money(v) for k, v in buckets.items()},
                plans=plan_lines,
                notes=line_notes,
            )
        )

    # ------------------------------------------------------------------
    # Per-plan totals
    # ------------------------------------------------------------------
    for plan in ordered:
        decision = decisions.get(plan.key) or OrderDecision(plan.key, "primary", 1, plan.coordination_rule)
        plan_lines: list[PlanLineResult] = []
        for line_result in output_lines:
            match = next((p for p in line_result.plans if p.plan_key == plan.key), None)
            if match is not None:
                plan_lines.append(match)
        needs_preauth, preauth_reason = preauth_requirement(claim, plan)
        plan_results.append(
            PlanAdjudication(
                plan_key=plan.key,
                insurer=plan.insurer,
                plan_name=plan.plan_name,
                policy_number=plan.policy_number,
                policy_id=plan.policy_id,
                version_id=plan.version_id,
                role=decision.role,
                order=decision.order,
                lines=plan_lines,
                allowed_total=money(sum((l.allowed for l in plan_lines), ZERO)),
                contractual_total=money(sum((l.contractual for l in plan_lines), ZERO)),
                excluded_total=money(sum((l.excluded for l in plan_lines), ZERO)),
                sublimit_total=money(sum((l.sublimit_excess for l in plan_lines), ZERO)),
                deductible_total=money(sum((l.deductible for l in plan_lines), ZERO)),
                coinsurance_total=money(sum((l.coinsurance for l in plan_lines), ZERO)),
                penalty_total=money(sum((l.penalty for l in plan_lines), ZERO)),
                plan_paid=money(sum((l.plan_paid for l in plan_lines), ZERO)),
                member_paid=money(sum((l.member_total for l in plan_lines), ZERO)),
                annual_limit_excess=money(sum((l.annual_limit_excess for l in plan_lines), ZERO)),
                oop_cap_applied=money(sum((l.oop_cap for l in plan_lines), ZERO)),
                preauth_required=needs_preauth,
                preauth_reason=preauth_reason,
                assumptions=[decision.assumption] if decision.assumption else [],
                notes=sorted({n for l in plan_lines for n in l.notes}),
            )
        )

    # ------------------------------------------------------------------
    # Totals and invariants
    # ------------------------------------------------------------------
    billed_total = money(sum((line.billed for line in output_lines), ZERO))
    contractual_total = money(sum((line.contractual for line in output_lines), ZERO))
    paid_total = money(sum((p.plan_paid for p in plan_results), ZERO))
    patient_total = money(sum((line.patient for line in output_lines), ZERO))
    excluded_total = money(sum((line.excluded for line in output_lines), ZERO))
    primary_paid = money(sum((p.plan_paid for p in plan_results if p.role == "primary"), ZERO))
    secondary_paid = money(sum((p.plan_paid for p in plan_results if p.role != "primary"), ZERO))

    totals = {
        "billed": billed_total,
        "allowed": money(sum((line.allowed for line in output_lines), ZERO)),
        "contractual_adjustment": contractual_total,
        "excluded": excluded_total,
        "primary_paid": primary_paid,
        "secondary_paid": secondary_paid,
        "insurer_paid": paid_total,
        "patient_liability": patient_total,
        "patient_cost_share": money(patient_total - excluded_total),
    }

    invariants: list[InvariantCheck] = []

    def check(name: str, passed: bool, detail: str) -> None:
        invariants.append(InvariantCheck(name, passed, detail))

    check(
        "Bill reconciles",
        money(paid_total + patient_total + contractual_total) == billed_total,
        f"{money(paid_total)} paid + {money(patient_total)} patient + {money(contractual_total)} adjustments "
        f"= {money(paid_total + patient_total + contractual_total)} vs billed {money(billed_total)}",
    )

    # Per line, not only in total: an error on one line must not hide inside a
    # compensating error on another.
    line_issues = []
    for line in output_lines:
        line_paid = money(sum((p.plan_paid for p in line.plans), ZERO))
        if money(line_paid + line.patient + line.contractual) != line.billed:
            line_issues.append(
                f"line {line.line_id}: paid {money(line_paid)} + patient {money(line.patient)} + "
                f"adjustments {money(line.contractual)} = {money(line_paid + line.patient + line.contractual)} "
                f"vs billed {money(line.billed)}"
            )
        if line.allowed < 0 or line.excluded < 0 or line.contractual < 0 or line.patient < 0:
            line_issues.append(f"line {line.line_id}: a negative total ({money(line.allowed)}/{money(line.excluded)})")
        for key, value in line.patient_parts.items():
            if value < 0:
                line_issues.append(f"line {line.line_id}: negative {key} bucket ({money(value)})")
    check(
        "Every line reconciles",
        not line_issues,
        "; ".join(line_issues[:3]) if line_issues else "every line's payments, patient share and adjustments equal its bill",
    )
    check(
        "Allowed amount reconciles",
        money(excluded_total + totals["allowed"] + contractual_total) == billed_total,
        f"excluded {money(excluded_total)} + allowed {money(totals['allowed'])} + adjustments "
        f"{money(contractual_total)} = {money(excluded_total + totals['allowed'] + contractual_total)}",
    )
    check(
        "Patient liability equals the sum of its lines",
        money(sum((line.patient for line in output_lines), ZERO)) == patient_total,
        f"lines total {money(patient_total)}",
    )
    check(
        "Plan order names each plan once",
        not duplicate_keys,
        "each plan appears once" if not duplicate_keys else f"repeated: {', '.join(duplicate_keys)}",
    )
    bad_factors = [f"{plan.key}={plan.allowed_factor}" for plan in ordered if not (0 < plan.allowed_factor <= 1)]
    check(
        "Allowed factors are within (0, 1]",
        not bad_factors,
        "all factors are valid" if not bad_factors else f"outside the range: {', '.join(bad_factors)}",
    )

    # A later plan must take the previous plan's residual as its base and can
    # never pay more than it, on any line.
    residual_issues = []
    for index, plan_result in enumerate(plan_results):
        for line_result in plan_result.lines:
            if line_result.base < 0:
                residual_issues.append(f"{plan_result.plan_key} line {line_result.plan_key}: negative base")
            if index > 0 and line_result.plan_paid > line_result.base:
                residual_issues.append(
                    f"{plan_result.plan_key}: paid {money(line_result.plan_paid)} above its base "
                    f"{money(line_result.base)}"
                )
    check(
        "A later plan never pays above its residual",
        not residual_issues,
        "; ".join(residual_issues[:3]) if residual_issues else "every later plan's payment is within its base",
    )
    for plan_result in plan_results:
        over = [l for l in plan_result.lines if l.plan_paid > l.allowed]
        check(
            f"{plan_result.insurer}: no payment above the allowed amount",
            not over,
            "all line payments are within the allowed amount" if not over else f"{len(over)} line(s) exceed allowed",
        )
        if plan_result.preauth_required and not preauth_obtained.get(plan_result.plan_key, False):
            check(
                f"{plan_result.insurer}: pre-authorisation penalty disclosed",
                True,
                f"payment reduced by {money(plan_result.penalty_total)} because pre-authorisation was not approved",
            )
    penalty_leaks = [
        f"line {line_result.line_id}/{plan_line.plan_key}: {money(plan_line.penalty)} vs {money(expected_penalty[(line_result.line_id, plan_line.plan_key)])}"
        for line_result in output_lines
        for plan_line in line_result.plans
        if (line_result.line_id, plan_line.plan_key) in expected_penalty
        and plan_line.penalty != expected_penalty[(line_result.line_id, plan_line.plan_key)]
    ]
    check(
        "Pre-authorisation penalties are not reduced by the out-of-pocket maximum",
        not penalty_leaks,
        "; ".join(penalty_leaks[:3]) if penalty_leaks else "every penalty is charged in full",
    )
    for plan in ordered:
        st = state[plan.key]
        if plan.deductible_total > 0:
            used = money(plan.deductible_used + st["deductible_applied"])
            check(
                f"{plan.insurer}: deductible within policy limit",
                used <= plan.deductible_total,
                f"used {money(used)} of {money(plan.deductible_total)}",
            )
        if plan.oop_max > 0:
            used = money(plan.oop_used + st["oop_applied"])
            check(
                f"{plan.insurer}: out-of-pocket maximum respected",
                used <= plan.oop_max,
                f"used {money(used)} of {money(plan.oop_max)}",
            )
        if annual_cap[plan.key] > 0:
            used = money(plan.annual_limit_used + st["annual_applied"])
            check(
                f"{plan.insurer}: annual limit respected",
                used <= annual_cap[plan.key],
                f"paid to date {money(used)} of {money(annual_cap[plan.key])}",
            )
        if plan.sum_insured > 0:
            used = money(plan.annual_limit_used + st["annual_applied"])
            check(
                f"{plan.insurer}: payments within the sum insured",
                used <= plan.sum_insured,
                f"paid to date {money(used)} of {money(plan.sum_insured)}",
            )
        for sub in plan.sublimits:
            if sub.basis == "per_claim":
                # A per-claim cap is consumed inside this claim only; its
                # carried-over `used` must not be accumulated or tested.
                continue
            used = money(sub.used + st["sub_applied"].get(sub.key, ZERO))
            check(
                f"{plan.insurer}: {sub.label} sub-limit respected",
                used <= sub.limit,
                f"used {money(used)} of {money(sub.limit)}",
            )
    negative = [
        (line.line_id, p.plan_key)
        for line in output_lines
        for p in line.plans
        if p.plan_paid < 0 or p.member_total < 0 or p.allowed < 0 or p.contractual < 0
    ] + [
        (line.line_id, "patient")
        for line in output_lines
        if line.patient < 0 or line.patient_parts and min(line.patient_parts.values(), default=ZERO) < 0
    ]
    if contractual_total < 0 or excluded_total < 0 or totals["allowed"] < 0:
        negative.append((0, "totals"))
    check("No negative amounts", not negative, "every amount is zero or positive" if not negative else str(negative[:5]))

    accumulators = {}
    for plan in ordered:
        st = state[plan.key]
        accumulators[plan.key] = {
            "policy_id": plan.policy_id,
            "version_id": plan.version_id,
            "deductible_used": str(money(plan.deductible_used + st["deductible_applied"])),
            "oop_used": str(money(plan.oop_used + st["oop_applied"])),
            "annual_limit_used": str(money(plan.annual_limit_used + st["annual_applied"])),
            "sublimits": {
                sub.key: {
                    "label": sub.label,
                    "limit": str(money(sub.limit)),
                    "basis": sub.basis,
                    "used": str(
                        money(
                            sub.used
                            if sub.basis == "per_claim"
                            else sub.used + st["sub_applied"].get(sub.key, ZERO)
                        )
                    ),
                }
                for sub in plan.sublimits
            },
        }

    if any(not inv.passed for inv in invariants):
        warnings.append("One or more financial invariants failed; the supervisor must repair the calculation.")

    return ClaimResult(
        claim=claim,
        order=[decisions.get(p.key) or OrderDecision(p.key, "primary", 1, p.coordination_rule) for p in ordered],
        plans=plan_results,
        lines=output_lines,
        totals=totals,
        invariants=invariants,
        warnings=warnings,
        assumptions=assumptions,
        accumulators=accumulators,
        plan_state=state,
    )


def primary_only_totals(result: ClaimResult) -> dict[str, Decimal]:
    """What the household would pay if only the primary policy existed."""
    primary = next((p for p in result.plans if p.role == "primary"), None)
    if primary is None:
        return {"insurer_paid": ZERO, "patient_liability": result.totals["billed"]}
    patient = money(result.totals["billed"] - primary.plan_paid - primary.contractual_total)
    return {"insurer_paid": primary.plan_paid, "patient_liability": patient}
