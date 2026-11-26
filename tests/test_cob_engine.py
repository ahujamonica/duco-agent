"""Arithmetic tests for the coordination-of-benefits engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from duco_agent.config import ACCUMULATORS, PLAN_A, PLAN_B
from duco_agent.engines.cob_engine import coordinate, preauth_required
from duco_agent.models import Claim, LineCategory, MemberAccumulator, ServiceLine, money


def surgery_claim(total_a=350000, total_b=100000) -> Claim:
    return Claim(
        claim_id="CLM-T-1",
        patient_name="Aarav Sen",
        member_id="SEN-A-002",
        provider_name="Test Surgeon",
        service_date=date(2026, 12, 4),
        lines=[
            ServiceLine("ACL reconstruction", 1, money(total_a), money(total_a), "29888", ["S83.511A"], LineCategory.PROFESSIONAL),
            ServiceLine("Meniscectomy", 1, money(total_b), money(total_b), "29881", ["S83.241A"], LineCategory.PROFESSIONAL),
        ],
    )


def fresh_accumulators():
    return {
        ("PLAN_A", "SEN-P-001"): MemberAccumulator("SEN-P-001", "PLAN_A", money(1500), money(1500)),
        ("PLAN_A", "SEN-A-002"): MemberAccumulator("SEN-A-002", "PLAN_A", money(0), money(0)),
        ("PLAN_B", "SEN-P-001"): MemberAccumulator("SEN-P-001", "PLAN_B", money(0), money(0)),
        ("PLAN_B", "SEN-A-002"): MemberAccumulator("SEN-A-002", "PLAN_B", money(2000), money(2000)),
    }


def test_preauth_required_for_surgery_but_not_therapy():
    surgery = surgery_claim()
    assert preauth_required(surgery, PLAN_B) is True
    therapy = Claim(
        "CLM-T-2", "Priya Sen", "SEN-P-001", "Clinic", date(2026, 11, 12),
        [ServiceLine("Therapy", 10, money(2000), money(20000), "97110", ["M54.5"], LineCategory.THERAPY)],
    )
    assert preauth_required(therapy, PLAN_A) is False


def test_primary_deductible_and_coinsurance():
    outcome = coordinate(surgery_claim(), "PLAN_B", "PLAN_A", {"PLAN_B": True, "PLAN_A": True}, fresh_accumulators())
    primary = outcome.primary
    # Aarav has already used 2,000 of the 5,000 deductible, so 3,000 is due.
    assert primary.deductible_applied == money(3000)
    # 450,000 - 3,000 = 447,000; Insurer2 pays 90%, member keeps 10%.
    assert primary.plan_paid == money(402300)
    assert primary.member_paid == money(47700)


def test_secondary_only_sees_the_residual():
    outcome = coordinate(surgery_claim(), "PLAN_B", "PLAN_A", {"PLAN_B": True, "PLAN_A": True}, fresh_accumulators())
    secondary = outcome.secondary
    assert secondary.allowed_total <= outcome.primary.member_paid
    assert secondary.plan_paid < outcome.primary.plan_paid


def test_totals_conserve_and_savings_are_positive():
    outcome = coordinate(surgery_claim(), "PLAN_B", "PLAN_A", {"PLAN_B": True, "PLAN_A": True}, fresh_accumulators())
    assert outcome.total_plan_paid + outcome.member_out_of_pocket == outcome.claim.total_billed
    assert outcome.savings_vs_primary_only == money(34160)


def test_missing_preauth_increases_member_cost():
    with_auth = coordinate(surgery_claim(), "PLAN_B", "PLAN_A", {"PLAN_B": True, "PLAN_A": True}, fresh_accumulators())
    without_auth = coordinate(surgery_claim(), "PLAN_B", "PLAN_A", {"PLAN_B": False, "PLAN_A": False}, fresh_accumulators())
    assert without_auth.member_out_of_pocket > with_auth.member_out_of_pocket
    assert without_auth.primary.preauth_penalty > 0


def test_out_of_pocket_maximum_absorbs_the_member_share():
    """The OOP maximum caps the member's total share, deductible included."""
    tiny_max = MemberAccumulator("SEN-A-002", "PLAN_B", money(0), money(79500))  # only 500 of OOP room left
    outcome = coordinate(surgery_claim(), "PLAN_B", "PLAN_A", {"PLAN_B": True, "PLAN_A": True}, {
        **fresh_accumulators(), ("PLAN_B", "SEN-A-002"): tiny_max,
    })
    primary = outcome.primary
    assert primary.oop_cap_applied > 0
    assert primary.member_paid == money(500) + primary.non_covered_total


def test_equipment_is_never_paid():
    claim = surgery_claim()
    claim.lines.append(ServiceLine("Home traction equipment", 1, money(2500), money(2500), None, [], LineCategory.EQUIPMENT, non_covered=True))
    outcome = coordinate(claim, "PLAN_B", "PLAN_A", {"PLAN_B": True, "PLAN_A": True}, fresh_accumulators())
    assert outcome.primary.non_covered_total == money(2500)
    assert outcome.member_out_of_pocket >= money(2500)


def test_secondary_pays_nothing_when_primary_covers_everything():
    claim = Claim(
        "CLM-T-3", "Priya Sen", "SEN-P-001", "Clinic", date(2026, 11, 12),
        [ServiceLine("Therapy", 2, money(500), money(1000), "97110", ["M54.5"], LineCategory.THERAPY)],
    )
    outcome = coordinate(claim, "PLAN_A", "PLAN_B", {"PLAN_A": True, "PLAN_B": True}, fresh_accumulators())
    assert outcome.member_out_of_pocket >= 0
    assert outcome.total_plan_paid + outcome.member_out_of_pocket == claim.total_billed
