"""COB agent: decide the primary/secondary order for each claim and adjudicate.

The agent deliberately runs the claim twice. The first pass files nothing, so
the engine shows what a claim would cost without pre-authorisation; the agent
then reads that result, notices the penalty, and asks the compliance agent to
file the letters before the final pass. That repair loop is the reason the
final numbers are the ones worth showing the household.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..engines.cob_engine import coordinate
from ..models import ClaimOutcome, money
from .base import AgentBase, CheckResult


@dataclass
class COBResult:
    outcomes: dict[str, ClaimOutcome]
    preliminary: dict[str, ClaimOutcome]
    warnings: list[str]

    @property
    def total_member_out_of_pocket(self):
        return money(sum((outcome.member_out_of_pocket for outcome in self.outcomes.values()), money(0)))

    @property
    def total_savings(self):
        return money(sum((outcome.savings_vs_primary_only for outcome in self.outcomes.values()), money(0)))

    @property
    def preauth_gap_cost(self):
        return money(
            sum(
                (
                    self.preliminary[claim_id].member_out_of_pocket - self.outcomes[claim_id].member_out_of_pocket
                    for claim_id in self.outcomes
                ),
                money(0),
            )
        )

    def to_dict(self) -> dict:
        return {
            "outcomes": {claim_id: outcome.to_dict() for claim_id, outcome in self.outcomes.items()},
            "preliminary_without_preauth": {
                claim_id: {
                    "member_out_of_pocket": str(outcome.member_out_of_pocket),
                    "plan_paid": str(outcome.total_plan_paid),
                }
                for claim_id, outcome in self.preliminary.items()
            },
            "total_member_out_of_pocket": str(self.total_member_out_of_pocket),
            "total_savings": str(self.total_savings),
            "preauth_gap_cost": str(self.preauth_gap_cost),
            "warnings": self.warnings,
        }


class COBAgent(AgentBase):
    name = "COBAgent"
    states = ("ordering", "adjudicating", "validated")

    def preliminary(self, claims, coverage) -> dict[str, ClaimOutcome]:
        outcomes: dict[str, ClaimOutcome] = {}
        for claim in claims:
            primary = coverage.primary_plan_by_member[claim.member_id]
            secondary = coverage.secondary_plan_by_member[claim.member_id]
            # Explicitly "nothing filed yet" for both plans, so the engine shows
            # the penalty a missing pre-authorisation would trigger.
            outcome = coordinate(
                claim,
                primary,
                secondary,
                preauth_obtained={primary: False, secondary: False},
                accumulators=dict(coverage.accumulators),
            )
            outcomes[claim.claim_id] = outcome
        self.act(
            "ordering",
            "Before filing anything, adjudicate each claim as if no pre-authorisation existed. That is how the agent finds out whether a letter is needed at all.",
            "adjudicate_without_preauth",
            observation="; ".join(
                f"{claim_id}: member pays {outcome.member_out_of_pocket}" for claim_id, outcome in outcomes.items()
            ),
            checks=[
                CheckResult(
                    "preauth_requirement_detected",
                    any(any(outcome.preauth_required.values()) for outcome in outcomes.values()),
                    "at least one claim needs pre-authorisation",
                )
            ],
            decision="ask the compliance agent to file pre-auth for the plans that need it",
        )
        return outcomes

    def run(self, claims, coverage, preauth: dict[tuple[str, str], dict]) -> COBResult:
        outcomes: dict[str, ClaimOutcome] = {}
        warnings: list[str] = []

        for claim in claims:
            primary = coverage.primary_plan_by_member[claim.member_id]
            secondary = coverage.secondary_plan_by_member[claim.member_id]
            obtained = {
                plan_id: bool(preauth.get((claim.claim_id, plan_id), {}).get("approved"))
                for plan_id in (primary, secondary)
            }
            self.act(
                "ordering",
                f"{claim.patient_name}: the plan where they are the primary policyholder pays first; the spouse's plan is secondary. "
                "Ordering is a fact about the policy, not a choice.",
                "resolve_cob_order",
                inputs={"claim_id": claim.claim_id, "patient": claim.patient_name},
                observation=f"primary={primary}, secondary={secondary}",
                decision="secondary only sees the residual after the primary pays",
            )
            outcome = coordinate(claim, primary, secondary, preauth_obtained=obtained, accumulators=dict(coverage.accumulators))
            outcomes[claim.claim_id] = outcome
            warnings.extend(outcome.warnings)

        self.transition("validated")
        checks = self._validate(outcomes)
        self.act(
            "validated",
            "Every claim must satisfy the conservation rule: plan payments plus the household's share equal the bill, "
            "and no plan pays more than it allows.",
            "validate_adjudication",
            observation="; ".join(f"{claim_id}: {outcome.total_plan_paid}+{outcome.member_out_of_pocket}" for claim_id, outcome in outcomes.items()),
            checks=checks,
            decision="final numbers accepted" if all(check.passed for check in checks) else "numbers flagged for review",
        )
        return COBResult(outcomes=outcomes, preliminary={}, warnings=warnings)

    def _validate(self, outcomes: dict[str, ClaimOutcome]) -> list[CheckResult]:
        checks: list[CheckResult] = []
        for claim_id, outcome in outcomes.items():
            billed = outcome.claim.total_billed
            conservation = money(outcome.total_plan_paid + outcome.member_out_of_pocket)
            checks.append(
                CheckResult(
                    f"{claim_id}_conservation",
                    conservation == billed,
                    f"paid {outcome.total_plan_paid} + member {outcome.member_out_of_pocket} = {conservation} vs billed {billed}",
                )
            )
            checks.append(
                CheckResult(
                    f"{claim_id}_plan_within_allowed",
                    outcome.primary.plan_paid <= outcome.primary.allowed_total
                    and outcome.secondary.plan_paid <= outcome.secondary.allowed_total,
                    "",
                )
            )
            checks.append(
                CheckResult(
                    f"{claim_id}_secondary_only_residual",
                    outcome.secondary.plan_paid <= outcome.primary.member_paid,
                    "",
                )
            )
        return checks
