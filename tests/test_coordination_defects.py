"""Regression tests for defects found in the independent engine review.

Each test is a minimal failing input from the review: expected vs actual.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from duco_agent.engines.coordination import (
    Exclusion,
    InsurancePlan,
    LineInput,
    OrderDecision,
    Sublimit,
    adjudicate_claim,
    money,
    primary_only_totals,
)

from tests.test_coordination_engine import claim, one_line, order, plan_a, plan_b


def simple_plan(key="A", **overrides) -> InsurancePlan:
    values = dict(
        key=key,
        insurer=f"{key} Insurer",
        plan_name="Simple",
        policy_number=f"POL-{key}",
        deductible_total=Decimal("0"),
        coinsurance_member=Decimal("0"),
        oop_max=Decimal("0"),
        annual_limit=Decimal("0"),
        start_date=date(2024, 1, 1),
        member_role="policyholder",
    )
    values.update(overrides)
    return InsurancePlan(**values)


def third_plan(**overrides) -> InsurancePlan:
    return simple_plan("C", **overrides)


def test_rounding_never_breaks_the_bill_reconciliation():
    result = adjudicate_claim(
        claim([one_line("100.01")]),
        [simple_plan(allowed_factor=Decimal("0.5"))],
        order("A"),
        {"A": True},
    )
    totals = result.totals
    assert totals["insurer_paid"] + totals["patient_liability"] + totals["contractual_adjustment"] == Decimal("100.01")
    assert result.plans[0].contractual_total == Decimal("50.00")
    assert result.plans[0].allowed_total == Decimal("50.01")
    assert all(inv.passed for inv in result.invariants)


def test_sub_limit_excess_is_offered_to_the_next_plan():
    result = adjudicate_claim(
        claim([one_line("30000", cpt="97110", category="therapy")]),
        [
            simple_plan(sublimits=[Sublimit("therapy", "Therapy limit", Decimal("20000"), applies_to_categories=["therapy"])]),
            simple_plan("B"),
        ],
        order("A", "B"),
        {"A": True, "B": True},
    )
    assert result.plans[0].plan_paid == Decimal("20000.00")
    assert result.plans[1].plan_paid == Decimal("10000.00")
    assert result.totals["patient_liability"] == Decimal("0.00")
    assert all(inv.passed for inv in result.invariants)


def test_middle_plan_exclusion_leaves_the_residual_for_later_plans():
    result = adjudicate_claim(
        claim([one_line("15000", cpt="E0114", category="equipment")]),
        [plan_a(), plan_b(exclusions=[Exclusion(label="Durable equipment", code="E0114")]), third_plan()],
        order("A", "B", "C"),
        {"A": True, "B": True, "C": True},
    )
    assert result.plans[0].plan_paid == Decimal("8000.00")
    assert result.plans[1].plan_paid == Decimal("0.00")
    assert result.plans[2].plan_paid == Decimal("7000.00")
    assert result.totals["patient_liability"] == Decimal("0.00")
    assert all(inv.passed for inv in result.invariants)


def test_later_plan_factor_does_not_price_the_residual():
    result = adjudicate_claim(
        claim([one_line("100000")]),
        [plan_a(), plan_b(allowed_factor=Decimal("0.9"), coinsurance_member=Decimal("0.10"))],
        order("A", "B"),
        {"A": True, "B": True},
    )
    assert result.plans[1].contractual_total == Decimal("0.00")
    assert result.plans[1].plan_paid == Decimal("21600.00")
    assert result.totals["excluded"] == Decimal("0.00")
    assert not any(v < 0 for line in result.lines for v in line.patient_parts.values())
    assert all(inv.passed for inv in result.invariants)


def test_sum_insured_caps_payment_when_annual_limit_is_unset():
    result = adjudicate_claim(
        claim([one_line("900000")]),
        [simple_plan(sum_insured=Decimal("500000"))],
        order("A"),
        {"A": True},
    )
    assert result.plans[0].plan_paid == Decimal("500000.00")
    assert result.totals["patient_liability"] == Decimal("400000.00")
    assert all(inv.passed for inv in result.invariants)


def test_out_of_pocket_maximum_does_not_erase_the_preauth_penalty():
    result = adjudicate_claim(
        claim([one_line("100000")]),
        [plan_a(oop_max=Decimal("60000"), oop_used=Decimal("60000"), deductible_used=Decimal("5000"))],
        order("A"),
        {"A": False},
    )
    assert result.plans[0].penalty_total == Decimal("16000.00")
    assert result.totals["patient_liability"] == Decimal("16000.00")
    assert result.plans[0].plan_paid == Decimal("84000.00")
    assert all(inv.passed for inv in result.invariants)


def test_out_of_pocket_accumulator_excludes_annual_limit_excess():
    result = adjudicate_claim(
        claim([one_line("100000")]),
        [plan_a(coinsurance_member=Decimal("0.5"), oop_max=Decimal("30000"), annual_limit=Decimal("40000"))],
        order("A"),
        {"A": True},
    )
    assert result.accumulators["A"]["oop_used"] == "30000.00"
    assert all(inv.passed for inv in result.invariants)


def test_sub_limit_applies_after_the_network_discount():
    result = adjudicate_claim(
        claim([one_line("30000", cpt="97110", category="therapy")]),
        [
            simple_plan(
                allowed_factor=Decimal("0.9"),
                sublimits=[Sublimit("therapy", "Therapy limit", Decimal("20000"), applies_to_categories=["therapy"])],
            )
        ],
        order("A"),
        {"A": True},
    )
    assert result.plans[0].allowed_total == Decimal("20000.00")
    assert result.plans[0].plan_paid == Decimal("20000.00")
    assert result.plans[0].contractual_total == Decimal("3000.00")
    assert result.totals["patient_liability"] == Decimal("7000.00")
    assert all(inv.passed for inv in result.invariants)


def test_per_claim_sub_limit_is_not_accumulated_across_claims():
    result = adjudicate_claim(
        claim([one_line("10000", cpt="97110", category="therapy")]),
        [
            simple_plan(
                sublimits=[
                    Sublimit(
                        "therapy",
                        "Per-claim therapy limit",
                        Decimal("20000"),
                        used=Decimal("20000"),
                        applies_to_categories=["therapy"],
                        basis="per_claim",
                    )
                ]
            )
        ],
        order("A"),
        {"A": True},
    )
    assert result.plans[0].plan_paid == Decimal("10000.00")
    assert result.accumulators["A"]["sublimits"]["therapy"]["used"] == "20000.00"
    assert all(inv.passed for inv in result.invariants)


def test_duplicate_plan_key_pays_once_and_fails_its_check():
    duplicates = [OrderDecision("A", "primary", 1, "policyholder"), OrderDecision("A", "secondary", 2, "policyholder")]
    result = adjudicate_claim(claim([one_line()]), [plan_a()], duplicates, {"A": True})
    assert result.plans[0].plan_paid == Decimal("76000.00")
    assert result.totals["insurer_paid"] == Decimal("76000.00")
    failed = [inv.name for inv in result.invariants if not inv.passed]
    assert "Plan order names each plan once" in failed
    assert any("more than once" in warning for warning in result.warnings)


def test_exclusion_keywords_match_whole_words_only():
    result = adjudicate_claim(
        claim([one_line("20000", cpt="93000", description="Cardiology - heart echo")]),
        [simple_plan(exclusions=[Exclusion(label="Hearing aids", keyword="ear")])],
        order("A"),
        {"A": True},
    )
    assert result.plans[0].plan_paid == Decimal("20000.00")
    assert result.totals["patient_liability"] == Decimal("0.00")


def test_primary_only_totals_uses_the_primary_contractual_write_off():
    result = adjudicate_claim(
        claim([one_line("100000")]),
        [plan_a(), plan_b(allowed_factor=Decimal("0.9"))],
        order("A", "B"),
        {"A": True, "B": True},
    )
    primary_only = primary_only_totals(result)
    assert primary_only["patient_liability"] == Decimal("24000.00")


def test_negative_bill_line_is_clamped_and_warned():
    line = one_line("500")
    line.billed = money("-500")
    result = adjudicate_claim(claim([line]), [plan_a()], order("A"), {"A": True})
    assert result.totals["billed"] == Decimal("0.00")
    assert result.totals["patient_liability"] == Decimal("0.00")
    assert any("negative billed amount" in warning for warning in result.warnings)


def test_allowed_factor_outside_the_range_is_flagged_not_paid():
    for factor in (Decimal("0"), Decimal("1.2")):
        result = adjudicate_claim(
            claim([one_line("100000")]),
            [simple_plan(allowed_factor=factor)],
            order("A"),
            {"A": True},
        )
        assert result.plans[0].plan_paid <= Decimal("100000.00")
        assert any("allowed_factor" in warning for warning in result.warnings)
        failed = [inv.name for inv in result.invariants if not inv.passed]
        assert "Allowed factors are within (0, 1]" in failed


def test_out_of_pocket_absorption_keeps_the_deductible_accumulator_consistent():
    plan = simple_plan(deductible_total=Decimal("5000"), coinsurance_member=Decimal("0"), oop_max=Decimal("2000"))
    result = adjudicate_claim(
        claim([one_line("3000"), one_line("3000")]),
        [plan],
        order("A"),
        {"A": True},
    )
    state = result.plan_state["A"]
    used = money(result.accumulators["A"]["deductible_used"])
    # The out-of-pocket maximum paid part of the deductible, so only what the
    # member actually paid consumes it: used + remaining still equals 5,000.
    assert used == Decimal("2000.00")
    assert money(used + state["deductible_remaining"]) == Decimal("5000.00")
    assert all(inv.passed for inv in result.invariants)


def test_adding_a_plan_never_raises_patient_liability():
    lines = [one_line("15000", cpt="E0114", category="equipment")]
    base = adjudicate_claim(claim(lines), [plan_a(), third_plan()], order("A", "C"), {"A": True, "C": True})
    middle = adjudicate_claim(
        claim(lines),
        [plan_a(), plan_b(exclusions=[Exclusion(label="Durable equipment", code="E0114")]), third_plan()],
        order("A", "B", "C"),
        {"A": True, "B": True, "C": True},
    )
    assert middle.totals["patient_liability"] <= base.totals["patient_liability"]
