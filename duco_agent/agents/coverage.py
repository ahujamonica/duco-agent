"""Coverage agent: prove who is covered, where, and in which role."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import MEMBERS, PLANS, PRIMARY_PLAN_BY_PATIENT, SECONDARY_PLAN_BY_PATIENT
from ..models import MemberAccumulator, money
from ..tools.insurer_api import InsurerAPIClient
from .base import AgentBase, CheckResult


@dataclass
class CoverageResult:
    eligibility: dict
    benefits: dict
    accumulators: dict[tuple[str, str], MemberAccumulator]
    primary_plan_by_member: dict[str, str]
    secondary_plan_by_member: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "eligibility": self.eligibility,
            "benefits": self.benefits,
            "primary_plan_by_member": self.primary_plan_by_member,
            "secondary_plan_by_member": self.secondary_plan_by_member,
            "warnings": self.warnings,
        }


class CoverageAgent(AgentBase):
    name = "CoverageAgent"
    states = ("coverage", "verified", "blocked")

    def __init__(self, trace, client: InsurerAPIClient | None = None) -> None:
        super().__init__(trace)
        self.client = client or InsurerAPIClient()

    def run(self, claims) -> CoverageResult:
        eligibility: dict[str, dict] = {}
        benefits: dict[str, dict] = {}
        accumulators: dict[tuple[str, str], MemberAccumulator] = {}
        warnings: list[str] = []

        for claim in claims:
            primary_plan = PRIMARY_PLAN_BY_PATIENT[claim.patient_name]
            secondary_plan = SECONDARY_PLAN_BY_PATIENT[claim.patient_name]
            member = MEMBERS[claim.member_id]
            for plan_id in (primary_plan, secondary_plan):
                key = f"{claim.member_id}:{plan_id}"
                result = self.client.eligibility(plan_id, claim.member_id)
                eligibility[key] = result
                if not result.get("eligible"):
                    warnings.append(f"{claim.patient_name} is not eligible under {plan_id}")
                    continue
                expected_role = "primary" if plan_id == primary_plan else "dependent"
                if result.get("role") != expected_role:
                    warnings.append(
                        f"{plan_id} lists {claim.patient_name} as {result.get('role')}, expected {expected_role}"
                    )
                details = self.client.benefits(plan_id, claim.member_id)
                benefits[key] = details
                accumulators[(plan_id, claim.member_id)] = MemberAccumulator(
                    member_id=claim.member_id,
                    plan_id=plan_id,
                    deductible_used=money(details["accumulators"]["deductible_used"]),
                    oop_used=money(details["accumulators"]["oop_used"]),
                )

        self.transition("verified")
        self.act(
            "coverage",
            "Coverage is not assumed from the user's story: each plan is asked who the member is and in what role, "
            "and the year-to-date accumulators are pulled from the insurer before any maths.",
            "verify_eligibility_and_benefits",
            inputs={"members": [claim.member_id for claim in claims], "plans": list(PLANS)},
            observation="; ".join(
                f"{key}={value.get('role')}/{value.get('policy_status')}" for key, value in eligibility.items()
            ),
            checks=[
                CheckResult("all_eligible", all(item.get("eligible") for item in eligibility.values()), ""),
                CheckResult("roles_match_expected", not any("expected" in warning for warning in warnings), str(warnings)),
                CheckResult("accumulators_loaded", len(accumulators) == 4, f"{len(accumulators)} loaded"),
            ],
            decision="coverage verified; hand to the COB agent",
        )
        return CoverageResult(
            eligibility=eligibility,
            benefits=benefits,
            accumulators=accumulators,
            primary_plan_by_member={claim.member_id: PRIMARY_PLAN_BY_PATIENT[claim.patient_name] for claim in claims},
            secondary_plan_by_member={claim.member_id: SECONDARY_PLAN_BY_PATIENT[claim.patient_name] for claim in claims},
            warnings=warnings,
        )
