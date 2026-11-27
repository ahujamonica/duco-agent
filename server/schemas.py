"""Request schemas (Pydantic v2) for the public API."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    locale: Literal["en", "hi"] = "en"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class FamilyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    coordination_rule: Literal["policyholder", "birthday", "longest_coverage", "manual"] = "policyholder"
    notes: str | None = None


class FamilyUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    coordination_rule: Literal["policyholder", "birthday", "longest_coverage", "manual"] | None = None
    notes: str | None = None


class MemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    date_of_birth: date | None = None
    age_years: int | None = Field(default=None, ge=0, le=120)
    relation: str = Field(default="self", max_length=30)
    gender: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=30)
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str) -> str:
        return value.strip()


class MemberUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    date_of_birth: date | None = None
    age_years: int | None = Field(default=None, ge=0, le=120)
    relation: str | None = Field(default=None, max_length=30)
    gender: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=30)
    notes: str | None = None


class SublimitIn(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=120)
    limit: str | float = "0"
    used: str | float = "0"
    applies_to_codes: list[str] = []
    applies_to_categories: list[str] = []
    basis: Literal["per_year", "per_claim"] = "per_year"


class ExclusionIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=20)
    keyword: str | None = Field(default=None, max_length=200)


class TermsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sum_insured: str | float = "0"
    deductible: str | float = "0"
    deductible_used: str | float = "0"
    coinsurance_member: str | float = "0"
    oop_max: str | float = "0"
    oop_used: str | float = "0"
    annual_limit: str | float = "0"
    annual_limit_used: str | float = "0"
    preauth_threshold: str | float = "0"
    preauth_penalty_rate: str | float = "0"
    waiting_period_days: int = 0
    allowed_factor: str | float = "1"
    network_only: bool = False
    preauth_always: bool = False
    covers_primary_exclusions: bool = False
    sublimits: list[SublimitIn] = []
    exclusions: list[ExclusionIn | str] = []
    preauth_cpt_codes: list[str] = []
    preauth_categories: list[str] = []


class MemberLinkIn(BaseModel):
    member_id: int
    role: str = "dependent"


class PolicyIn(BaseModel):
    family_id: int
    insurer_name: str = Field(min_length=1, max_length=160)
    plan_name: str = Field(min_length=1, max_length=160)
    policy_number: str = Field(min_length=1, max_length=80)
    policyholder_member_id: int | None = None
    status: Literal["active", "inactive", "expired"] = "active"
    start_date: date | None = None
    end_date: date | None = None
    coordination_rule: Literal["policyholder", "birthday", "longest_coverage", "manual"] = "policyholder"
    terms: TermsIn = TermsIn()
    members: list[MemberLinkIn] = []


class PolicyUpdateIn(BaseModel):
    insurer_name: str | None = Field(default=None, max_length=160)
    plan_name: str | None = Field(default=None, max_length=160)
    policy_number: str | None = Field(default=None, max_length=80)
    policyholder_member_id: int | None = None
    status: Literal["active", "inactive", "expired"] | None = None
    start_date: date | None = None
    end_date: date | None = None
    coordination_rule: Literal["policyholder", "birthday", "longest_coverage", "manual"] | None = None
    terms: TermsIn | None = None
    change_note: str | None = None


class PolicyExtractIn(BaseModel):
    document_id: int


class PolicyVersionIn(BaseModel):
    terms: TermsIn
    change_note: str | None = None
    effective_from: date | None = None


class PolicyMemberIn(BaseModel):
    member_id: int
    role: str = "dependent"


class DocumentTypeIn(BaseModel):
    doc_type: Literal[
        "invoice", "estimate", "policy", "radiology", "prescription", "discharge", "transcript", "unknown"
    ]


class CaseIn(BaseModel):
    family_id: int
    title: str = Field(min_length=2, max_length=200)
    patient_member_id: int
    selected_member_ids: list[int] = Field(default_factory=list)
    provider_name: str = ""
    provider_in_network: bool = True
    service_date: date | None = None
    narrative: str | None = None
    document_ids: list[int] = []
    policy_ids: list[int] = []
    policy_order: list[int] = []
    coordination_rule: Literal["policyholder", "birthday", "longest_coverage", "manual"] | None = None
    manual_lines: list[dict[str, Any]] = []


class CaseUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    provider_name: str | None = None
    provider_in_network: bool | None = None
    service_date: date | None = None
    narrative: str | None = None
    document_ids: list[int] | None = None
    policy_ids: list[int] | None = None
    policy_order: list[int] | None = None
    coordination_rule: Literal["policyholder", "birthday", "longest_coverage", "manual"] | None = None
    review_confirmed: bool | None = None


class ReviewItemIn(BaseModel):
    id: int
    status: Literal["accepted", "corrected"]
    value: str | None = None


class ReviewIn(BaseModel):
    items: list[ReviewItemIn] = []
    confirm: bool = True


class SimulateIn(BaseModel):
    policies: dict[str, dict[str, str | float | bool]] = {}


class ProfileIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    locale: Literal["en", "hi"] | None = None


class DemoScenarioIn(BaseModel):
    scenario: str = "main"
