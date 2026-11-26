"""Coordination-of-benefits (COB) adjudication engine.

The engine is deliberately separate from the agent: it is deterministic, has
no side effects and is the unit the tests exercise. The agent decides *which*
plans apply, in which order, and whether pre-authorisation was obtained; the
engine turns those decisions into rupee amounts.

Rules implemented (documented in ``docs/COB_RULES.md``):
* each member's own employer plan is primary, the spouse's plan is secondary;
* the deductible is applied to the allowed amount before coinsurance;
* the secondary plan only considers what the primary plan left unpaid;
* the member out-of-pocket maximum caps the member's share per plan per year;
* procedures above the pre-authorisation threshold (or surgical codes) need
  pre-auth, and skipping it cuts the plan's payment by the penalty rate;
* excluded items (equipment) are never paid by either plan.
"""

from __future__ import annotations

from decimal import Decimal

from ..config import ACCUMULATORS, PLANS
from ..models import (
    Adjudication,
    Claim,
    ClaimOutcome,
    LineAdjudication,
    LineCategory,
    MemberAccumulator,
    Money,
    PlanTerms,
    ZERO,
    money,
)

SURGERY_CODES = {"29888", "29881", "29870"}


def preauth_required(claim: Claim, plan: PlanTerms) -> bool:
    """True when the plan needs pre-authorisation before the service."""
    covered_total = sum(
        (line.billed_amount for line in claim.lines if _covered(line, plan)), ZERO
    )
    surgical = any((line.cpt_code in SURGERY_CODES) for line in claim.lines)
    return bool(surgical or money(covered_total) > plan.preauth_threshold)


def _covered(line, plan: PlanTerms) -> bool:
    if line.non_covered:
        return False
    if line.category == LineCategory.EQUIPMENT and not plan.equipment_covered:
        return False
    return True


def _therapy_allowed(line, plan: PlanTerms) -> Money:
    """Apply the plan's annual therapy session limit to a therapy line."""
    if line.category != LineCategory.THERAPY or not line.quantity or not line.unit_rate:
        return line.billed_amount
    allowed_sessions = min(line.quantity, plan.therapy_session_limit)
    return money(line.unit_rate * allowed_sessions)


def adjudicate(
    claim: Claim,
    plan: PlanTerms,
    accumulator: MemberAccumulator,
    preauth_obtained: bool = True,
    role: str = "primary",
    primary: Adjudication | None = None,
) -> tuple[Adjudication, MemberAccumulator]:
    """Adjudicate one claim under one plan, as primary or secondary.

    Returns the adjudication plus the updated member accumulator.
    """
    if role == "secondary" and primary is None:
        raise ValueError("secondary adjudication needs the primary result")

    deductible_remaining = money(plan.deductible_per_member - accumulator.deductible_used)
    oop_remaining = money(plan.oop_max_per_member - accumulator.oop_used)

    needs_preauth = preauth_required(claim, plan)
    penalty_applies = needs_preauth and not preauth_obtained

    line_results: list[LineAdjudication] = []
    total_allowed = ZERO
    total_non_covered = ZERO
    total_deductible = ZERO
    total_coinsurance = ZERO
    total_paid = ZERO
    total_member = ZERO
    total_penalty = ZERO
    oop_cap_applied = ZERO

    for index, line in enumerate(claim.lines):
        covered = _covered(line, plan)
        billed = money(line.billed_amount)
        allowed = _therapy_allowed(line, plan) if covered else ZERO
        non_covered = ZERO if covered else billed

        if role == "secondary":
            # The secondary plan only looks at what the primary left unpaid on
            # the covered part of the line.
            covered_member_after_primary = primary.lines[index].member_paid_covered  # type: ignore[index]
            allowed = min(allowed, money(covered_member_after_primary))

        deductible = money(min(deductible_remaining, allowed)) if allowed > 0 else ZERO
        deductible_remaining = money(deductible_remaining - deductible)
        post_deductible = money(allowed - deductible)
        coinsurance_member = money(post_deductible * plan.coinsurance_member)
        plan_paid = money(post_deductible - coinsurance_member)

        penalty = ZERO
        if penalty_applies and plan_paid > 0:
            penalty = money(plan_paid * plan.preauth_penalty_rate)
            plan_paid = money(plan_paid - penalty)

        member_paid_covered = money(deductible + coinsurance_member + penalty)
        member_paid = money(member_paid_covered + non_covered)

        total_allowed += allowed
        total_non_covered += non_covered
        total_deductible += deductible
        total_coinsurance += coinsurance_member
        total_penalty += penalty
        total_paid += plan_paid
        total_member += member_paid

        line_results.append(
            LineAdjudication(
                line_description=line.description,
                cpt_code=line.cpt_code,
                billed=billed,
                allowed=money(allowed),
                non_covered=money(non_covered),
                deductible_applied=deductible,
                coinsurance_member=coinsurance_member,
                plan_paid=plan_paid,
                member_paid=member_paid,
                preauth_penalty=penalty,
                notes=[],
            )
        )

    # Member out-of-pocket maximum: the plan absorbs anything above the cap.
    member_covered_total = money(total_deductible + total_coinsurance + total_penalty)
    if member_covered_total > oop_remaining:
        excess = money(member_covered_total - oop_remaining)
        remaining_excess = excess
        for result in line_results:
            if remaining_excess <= 0:
                break
            for attribute in ("coinsurance_member", "preauth_penalty", "deductible_applied"):
                if remaining_excess <= 0:
                    break
                value = getattr(result, attribute)
                take = money(min(value, remaining_excess))
                if take <= 0:
                    continue
                setattr(result, attribute, money(value - take))
                result.plan_paid = money(result.plan_paid + take)
                result.member_paid = money(result.member_paid - take)
                result.notes.append("out-of-pocket maximum absorbed part of the member share")
                remaining_excess = money(remaining_excess - take)
        oop_cap_applied = money(excess - remaining_excess)

    # Totals are derived from the adjusted line results so they always agree.
    total_allowed = money(sum((line.allowed for line in line_results), ZERO))
    total_non_covered = money(sum((line.non_covered for line in line_results), ZERO))
    total_deductible = money(sum((line.deductible_applied for line in line_results), ZERO))
    total_coinsurance = money(sum((line.coinsurance_member for line in line_results), ZERO))
    total_penalty = money(sum((line.preauth_penalty for line in line_results), ZERO))
    total_paid = money(sum((line.plan_paid for line in line_results), ZERO))
    total_member = money(sum((line.member_paid for line in line_results), ZERO))

    # Recompute the per-line covered member share after the OOP cap so a
    # secondary plan reads the correct residual.
    for result in line_results:
        result.member_paid_covered = money(result.member_paid - result.non_covered)

    adjudication = Adjudication(
        claim_id=claim.claim_id,
        plan_id=plan.plan_id,
        role=role,
        lines=line_results,
        allowed_total=money(total_allowed),
        non_covered_total=money(total_non_covered),
        deductible_applied=money(total_deductible),
        coinsurance_member=money(total_coinsurance),
        plan_paid=money(total_paid),
        member_paid=money(total_member),
        preauth_penalty=money(total_penalty),
        oop_cap_applied=money(oop_cap_applied),
        notes=(
            [f"pre-authorisation was required but not obtained: plan payment reduced by {plan.preauth_penalty_rate:.0%}"]
            if penalty_applies
            else []
        ),
    )

    updated = MemberAccumulator(
        member_id=accumulator.member_id,
        plan_id=accumulator.plan_id,
        deductible_used=money(accumulator.deductible_used + total_deductible),
        oop_used=money(accumulator.oop_used + (total_member - total_non_covered)),
    )
    return adjudication, updated


def coordinate(
    claim: Claim,
    primary_plan_id: str,
    secondary_plan_id: str,
    preauth_obtained: dict[str, bool] | None = None,
    accumulators: dict[tuple[str, str], MemberAccumulator] | None = None,
) -> ClaimOutcome:
    """Run the full primary-then-secondary adjudication for one claim."""
    accumulators = accumulators or ACCUMULATORS
    preauth_obtained = preauth_obtained or {}
    primary_plan = PLANS[primary_plan_id]
    secondary_plan = PLANS[secondary_plan_id]
    member_id = claim.member_id

    primary_accum = accumulators[(primary_plan_id, member_id)]
    secondary_accum = accumulators[(secondary_plan_id, member_id)]

    primary_result, primary_updated = adjudicate(
        claim, primary_plan, primary_accum,
        preauth_obtained=preauth_obtained.get(primary_plan_id, True), role="primary",
    )
    secondary_result, secondary_updated = adjudicate(
        claim, secondary_plan, secondary_accum,
        preauth_obtained=preauth_obtained.get(secondary_plan_id, True), role="secondary",
        primary=primary_result,
    )
    accumulators[(primary_plan_id, member_id)] = primary_updated
    accumulators[(secondary_plan_id, member_id)] = secondary_updated

    warnings: list[str] = []
    if primary_result.non_covered_total > 0:
        warnings.append(
            f"{money(primary_result.non_covered_total)} of the bill is excluded by both plans "
            "(home traction equipment is not a covered benefit)"
        )
    if secondary_result.member_paid > 0 and secondary_plan.plan_id not in preauth_obtained:
        warnings.append("secondary plan benefit assumed pre-authorised; letters are drafted for both insurers")

    outcome = ClaimOutcome(
        claim=claim,
        primary_plan=primary_plan_id,
        secondary_plan=secondary_plan_id,
        primary=primary_result,
        secondary=secondary_result,
        preauth_required={
            primary_plan_id: preauth_required(claim, primary_plan),
            secondary_plan_id: preauth_required(claim, secondary_plan),
        },
        preauth_obtained=preauth_obtained,
        warnings=warnings,
    )
    return outcome


def inventory_snapshot() -> dict:
    """Small helper used by the mock API to expose accumulator state."""
    return {f"{plan}:{member}": acc.to_dict() for (plan, member), acc in ACCUMULATORS.items()}


def with_preauth(outcome: ClaimOutcome, accumulators: dict | None = None) -> ClaimOutcome:
    """Return the same claim adjudicated as if every pre-auth had been filed."""
    return coordinate(
        outcome.claim,
        outcome.primary_plan,
        outcome.secondary_plan,
        preauth_obtained={outcome.primary_plan: True, outcome.secondary_plan: True},
        accumulators=dict(accumulators or ACCUMULATORS),
    )
