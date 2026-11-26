"""Compliance agent: decide what needs pre-authorisation, file it, draft the letters.

Insurers reject claims for missing pre-auth far more often than for clinical
reasons, so this agent checks the requirement itself, submits the request to the
mock API, and renders a letter that carries the diagnosis codes, the CPT codes,
the provider's registration and the coordination position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import PLANS
from ..engines.cob_engine import preauth_required
from ..engines.preauth import build_letter
from ..tools.insurer_api import InsurerAPIClient
from .base import AgentBase, CheckResult

JUSTIFICATIONS = {
    "CLM-2026-A-ACL": (
        "MRI of the right knee confirms a complete tear of the anterior cruciate ligament with a complex tear of "
        "the medial meniscus and a joint effusion. The patient reports repeated instability and giving way during "
        "routine activity. Arthroscopic ACL reconstruction with partial meniscectomy is planned. Conservative "
        "management including physiotherapy has not restored stability. The requested procedure is reconstructive, "
        "not cosmetic, and delay risks further meniscal damage."
    ),
    "CLM-2026-P-PT": (
        "The patient completed a supervised course of physiotherapy for chronic low back pain: one evaluation and "
        "twelve therapeutic exercise sessions combining ultrasound and interferential therapy. The invoice does not "
        "print billing codes; CPT 97161 and 97110 have been derived from the documented service descriptions. "
        "The home traction device on the invoice is not claimed as a covered benefit."
    ),
}


@dataclass
class PreAuthRecord:
    claim_id: str
    plan_id: str
    required: bool
    approved: bool = False
    reference: str = ""
    letter_path: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "plan_id": self.plan_id,
            "required": self.required,
            "approved": self.approved,
            "reference": self.reference,
            "letter_path": self.letter_path,
            "note": self.note,
        }


@dataclass
class ComplianceResult:
    records: dict[tuple[str, str], PreAuthRecord] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def obtained_map(self) -> dict[tuple[str, str], dict]:
        return {
            key: {"approved": record.approved, "reference": record.reference}
            for key, record in self.records.items()
        }

    def to_dict(self) -> dict:
        return {
            "records": [record.to_dict() for record in self.records.values()],
            "warnings": self.warnings,
        }


class ComplianceAgent(AgentBase):
    name = "ComplianceAgent"
    states = ("checking", "filing", "drafted")

    def __init__(self, trace, client: InsurerAPIClient | None = None) -> None:
        super().__init__(trace)
        self.client = client or InsurerAPIClient()

    def run(self, claims, coverage, output_dir: Path) -> ComplianceResult:
        result = ComplianceResult()
        letters_dir = output_dir / "preauth_letters"
        letters_dir.mkdir(parents=True, exist_ok=True)

        for claim in claims:
            primary_id = coverage.primary_plan_by_member[claim.member_id]
            secondary_id = coverage.secondary_plan_by_member[claim.member_id]
            justification = JUSTIFICATIONS.get(claim.claim_id, "")
            for plan_id in (primary_id, secondary_id):
                plan = PLANS[plan_id]
                required = preauth_required(claim, plan)
                record = PreAuthRecord(claim_id=claim.claim_id, plan_id=plan_id, required=required)
                if not required:
                    record.note = "no pre-authorisation required for this benefit; claim can be filed directly"
                    result.records[(claim.claim_id, plan_id)] = record
                    self.act(
                        "checking",
                        f"{claim.claim_id}/{plan_id}: the threshold and code rules say no pre-authorisation is needed, so no letter is filed.",
                        "check_preauth_requirement",
                        inputs={"claim_id": claim.claim_id, "plan_id": plan_id},
                        observation=record.note,
                        checks=[CheckResult("requirement_assessed", True, "not required")],
                        decision="skip filing",
                    )
                    continue

                role = "primary" if plan_id == primary_id else "secondary"
                submission = self.client.submit_preauth(
                    plan_id,
                    claim.member_id,
                    claim.claim_id,
                    payload={
                        "cpt_codes": [line.cpt_code for line in claim.lines if line.cpt_code],
                        "icd_codes": claim.lines[0].icd_codes if claim.lines else [],
                        "estimated_cost": str(claim.total_billed),
                        "role": role,
                    },
                )
                record.approved = submission.get("status") == "approved"
                record.reference = submission.get("preauth_id", "")
                if not record.approved:
                    result.warnings.append(f"{claim.claim_id}/{plan_id}: pre-auth submission not approved - {submission}")
                    self.act(
                        "filing",
                        "The submission did not come back approved; keep the reference and warn instead of pretending the claim is safe.",
                        "submit_preauth",
                        inputs={"claim_id": claim.claim_id, "plan_id": plan_id},
                        observation=str(submission),
                        decision="warn and continue",
                    )

                letter_path = letters_dir / f"{claim.claim_id}_{plan_id}.pdf"
                letter = build_letter(
                    claim,
                    plan,
                    record.reference,
                    role,
                    claim.lines[0].icd_codes if claim.lines else [],
                    justification,
                    letter_path,
                )
                record.letter_path = str(letter_path)
                size = letter_path.stat().st_size if letter_path.exists() else 0
                letter_text = ""
                if letter_path.exists():
                    import pymupdf

                    with pymupdf.open(str(letter_path)) as document:
                        letter_text = "\n".join(page.get_text("text") for page in document)
                checks = [
                    CheckResult("submission_approved", record.approved, record.reference),
                    CheckResult("letter_written", size > 2000, f"{size} bytes"),
                    CheckResult(
                        "codes_on_letter",
                        all(code in letter_text for code in letter.diagnosis_codes),
                        "every diagnosis code appears in the letter text",
                    ),
                    CheckResult(
                        "procedure_codes_on_letter",
                        all((line.cpt_code or "n/a") in letter_text for line in claim.lines),
                        "",
                    ),
                ]
                self.act(
                    "filing",
                    f"{claim.claim_id}/{plan_id}: file the pre-authorisation and render the letter with the diagnosis and procedure codes so the claim cannot be rejected for a missing reference.",
                    "submit_preauth_and_draft_letter",
                    inputs={"claim_id": claim.claim_id, "plan_id": plan_id, "role": role},
                    observation=f"reference={record.reference}, letter={letter_path.name} ({size} bytes)",
                    checks=checks,
                    decision="letter ready to send" if all(check.passed for check in checks) else "letter drafted, check the warning",
                )
                result.records[(claim.claim_id, plan_id)] = record

        self.transition("drafted")
        return result
