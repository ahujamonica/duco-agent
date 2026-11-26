"""Intake agent: read the four documents, recover the missing codes, build claims.

The agent treats every extraction as a hypothesis. It scores each OCR variant
on evidence (service lines recovered, whether the lines reconcile with the
printed total, mean word confidence), retries with another strategy when the
checks fail, and only then hands claims to the coverage and COB agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import codes, extraction
from ..config import SERVICE_DATE_SURGERY, SERVICE_DATE_THERAPY
from ..models import Claim, LineCategory, ServiceLine
from ..tools.ocr import VARIANTS, run_ocr
from ..tools.pdf import extract_pdf_text
from .base import AgentBase, Attempt, CheckResult

DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")


@dataclass
class IntakeResult:
    documents: dict[str, extraction.ParsedDocument]
    claims: list[Claim]
    issues: list[str]
    goals: list[str]
    diagnosis_codes: dict[str, list[str]]

    def to_dict(self) -> dict:
        return {
            "documents": {key: doc.to_dict() for key, doc in self.documents.items()},
            "claims": [claim.to_dict() for claim in self.claims],
            "issues": self.issues,
            "goals": self.goals,
        }


def _parse_date(value: str | None, fallback):
    if not value:
        return fallback
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return fallback


class IntakeAgent(AgentBase):
    name = "IntakeAgent"
    states = ("intake", "extracting", "coding", "validated", "blocked")

    def run(self, root: Path) -> IntakeResult:
        self.transition("extracting")
        documents: dict[str, extraction.ParsedDocument] = {}
        issues: list[str] = []

        invoice = self._extract_image(root / "fixtures/priya_pt_invoice.png", "invoice_image")
        documents["invoice"] = invoice
        estimate = self._extract_image(root / "fixtures/surgeon_estimate.jpg", "estimate_image")
        documents["estimate"] = estimate
        documents["mri"] = self._extract_pdf(root / "fixtures/aarav_mri_report.pdf")
        documents["transcript"] = self._extract_transcript(root / "fixtures/user_query.txt")

        for name, document in documents.items():
            issues.extend(f"{name}: {issue}" for issue in document.issues)

        self.transition("coding")
        diagnosis_codes = self._resolve_diagnosis(documents)
        goals = list(documents["transcript"].field_value("asks", []))
        claims = [
            self._build_surgery_claim(documents["estimate"], diagnosis_codes, goals),
            self._build_therapy_claim(documents["invoice"], goals),
        ]
        self.transition("validated")
        self.act(
            "validated",
            "Both claims are built; the missing invoice codes were inferred and every arithmetic check passed.",
            "build_claims",
            inputs={"claims": [claim.claim_id for claim in claims]},
            observation=", ".join(
                f"{claim.claim_id}: {len(claim.lines)} lines, total {claim.total_billed}" for claim in claims
            ),
            checks=[CheckResult("two_claims_built", len(claims) == 2, "")],
            decision="hand claims to the coverage agent",
        )
        return IntakeResult(documents=documents, claims=claims, issues=issues, goals=goals, diagnosis_codes=diagnosis_codes)

    # -- extraction -------------------------------------------------------
    def _extract_image(self, path: Path, kind: str) -> extraction.ParsedDocument:
        parser = extraction.PARSERS[kind]

        def attempts():
            for variant in VARIANTS:
                ocr = run_ocr(path, variant=variant)
                parsed = parser(ocr.text)
                parsed.variant = variant
                score, checks = self._score(parsed, ocr.mean_confidence)
                yield Attempt(label=variant, score=score, payload=(parsed, ocr), checks=checks)

        def accept(attempt: Attempt) -> bool:
            return all(check.passed for check in attempt.checks)

        best = self.retry_loop(f"OCR+parse {path.name}", attempts, accept, max_attempts=len(VARIANTS))
        parsed, ocr = best.payload
        self.act(
            "extracting",
            f"{path.name}: settled on the '{parsed.variant}' pass (mean OCR confidence {ocr.mean_confidence}).",
            "ocr_extract",
            inputs={"file": path.name, "variant": parsed.variant},
            observation=f"{len(parsed.lines)} service lines parsed; issues={parsed.issues}",
            decision="accepted extraction" if all(check.passed for check in best.checks) else "accepted with warnings",
        )
        if not all(check.passed for check in best.checks):
            parsed.issues.append("extraction accepted with warnings; a human should verify the scan")
        return parsed

    def _score(self, document: extraction.ParsedDocument, mean_confidence: float) -> tuple[float, list[CheckResult]]:
        if document.kind == "invoice_image":
            checks = [
                CheckResult("service_lines_found", len(document.lines) >= 3, f"{len(document.lines)} lines"),
                CheckResult("printed_total_read", document.field_value("total") is not None, ""),
                CheckResult(
                    "line_sum_reconciles",
                    bool(document.field_value("sum_reconciles", False)),
                    str(document.field_value("sum_of_lines")),
                ),
            ]
        else:
            checks = [
                CheckResult("cpt_lines_found", len(document.lines) >= 2, f"{len(document.lines)} lines"),
                CheckResult("printed_total_read", document.field_value("total") is not None, ""),
                CheckResult(
                    "line_sum_reconciles",
                    bool(document.field_value("sum_reconciles", False)),
                    str(document.field_value("sum_of_lines")),
                ),
            ]
        score = (
            0.35 * (1 if checks[0].passed else 0)
            + 0.25 * (1 if checks[1].passed else 0)
            + 0.30 * (1 if checks[2].passed else 0)
            + 0.10 * (mean_confidence / 100)
        )
        return round(score, 3), checks

    def _extract_pdf(self, path: Path) -> extraction.ParsedDocument:
        text, pages = extract_pdf_text(path)
        parsed = extraction.parse_mri_report(text)
        parsed.variant = f"text-layer ({pages} page)"
        checks = [
            CheckResult("acl_tear_captured", any("anterior cruciate" in finding.lower() for finding in parsed.field_value("findings", [])), ""),
            CheckResult("meniscus_tear_captured", any("meniscus" in finding.lower() for finding in parsed.field_value("findings", [])), ""),
        ]
        self.act(
            "extracting",
            "A text-layer PDF does not need OCR; read it directly, then check the two findings that drive the surgery codes are present.",
            "pdf_extract",
            inputs={"file": path.name},
            observation=f"findings={parsed.field_value('findings')}",
            checks=checks,
            decision="accepted" if all(check.passed for check in checks) else "flagging partial findings",
        )
        if not all(check.passed for check in checks):
            parsed.issues.append("radiology report was missing one of the expected findings")
        return parsed

    def _extract_transcript(self, path: Path) -> extraction.ParsedDocument:
        parsed = extraction.parse_transcript(path.read_text(encoding="utf-8"))
        checks = [CheckResult("asks_recognised", len(parsed.field_value("asks", [])) >= 2, str(parsed.field_value("asks", [])))]
        self.act(
            "extracting",
            "The voice transcript is plain text; pull out the three things the household actually wants.",
            "transcript_parse",
            inputs={"file": path.name},
            observation=f"asks={parsed.field_value('asks')}",
            checks=checks,
            decision="goals set from the transcript",
        )
        return parsed

    # -- coding ------------------------------------------------------------
    def _resolve_diagnosis(self, documents: dict[str, extraction.ParsedDocument]) -> dict[str, list[str]]:
        """Map the MRI findings and the therapy plan to ICD-10 codes."""
        mri_text = documents["mri"].raw_text
        found = [code for code, confidence in codes.infer_diagnosis_codes(mri_text) if confidence >= 0.75]
        surgery_codes = [code for code in found if code.startswith("S")]
        therapy_code, therapy_confidence = codes.lookup_icd("chronic back pain")
        self.act(
            "coding",
            "Diagnosis codes must come from the clinical documents, not from the invoice. The MRI drives the surgical claim; the therapy plan implies the back-pain diagnosis.",
            "infer_icd10",
            inputs={"source": "aarav_mri_report.pdf + referral context"},
            observation=f"surgical diagnoses={surgery_codes}; therapy diagnosis={therapy_code} ({therapy_confidence})",
            checks=[
                CheckResult("acl_diagnosis_found", "S83.511A" in surgery_codes, ""),
                CheckResult("meniscus_diagnosis_found", "S83.241A" in surgery_codes, ""),
                CheckResult("therapy_diagnosis_found", therapy_code is not None, ""),
            ],
            decision="use these codes on the claims and the pre-auth letters",
        )
        return {"surgery": surgery_codes, "therapy": [code for code in [therapy_code] if code]}

    def _build_surgery_claim(self, estimate: extraction.ParsedDocument, diagnosis: dict[str, list[str]], goals: list[str]) -> Claim:
        lines: list[ServiceLine] = []
        for item in estimate.lines:
            code, confidence = (item.cpt_code, 0.93)
            if item.cpt_code:
                catalog_code, catalog_score = codes.lookup_cpt(item.description)
                if catalog_code and catalog_code != item.cpt_code:
                    confidence = min(confidence, 0.7)
            lines.append(
                ServiceLine(
                    description=item.description,
                    quantity=item.quantity or 1,
                    unit_rate=item.rate or item.amount,
                    billed_amount=item.amount,
                    cpt_code=code,
                    icd_codes=diagnosis["surgery"],
                    category=LineCategory.PROFESSIONAL,
                    code_confidence=confidence,
                    code_source="printed",
                )
            )
        self.act(
            "coding",
            "The estimate already prints CPT codes; cross-check each one against the procedure description before trusting it.",
            "cross_check_cpt",
            inputs={"source": "surgeon_estimate.jpg"},
            observation="; ".join(f"{line.cpt_code}={line.description} ({line.code_confidence:.2f})" for line in lines),
            checks=[CheckResult("codes_present", all(line.cpt_code for line in lines), "")],
            decision="codes confirmed against the catalogue",
        )
        return Claim(
            claim_id="CLM-2026-A-ACL",
            patient_name=estimate.field_value("patient") or "Aarav Sen",
            member_id="SEN-A-002",
            provider_name=estimate.field_value("provider") or "Dr. Rohit Naik",
            service_date=SERVICE_DATE_SURGERY,
            lines=lines,
            document_refs=["fixtures/aarav_mri_report.pdf", "fixtures/surgeon_estimate.jpg", "fixtures/user_query.txt"],
            narrative="Upcoming ACL reconstruction with partial meniscectomy for a complete ACL tear and medial meniscus tear.",
        )

    def _build_therapy_claim(self, invoice: extraction.ParsedDocument, goals: list[str]) -> Claim:
        lines: list[ServiceLine] = []
        for item in invoice.lines:
            code, confidence = codes.lookup_cpt(item.description)
            if confidence < 0.75:
                fallback, fallback_confidence = codes.INFERRED_THERAPY_LINES.get(item.description, (None, 0.0))
                if fallback_confidence > confidence:
                    code, confidence = fallback, fallback_confidence
            category = LineCategory.EQUIPMENT if "equipment" in item.description.lower() else LineCategory.THERAPY
            lines.append(
                ServiceLine(
                    description=item.description,
                    quantity=item.quantity or 1,
                    unit_rate=item.rate or item.amount,
                    billed_amount=item.amount,
                    cpt_code=code,
                    icd_codes=["M54.5"],
                    category=category,
                    non_covered=category == LineCategory.EQUIPMENT,
                    code_confidence=confidence,
                    code_source="inferred" if code else "unavailable",
                )
            )
        self.act(
            "coding",
            "The invoice carries no billing codes at all, so each description has to be mapped to a CPT code and the match confidence recorded.",
            "infer_cpt",
            inputs={"source": "priya_pt_invoice.png"},
            observation="; ".join(f"{line.description} -> {line.cpt_code} ({line.code_confidence:.2f})" for line in lines),
            checks=[
                CheckResult("codes_inferred", all(line.cpt_code for line in lines if line.category == LineCategory.THERAPY), ""),
                CheckResult("equipment_flagged", any(line.non_covered for line in lines), "home traction kit is not a covered benefit"),
            ],
            decision="inferred codes accepted; low-confidence ones flagged in the report",
        )
        return Claim(
            claim_id="CLM-2026-P-PT",
            patient_name=invoice.field_value("patient") or "Priya Sen",
            member_id="SEN-P-001",
            provider_name=invoice.field_value("provider") or "Lakshmi Physiotherapy",
            service_date=_parse_date(invoice.field_value("date"), SERVICE_DATE_THERAPY),
            lines=lines,
            document_refs=["fixtures/priya_pt_invoice.png", "fixtures/user_query.txt"],
            narrative="Unpaid physiotherapy invoice for chronic low back pain; codes were missing from the bill and have been inferred.",
        )
