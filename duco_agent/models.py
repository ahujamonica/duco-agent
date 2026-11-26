"""Core domain models shared by the agents, engines and mock APIs.

All money is handled as :class:`decimal.Decimal` in INR and rounded to paise.
The models are deliberately plain dataclasses so they can be serialised to the
run trace and to the output JSON without a schema library.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Optional

Money = Decimal
ZERO = Decimal("0.00")


def money(value: Any) -> Money:
    """Return ``value`` as a 2-decimal INR amount."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money_str(value: Money) -> str:
    """Format an amount the way Indian invoices do: ``1,04,500.00``."""
    negative = value < 0
    text = f"{abs(money(value)):,.2f}"
    return f"-{text}" if negative else text


class DocumentKind(str, Enum):
    INVOICE_IMAGE = "invoice_image"
    RADIOLOGY_PDF = "radiology_pdf"
    ESTIMATE_IMAGE = "estimate_image"
    TRANSCRIPT = "transcript"


class LineCategory(str, Enum):
    PROFESSIONAL = "professional"
    FACILITY = "facility"
    THERAPY = "therapy"
    EQUIPMENT = "equipment"
    DIAGNOSTIC = "diagnostic"


@dataclass
class ServiceLine:
    """A single billed service, after coding has been resolved."""

    description: str
    quantity: int
    unit_rate: Money
    billed_amount: Money
    cpt_code: Optional[str] = None
    icd_codes: list[str] = field(default_factory=list)
    category: LineCategory = LineCategory.PROFESSIONAL
    non_covered: bool = False
    code_confidence: float = 0.0
    code_source: str = "printed"  # printed | inferred | unavailable

    def to_dict(self) -> dict:
        data = asdict(self)
        data["unit_rate"] = str(self.unit_rate)
        data["billed_amount"] = str(self.billed_amount)
        data["category"] = self.category.value
        return data


@dataclass
class Claim:
    """A claim (or pre-claim estimate) for one patient under one provider."""

    claim_id: str
    patient_name: str
    member_id: str
    provider_name: str
    service_date: date
    lines: list[ServiceLine]
    document_refs: list[str] = field(default_factory=list)
    narrative: str = ""

    @property
    def total_billed(self) -> Money:
        return money(sum((line.billed_amount for line in self.lines), ZERO))

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "patient_name": self.patient_name,
            "member_id": self.member_id,
            "provider_name": self.provider_name,
            "service_date": self.service_date.isoformat(),
            "total_billed": str(self.total_billed),
            "document_refs": self.document_refs,
            "narrative": self.narrative,
            "lines": [line.to_dict() for line in self.lines],
        }


@dataclass
class PlanTerms:
    """Benefit terms for one mock insurer plan.

 These are illustrative values written for this assessment; they are not
    real policy terms and the README and ``docs/COB_RULES.md`` say so.
    """

    plan_id: str
    insurer_name: str
    plan_name: str
    deductible_per_member: Money
    coinsurance_member: Money  # fraction of the post-deductible balance the member pays
    oop_max_per_member: Money
    preauth_threshold: Money
    preauth_penalty_rate: Money  # reduction of plan payment when pre-auth was skipped
    therapy_session_limit: int = 20
    equipment_covered: bool = False

    @property
    def coinsurance_plan(self) -> Money:
        return money(Decimal("1") - self.coinsurance_member)

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in (
            "deductible_per_member",
            "coinsurance_member",
            "oop_max_per_member",
            "preauth_threshold",
            "preauth_penalty_rate",
        ):
            data[key] = str(data[key])
        return data


@dataclass
class MemberAccumulator:
    """Year-to-date accumulators for one member's benefits year."""

    member_id: str
    plan_id: str
    deductible_used: Money = ZERO
    oop_used: Money = ZERO

    @property
    def deductible_remaining(self) -> Money:  # set by the API wrapper
        return ZERO

    def to_dict(self) -> dict:
        return {
            "member_id": self.member_id,
            "plan_id": self.plan_id,
            "deductible_used": str(self.deductible_used),
            "oop_used": str(self.oop_used),
        }


@dataclass
class LineAdjudication:
    line_description: str
    cpt_code: Optional[str]
    billed: Money
    allowed: Money
    non_covered: Money
    deductible_applied: Money
    coinsurance_member: Money
    plan_paid: Money
    member_paid: Money
    preauth_penalty: Money = ZERO
    member_paid_covered: Money = ZERO
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, Decimal):
                data[key] = str(value)
        return data


@dataclass
class Adjudication:
    """Result of adjudicating one claim under one plan, primary or secondary."""

    claim_id: str
    plan_id: str
    role: str  # primary | secondary
    lines: list[LineAdjudication]
    allowed_total: Money
    non_covered_total: Money
    deductible_applied: Money
    coinsurance_member: Money
    plan_paid: Money
    member_paid: Money
    preauth_penalty: Money = ZERO
    oop_cap_applied: Money = ZERO
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "plan_id": self.plan_id,
            "role": self.role,
            "allowed_total": str(self.allowed_total),
            "non_covered_total": str(self.non_covered_total),
            "deductible_applied": str(self.deductible_applied),
            "coinsurance_member": str(self.coinsurance_member),
            "plan_paid": str(self.plan_paid),
            "member_paid": str(self.member_paid),
            "preauth_penalty": str(self.preauth_penalty),
            "oop_cap_applied": str(self.oop_cap_applied),
            "notes": self.notes,
            "lines": [line.to_dict() for line in self.lines],
        }


@dataclass
class ClaimOutcome:
    """Full coordination-of-benefits outcome for one claim."""

    claim: Claim
    primary_plan: str
    secondary_plan: str
    primary: Adjudication
    secondary: Adjudication
    preauth_required: dict[str, bool]
    preauth_obtained: dict[str, bool]
    household_saving: Money = ZERO
    warnings: list[str] = field(default_factory=list)

    @property
    def total_plan_paid(self) -> Money:
        return money(self.primary.plan_paid + self.secondary.plan_paid)

    @property
    def member_out_of_pocket(self) -> Money:
        """What the household still pays after both plans have paid.

        The secondary plan's payment comes out of the balance the primary plan
        left, so it is subtracted from the primary member share rather than
        added to it.
        """
        return money(self.primary.member_paid - self.secondary.plan_paid)

    @property
    def savings_vs_primary_only(self) -> Money:
        return money(self.primary.member_paid - self.member_out_of_pocket)

    def to_dict(self) -> dict:
        return {
            "claim": self.claim.to_dict(),
            "primary_plan": self.primary_plan,
            "secondary_plan": self.secondary_plan,
            "primary": self.primary.to_dict(),
            "secondary": self.secondary.to_dict(),
            "preauth_required": self.preauth_required,
            "preauth_obtained": self.preauth_obtained,
            "total_plan_paid": str(self.total_plan_paid),
            "member_out_of_pocket": str(self.member_out_of_pocket),
            "savings_vs_primary_only": str(self.savings_vs_primary_only),
            "warnings": self.warnings,
        }


@dataclass
class TraceStep:
    """One recorded thought/action/observation of the agent loop."""

    index: int
    agent: str
    state: str
    thought: str
    action: str
    inputs: dict[str, Any] = field(default_factory=dict)
    observation: str = ""
    checks: list[dict[str, Any]] = field(default_factory=list)
    decision: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)


class ValidationError_(Exception):
    """Raised when a validation loop cannot repair an observation."""
