"""Database entities for the DuCO Agent platform.

The schema is deliberately normalised around the things a real coordination
case needs: a household, its members, policies (versioned), documents, cases,
claims and lines, and a full audit trail of agent and mock-insurer activity.

Money is stored as ``Numeric(14, 2)`` and converted to ``Decimal`` in Python;
it is never stored or computed as a float.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ref(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4).upper()}"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    families: Mapped[list["Family"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Family(Base):
    __tablename__ = "families"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    coordination_rule: Mapped[str] = mapped_column(String(40), default="policyholder")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    owner: Mapped["User"] = relationship(back_populates="families")
    members: Mapped[list["FamilyMember"]] = relationship(
        back_populates="family", cascade="all, delete-orphan", order_by="FamilyMember.id"
    )
    policies: Mapped[list["Policy"]] = relationship(
        back_populates="family", cascade="all, delete-orphan", order_by="Policy.id"
    )
    documents: Mapped[list["Document"]] = relationship(back_populates="family", cascade="all, delete-orphan")
    cases: Mapped[list["Case"]] = relationship(
        back_populates="family", cascade="all, delete-orphan", order_by="Case.id.desc()"
    )


class FamilyMember(Base):
    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relation: Mapped[str] = mapped_column("relationship", String(30), default="self")
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    family: Mapped["Family"] = relationship(back_populates="members")
    policy_links: Mapped[list["PolicyMember"]] = relationship(
        back_populates="member", cascade="all, delete-orphan"
    )


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"), index=True)
    insurer_name: Mapped[str] = mapped_column(String(160))
    plan_name: Mapped[str] = mapped_column(String(160))
    policy_number: Mapped[str] = mapped_column(String(80), index=True)
    policyholder_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("family_members.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | inactive | expired
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    coordination_rule: Mapped[str] = mapped_column(String(40), default="policyholder")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    family: Mapped["Family"] = relationship(back_populates="policies")
    versions: Mapped[list["PolicyVersion"]] = relationship(
        back_populates="policy", cascade="all, delete-orphan", order_by="PolicyVersion.version"
    )
    member_links: Mapped[list["PolicyMember"]] = relationship(
        back_populates="policy", cascade="all, delete-orphan"
    )

    @property
    def current_version(self) -> "PolicyVersion | None":
        if not self.versions:
            return None
        # Demo scenario snapshots are isolated fixtures, not edits the household
        # made. Keep the latest manually-created version as "current" when one
        # exists; a real policy has no demo versions at all.
        manual = [version for version in self.versions if version.source != "demo"]
        return (manual or self.versions)[-1]


class PolicyVersion(Base):
    """A point-in-time set of benefit terms.

    Claims store the version they were adjudicated under. Editing terms creates
    a new version so an earlier claim can always be reproduced.
    """

    __tablename__ = "policy_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Money and rates
    sum_insured: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    deductible: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    deductible_used: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    coinsurance_member: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)  # 0.20 = member pays 20%
    oop_max: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    oop_used: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    annual_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    annual_limit_used: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    preauth_threshold: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    preauth_penalty_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)
    waiting_period_days: Mapped[int] = mapped_column(Integer, default=0)
    allowed_factor: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=1)  # network/contractual rate
    network_only: Mapped[bool] = mapped_column(Boolean, default=False)
    preauth_always: Mapped[bool] = mapped_column(Boolean, default=False)
    covers_primary_exclusions: Mapped[bool] = mapped_column(Boolean, default=False)
    # Structured terms
    sublimits: Mapped[list] = mapped_column(JSON, default=list)
    exclusions: Mapped[list] = mapped_column(JSON, default=list)
    preauth_cpt_codes: Mapped[list] = mapped_column(JSON, default=list)
    preauth_categories: Mapped[list] = mapped_column(JSON, default=list)
    extraction: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(30), default="manual")  # manual | document
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    policy: Mapped["Policy"] = relationship(back_populates="versions")

    def terms(self) -> dict:
        return {
            "sum_insured": self.sum_insured,
            "deductible": self.deductible,
            "deductible_used": self.deductible_used,
            "coinsurance_member": self.coinsurance_member,
            "oop_max": self.oop_max,
            "oop_used": self.oop_used,
            "annual_limit": self.annual_limit,
            "annual_limit_used": self.annual_limit_used,
            "preauth_threshold": self.preauth_threshold,
            "preauth_penalty_rate": self.preauth_penalty_rate,
            "waiting_period_days": self.waiting_period_days,
            "allowed_factor": self.allowed_factor,
            "network_only": self.network_only,
            "preauth_always": self.preauth_always,
            "covers_primary_exclusions": self.covers_primary_exclusions,
            "sublimits": self.sublimits or [],
            "exclusions": self.exclusions or [],
            "preauth_cpt_codes": self.preauth_cpt_codes or [],
            "preauth_categories": self.preauth_categories or [],
        }


class PolicyAccumulator(Base):
    """Year-to-date benefit usage for one member under one policy version.

    Deductibles, out-of-pocket spend and annual limits are tracked per person,
    not per policy: Aarav using his deductible must not consume Priya's.
    """

    __tablename__ = "policy_accumulators"
    __table_args__ = (UniqueConstraint("policy_version_id", "member_id", name="uq_version_member_accum"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_version_id: Mapped[int] = mapped_column(
        ForeignKey("policy_versions.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id", ondelete="CASCADE"), index=True)
    deductible_used: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    oop_used: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    annual_limit_used: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    sublimits: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PolicyMember(Base):
    __tablename__ = "policy_members"
    __table_args__ = (UniqueConstraint("policy_id", "member_id", name="uq_policy_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30), default="dependent")  # policyholder | spouse | dependent | child | parent
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    policy: Mapped["Policy"] = relationship(back_populates="member_links")
    member: Mapped["FamilyMember"] = relationship(back_populates="policy_links")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"), index=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(120), unique=True)
    mime: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    doc_type: Mapped[str] = mapped_column(String(40), default="unknown")
    classification_confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0)
    status: Mapped[str] = mapped_column(String(30), default="uploaded")  # uploaded|processed|needs_review|confirmed|failed
    pages: Mapped[int] = mapped_column(Integer, default=1)
    method: Mapped[str] = mapped_column(String(30), default="unknown")  # ocr|pdf_text|manual|transcript
    mean_ocr_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    family: Mapped["Family"] = relationship(back_populates="documents")


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    patient_member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id", ondelete="CASCADE"))
    provider_name: Mapped[str] = mapped_column(String(200), default="")
    provider_in_network: Mapped[bool] = mapped_column(Boolean, default=True)
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    # draft | documents_pending | awaiting_review | ready | running | awaiting_authorization | complete | failed
    coordination_rule: Mapped[str] = mapped_column(String(40), default="policyholder")
    policy_version_ids: Mapped[list] = mapped_column(JSON, default=list)
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    review_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    workflow_state: Mapped[dict] = mapped_column(JSON, default=dict)
    totals: Mapped[dict] = mapped_column(JSON, default=dict)
    run_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    family: Mapped["Family"] = relationship(back_populates="cases")
    claims: Mapped[list["Claim"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    adjudications: Mapped[list["Adjudication"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    review_items: Mapped[list["ReviewItem"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    events: Mapped[list["AgentEvent"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="AgentEvent.seq"
    )
    preauths: Mapped[list["Preauthorization"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    reports: Mapped[list["Report"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("family_members.id", ondelete="SET NULL"), nullable=True
    )
    patient_name: Mapped[str] = mapped_column(String(120), default="")
    provider_name: Mapped[str] = mapped_column(String(200), default="")
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bill_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    case: Mapped["Case"] = relationship(back_populates="claims")
    lines: Mapped[list["ClaimLine"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="ClaimLine.id"
    )


class ClaimLine(Base):
    __tablename__ = "claim_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    cpt_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    icd_codes: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(40), default="professional")
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    code_confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0)
    code_source: Mapped[str] = mapped_column(String(30), default="printed")
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    claim: Mapped["Claim"] = relationship(back_populates="lines")


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    field_key: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(160))
    extracted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | accepted | corrected
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    case: Mapped["Case"] = relationship(back_populates="review_items")


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (UniqueConstraint("case_id", "seq", name="uq_case_event_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str] = mapped_column(String(64), default="")
    agent: Mapped[str] = mapped_column(String(60))
    goal: Mapped[str] = mapped_column(String(120), default="")
    state: Mapped[str] = mapped_column(String(60), default="")
    action: Mapped[str] = mapped_column(String(200), default="")
    tool: Mapped[str | None] = mapped_column(String(120), nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    observation: Mapped[str] = mapped_column(Text, default="")
    checks: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[str] = mapped_column(Text, default="")
    next_action: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="succeeded")  # running|succeeded|failed|skipped|waiting
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    case: Mapped["Case"] = relationship(back_populates="events")


class Adjudication(Base):
    __tablename__ = "adjudications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"))
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"))
    policy_version_id: Mapped[int] = mapped_column(ForeignKey("policy_versions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))  # primary | secondary | tertiary
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    allowed: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    plan_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    member_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    case: Mapped["Case"] = relationship(back_populates="adjudications")


class EligibilityCheck(Base):
    __tablename__ = "eligibility_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"))
    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30))
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Preauthorization(Base):
    __tablename__ = "preauthorizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"))
    policy_version_id: Mapped[int] = mapped_column(ForeignKey("policy_versions.id", ondelete="CASCADE"))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="not_required")
    # not_required | required | submitted | approved | pending | rejected
    reference: Mapped[str] = mapped_column(String(60), default="")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    letter_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    case: Mapped["Case"] = relationship(back_populates="preauths")


class MockApiLog(Base):
    __tablename__ = "mock_api_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"), nullable=True)
    endpoint: Mapped[str] = mapped_column(String(120))
    method: Mapped[str] = mapped_column(String(10), default="POST")
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MockClaim(Base):
    """A claim submitted to the simulated insurer API, with its response."""

    __tablename__ = "mock_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"), nullable=True)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("policies.id", ondelete="SET NULL"), nullable=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("family_members.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="received")
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # json | html | pdf_letter | audio | trace
    title: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    case: Mapped["Case"] = relationship(back_populates="reports")


class SimulatorRun(Base):
    __tablename__ = "simulator_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def to_num(value) -> Decimal:
    """Coerce an incoming value to a 2dp Decimal without float drift."""
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))
