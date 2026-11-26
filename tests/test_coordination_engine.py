"""Tests for the dynamic coordination engine.

These exercise the arithmetic directly, without a database or HTTP layer, so a
failure points at the money rules rather than at plumbing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from duco_agent.engines.coordination import (
    ClaimInput,
    Exclusion,
    InsurancePlan,
    LineInput,
    OrderDecision,
    Sublimit,
    adjudicate_claim,
    money,
)


def plan_a(**overrides) -> InsurancePlan:
    values = dict(
        key="A",
        insurer="Acme Health",
        plan_name="Employer Plus",
        policy_number="POL-A",
        policy_id=1,
        version_id=11,
        deductible_total=Decimal("5000"),
        coinsurance_member=Decimal("0.20"),
        oop_max=Decimal("60000"),
        annual_limit=Decimal("500000"),
        preauth_threshold=Decimal("50000"),
        preauth_penalty_rate=Decimal("0.20"),
        preauth_cpt_codes=["29888"],
        start_date=date(2024, 1, 1),
        member_role="policyholder",
    )
    values.update(overrides)
    return InsurancePlan(**values)


def plan_b(**overrides) -> InsurancePlan:
    values = dict(
        key="B",
        insurer="Beta Assurance",
        plan_name="Family Shield",
        policy_number="POL-B",
        policy_id=2,
        version_id=21,
        deductible_total=Decimal("0"),
        coinsurance_member=Decimal("0.10"),
        oop_max=Decimal("80000"),
        annual_limit=Decimal("300000"),
        preauth_threshold=Decimal("50000"),
        preauth_penalty_rate=Decimal("0.25"),
        start_date=date(2024, 6, 1),
        member_role="dependent",
    )
    values.update(overrides)
    return InsurancePlan(**values)


def claim(lines, **overrides) -> ClaimInput:
    values = dict(
        claim_id=1,
        patient_name="Test Patient",
        member_key="M1",
        provider_name="City Hospital",
        service_date=date(2026, 5, 10),
        lines=lines,
        bill_number="B-1",
        provider_in_network=True,
    )
    values.update(overrides)
    return ClaimInput(**values)


def one_line(amount="100000", cpt="29888", category="professional", **kw) -> LineInput:
    return LineInput(
        line_id=1,
        description=kw.pop("description", "Surgical procedure"),
        billed=money(amount),
        quantity=1,
        unit_rate=money(amount),
        cpt_code=cpt,
        category=category,
        **kw,
    )


def order(*keys):
    return [OrderDecision(key, "primary" if i == 0 else "secondary", i + 1, "policyholder") for i, key in enumerate(keys)]


def test_primary_deductible_and_coinsurance():
    result = adjudicate_claim(claim([one_line()]), [plan_a()], order("A"), {"A": True})
    primary = result.plans[0]
    assert primary.deductible_total == Decimal("5000.00")
    assert primary.coinsurance_total == Decimal("19000.00")
    assert primary.plan_paid == Decimal("76000.00")
    assert result.totals["patient_liability"] == Decimal("24000.00")
    assert result.totals["insurer_paid"] == Decimal("76000.00")
    assert all(inv.passed for inv in result.invariants)


def test_secondary_applies_its_own_terms_to_the_residual_only():
    result = adjudicate_claim(
        claim([one_line()]), [plan_a(), plan_b()], order("A", "B"), {"A": True, "B": True}
    )
    secondary = result.plans[1]
    # Primary leaves 24,000. Secondary: no deductible, 10% coinsurance -> pays 21,600.
    assert secondary.lines[0].base == Decimal("24000.00")
    assert secondary.plan_paid == Decimal("21600.00")
    assert result.totals["patient_liability"] == Decimal("2400.00")
    assert result.totals["insurer_paid"] == Decimal("97600.00")
    assert all(inv.passed for inv in result.invariants)


def test_secondary_never_pays_more_than_primary_left():
    result = adjudicate_claim(
        claim([one_line("20000")]),
        [plan_a(deductible_total=Decimal("0"), coinsurance_member=Decimal("0.05")), plan_b(deductible_total=Decimal("0"), coinsurance_member=Decimal("0"))],
        order("A", "B"),
        {"A": True, "B": True},
    )
    # A pays 19,000 leaving 1,000; B's allowed factor is 1 so it cannot pay more
    # than the 1,000 residual even with zero cost sharing.
    assert result.plans[0].plan_paid == Decimal("19000.00")
    assert result.plans[1].plan_paid == Decimal("1000.00")
    assert result.totals["patient_liability"] == Decimal("0.00")
    assert all(inv.passed for inv in result.invariants)


def test_out_of_pocket_maximum_absorbs_member_share():
    result = adjudicate_claim(
        claim([one_line("100000")]),
        [plan_a(deductible_total=Decimal("0"), coinsurance_member=Decimal("0.50"), oop_max=Decimal("30000"))],
        order("A"),
        {"A": True},
    )
    primary = result.plans[0]
    assert primary.coinsurance_total == Decimal("30000.00")
    assert primary.plan_paid == Decimal("70000.00")
    assert result.totals["patient_liability"] == Decimal("30000.00")
    assert primary.oop_cap_applied == Decimal("20000.00")
    assert all(inv.passed for inv in result.invariants)


def test_annual_limit_caps_payment_and_moves_excess_to_patient():
    result = adjudicate_claim(
        claim([one_line("100000")]),
        [plan_a(deductible_total=Decimal("0"), coinsurance_member=Decimal("0"), annual_limit=Decimal("40000"))],
        order("A"),
        {"A": True},
    )
    primary = result.plans[0]
    assert primary.plan_paid == Decimal("40000.00")
    assert primary.annual_limit_excess == Decimal("60000.00")
    assert result.totals["patient_liability"] == Decimal("60000.00")
    assert all(inv.passed for inv in result.invariants)


def test_sub_limit_caps_the_eligible_amount():
    result = adjudicate_claim(
        claim([one_line("30000", cpt="97110", category="therapy")]),
        [
            plan_a(
                deductible_total=Decimal("0"),
                coinsurance_member=Decimal("0"),
                sublimits=[
                    Sublimit(
                        key="therapy",
                        label="Annual physiotherapy limit",
                        limit=Decimal("20000"),
                        applies_to_categories=["therapy"],
                    )
                ],
            )
        ],
        order("A"),
        {"A": True},
    )
    primary = result.plans[0]
    assert primary.sublimit_total == Decimal("10000.00")
    assert primary.plan_paid == Decimal("20000.00")
    assert result.totals["patient_liability"] == Decimal("10000.00")
    assert result.lines[0].patient_parts["sub_limit"] == Decimal("10000.00")
    assert all(inv.passed for inv in result.invariants)


def test_exclusion_is_not_paid_by_either_plan():
    result = adjudicate_claim(
        claim([one_line("15000", cpt="E0114", category="equipment")]),
        [
            plan_a(exclusions=[Exclusion(label="Durable equipment is excluded", code="E0114")]),
            plan_b(),
        ],
        order("A", "B"),
        {"A": True, "B": True},
    )
    assert result.plans[0].plan_paid == Decimal("0.00")
    assert result.plans[1].plan_paid == Decimal("0.00")
    assert result.totals["patient_liability"] == Decimal("15000.00")
    assert result.lines[0].excluded == Decimal("15000.00")
    assert all(inv.passed for inv in result.invariants)


def test_primary_exclusion_can_be_covered_when_policy_allows():
    result = adjudicate_claim(
        claim([one_line("15000", cpt="E0114", category="equipment")]),
        [
            plan_a(exclusions=[Exclusion(label="Durable equipment is excluded", code="E0114")]),
            plan_b(covers_primary_exclusions=True),
        ],
        order("A", "B"),
        {"A": True, "B": True},
    )
    assert result.plans[0].plan_paid == Decimal("0.00")
    assert result.plans[1].plan_paid == Decimal("13500.00")  # 15,000 less 10% coinsurance
    assert result.totals["patient_liability"] == Decimal("1500.00")
    assert all(inv.passed for inv in result.invariants)


def test_preauth_penalty_applies_when_not_approved():
    result = adjudicate_claim(
        claim([one_line("100000")]), [plan_a()], order("A"), {"A": False}
    )
    primary = result.plans[0]
    assert primary.preauth_required is True
    assert primary.penalty_total == Decimal("15200.00")  # 20% of 76,000
    assert result.totals["patient_liability"] == Decimal("39200.00")
    assert all(inv.passed for inv in result.invariants)
    assert any("pre-authorisation" in note for note in primary.notes)


def test_inactive_policy_is_skipped_and_explained():
    result = adjudicate_claim(
        claim([one_line("50000")]),
        [plan_a(status="inactive"), plan_b()],
        order("A", "B"),
        {"A": True, "B": True},
    )
    assert result.plans[0].plan_paid == Decimal("0.00")
    assert result.plans[1].plan_paid == Decimal("45000.00")
    assert any("inactive" in warning for warning in result.warnings)
    assert all(inv.passed for inv in result.invariants)


def test_waiting_period_blocks_cover():
    result = adjudicate_claim(
        claim([one_line("50000")], service_date=date(2024, 1, 10)),
        [plan_a(waiting_period_days=365)],
        order("A"),
        {"A": True},
    )
    assert result.plans[0].plan_paid == Decimal("0.00")
    assert result.totals["patient_liability"] == Decimal("50000.00")
    assert any("waiting period" in warning for warning in result.warnings)


def test_three_plans_coordinate_without_double_payment():
    third = InsurancePlan(
        key="C",
        insurer="Gamma General",
        plan_name="Top-up",
        policy_number="POL-C",
        deductible_total=Decimal("0"),
        coinsurance_member=Decimal("0"),
        annual_limit=Decimal("100000"),
    )
    result = adjudicate_claim(
        claim([one_line("100000")]),
        [plan_a(), plan_b(), third],
        order("A", "B", "C"),
        {"A": True, "B": True, "C": True},
    )
    total_paid = result.totals["insurer_paid"]
    assert total_paid <= Decimal("100000.00")
    assert total_paid + result.totals["patient_liability"] == Decimal("100000.00")
    assert all(inv.passed for inv in result.invariants)


def test_contractual_adjustment_reconciles():
    result = adjudicate_claim(
        claim([one_line("100000")]),
        [plan_a(allowed_factor=Decimal("0.90"), deductible_total=Decimal("0"), coinsurance_member=Decimal("0"))],
        order("A"),
        {"A": True},
    )
    assert result.totals["contractual_adjustment"] == Decimal("10000.00")
    assert result.totals["allowed"] == Decimal("90000.00")
    assert result.totals["insurer_paid"] == Decimal("90000.00")
    assert result.totals["patient_liability"] == Decimal("0.00")
    assert all(inv.passed for inv in result.invariants)


def test_accumulators_are_returned():
    result = adjudicate_claim(claim([one_line()]), [plan_a()], order("A"), {"A": True})
    acc = result.accumulators["A"]
    assert acc["deductible_used"] == "5000.00"
    assert acc["oop_used"] == "24000.00"
    assert acc["annual_limit_used"] == "76000.00"


def test_explain_my_bill_parts_add_up():
    result = adjudicate_claim(
        claim([one_line("100000")]), [plan_a(), plan_b()], order("A", "B"), {"A": True, "B": True}
    )
    line = result.lines[0]
    assert sum(line.patient_parts.values()) == line.patient
    assert line.patient == Decimal("2400.00")
    assert line.patient_parts["deductible"] == Decimal("0.00")  # secondary paid the primary deductible
