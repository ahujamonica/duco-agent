"""Turn the four mock documents into structured fields.

Every field carries a confidence and the reason it is trusted (``ocr``,
``derived``, ``inferred`` or ``cross-checked``). The intake agent uses those
values to decide whether to accept an extraction or retry with another OCR
variant. Parsing is intentionally tolerant: scans are noisy, quantities are
sometimes unreadable, and the invoice does not print billing codes at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from .models import money

MONEY_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{2,3})+(?:\.\d{2})?|\d+\.\d{2})(?![\d.])")
CODE_RE = re.compile(r"\bCPT\s*([0-9O]{5})\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
SERVICE_WORDS = (
    "therapy",
    "exercise",
    "evaluation",
    "traction",
    "reconstruction",
    "meniscectomy",
    "arthroscopy",
    "ultrasound",
)


@dataclass
class Field:
    value: Any
    confidence: float
    source: str
    note: str = ""

    def to_dict(self) -> dict:
        value = self.value
        if isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, list):
            value = [str(item) if isinstance(item, Decimal) else item for item in value]
        return {"value": value, "confidence": self.confidence, "source": self.source, "note": self.note}


@dataclass
class ParsedLine:
    description: str
    amount: Decimal
    rate: Optional[Decimal] = None
    quantity: Optional[int] = None
    cpt_code: Optional[str] = None
    confidence: float = 0.0
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "amount": str(self.amount),
            "rate": str(self.rate) if self.rate is not None else None,
            "quantity": self.quantity,
            "cpt_code": self.cpt_code,
            "confidence": self.confidence,
            "issues": self.issues,
        }


@dataclass
class ParsedDocument:
    kind: str
    path: str
    fields: dict[str, Field] = field(default_factory=dict)
    lines: list[ParsedLine] = field(default_factory=list)
    raw_text: str = ""
    variant: str = ""
    issues: list[str] = field(default_factory=list)

    def field_value(self, name: str, default: Any = None) -> Any:
        found = self.fields.get(name)
        return found.value if found else default

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": self.path,
            "variant": self.variant,
            "fields": {key: value.to_dict() for key, value in self.fields.items()},
            "lines": [line.to_dict() for line in self.lines],
            "issues": self.issues,
        }


def _money_tokens(line: str) -> list[Decimal]:
    return [money(token.replace(",", "")) for token in MONEY_RE.findall(line)]


def _clean_description(text: str) -> str:
    text = re.sub(r"^\s*(?:\d{1,2}[\).:]?|sr\.?)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip(" -|:;,.")
    # Drop stray single characters produced by noise around the table columns.
    tokens = [token for token in text.split(" ") if len(token) > 1 or not token.isalnum()]
    # Trailing OCR crumbs ("al", "a,", "12") sit after the description.
    while tokens and re.fullmatch(r"[A-Za-z0-9]{1,2}[.,)\]]?", tokens[-1]):
        tokens.pop()
    return " ".join(tokens).strip()


def parse_invoice(text: str) -> ParsedDocument:
    """Parse the scanned physiotherapy invoice."""
    document = ParsedDocument(kind="invoice_image", path="fixtures/priya_pt_invoice.png", raw_text=text)

    header = " ".join(text.splitlines()[:3])
    provider = "Lakshmi Physiotherapy" if "physiotherapy" in text.lower() else "unknown"
    document.fields["provider"] = Field(provider, 0.95 if provider != "unknown" else 0.4, "ocr")

    invoice_no = re.search(r"INVOICE\s*No[:\s]*([A-Z0-9/]+)", text, re.IGNORECASE)
    document.fields["invoice_no"] = Field(
        invoice_no.group(1) if invoice_no else None, 0.9 if invoice_no else 0.0, "ocr"
    )

    date_match = DATE_RE.search(text)
    document.fields["date"] = Field(date_match.group(1) if date_match else None, 0.85 if date_match else 0.0, "ocr")

    patient = re.search(r"Patient[:\s]*([A-Za-z]+(?:\s+[A-Za-z]+)?)", text)
    patient_name = patient.group(1).strip() if patient else None
    if patient_name:
        patient_name = re.sub(r"\s+(Age|Sex|M\/F).*$", "", patient_name).strip()
    document.fields["patient"] = Field(patient_name, 0.9 if patient_name else 0.0, "ocr")

    total: Optional[Decimal] = None
    for line in text.splitlines():
        if re.search(r"total", line, re.IGNORECASE) and not re.search(r"sub\s*total", line, re.IGNORECASE):
            tokens = _money_tokens(line)
            if tokens:
                total = tokens[-1]
    document.fields["total"] = Field(total, 0.95 if total is not None else 0.0, "ocr")

    for line in text.splitlines():
        if "total" in line.lower():
            continue
        tokens = _money_tokens(line)
        if len(tokens) < 2:
            continue
        description = _clean_description(line[: line.find(MONEY_RE.search(line).group(0))])
        if not description or not any(word in description.lower() for word in SERVICE_WORDS):
            continue
        amount = tokens[-1]
        rate = tokens[-2]
        parsed = ParsedLine(description=description, amount=amount, rate=rate)
        if rate and amount and amount % rate == 0:
            parsed.quantity = int(amount / rate)
        else:
            parsed.issues.append("quantity not legible on the scan")
            parsed.quantity = None
        parsed.confidence = 0.9 if parsed.quantity else 0.72
        document.lines.append(parsed)

    if total is not None and document.lines:
        summed = sum((line.amount for line in document.lines), money(0))
        document.fields["sum_of_lines"] = Field(summed, 0.95, "derived")
        document.fields["sum_reconciles"] = Field(
            summed == total, 0.95, "cross-checked", f"line sum {summed} vs printed total {total}"
        )
        if summed != total:
            document.issues.append(f"line sum {summed} does not match printed total {total}")
    if not document.lines:
        document.issues.append("no service lines could be parsed")
    return document


def parse_estimate(text: str) -> ParsedDocument:
    """Parse the surgeon's billing sheet photo."""
    document = ParsedDocument(kind="estimate_image", path="fixtures/surgeon_estimate.jpg", raw_text=text)

    provider = "Dr. Rohit Naik" if "ROHIT NAIK" in text.upper() else "unknown"
    document.fields["provider"] = Field(provider, 0.95 if provider != "unknown" else 0.4, "ocr")

    patient = re.search(r"Patient[:\s]*([A-Za-z]+(?:\s+[A-Za-z]+)?)", text)
    document.fields["patient"] = Field(patient.group(1).strip() if patient else None, 0.9 if patient else 0.0, "ocr")

    total = None
    for line in text.splitlines():
        if re.search(r"\btotal\b", line, re.IGNORECASE):
            tokens = _money_tokens(line)
            if tokens:
                total = tokens[-1]
    document.fields["total"] = Field(total, 0.95 if total is not None else 0.0, "ocr")

    for line in text.splitlines():
        code_match = CODE_RE.search(line)
        tokens = _money_tokens(line)
        if not code_match or not tokens:
            continue
        code = code_match.group(1).replace("O", "0")
        description = line[code_match.end(): line.rfind(MONEY_RE.findall(line)[-1])]
        document.lines.append(
            ParsedLine(description=_clean_description(description), amount=tokens[-1], cpt_code=code, confidence=0.93)
        )

    if total is not None and document.lines:
        summed = sum((line.amount for line in document.lines), money(0))
        document.fields["sum_of_lines"] = Field(summed, 0.95, "derived")
        document.fields["sum_reconciles"] = Field(summed == total, 0.95, "cross-checked")
        if summed != total:
            document.issues.append(f"estimate lines sum to {summed}, printed total is {total}")
    if not document.lines:
        document.issues.append("no CPT line items could be parsed from the estimate")
    return document


def parse_mri_report(text: str) -> ParsedDocument:
    """Parse the radiology report into clinical findings."""
    document = ParsedDocument(kind="radiology_pdf", path="fixtures/aarav_mri_report.pdf", raw_text=text)
    lowered = text.lower()

    patient = re.search(r"Patient:\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)", text)
    document.fields["patient"] = Field(patient.group(1).strip() if patient else None, 0.95 if patient else 0.0, "text")

    findings: list[str] = []
    if re.search(r"complete tear of the anterior cruciate ligament", lowered):
        findings.append("Complete tear of the anterior cruciate ligament (ACL)")
    if re.search(r"tear of the medial meniscus|complex tear of the medial meniscus", lowered):
        findings.append("Tear of the medial meniscus")
    if "effusion" in lowered:
        findings.append("Joint effusion")

    document.fields["findings"] = Field(findings, 0.92 if len(findings) >= 2 else 0.6, "text")
    document.fields["side"] = Field("right" if "right knee" in lowered else "unknown", 0.9, "text")
    document.fields["age_sex"] = Field(
        (re.search(r"Age/Sex:\s*([0-9]{1,3}\s*/\s*[MF])", text).group(1) if re.search(r"Age/Sex:\s*([0-9]{1,3}\s*/\s*[MF])", text) else None),
        0.9,
        "text",
    )
    if len(findings) < 2:
        document.issues.append("radiology findings were only partially recognised")
    return document


def parse_transcript(text: str) -> ParsedDocument:
    """Parse Aarav's voice-to-text request for the goals it implies."""
    document = ParsedDocument(kind="transcript", path="fixtures/user_query.txt", raw_text=text)
    lowered = text.lower()

    asks = []
    if "which plan pays first" in lowered or "pays first" in lowered:
        asks.append("coordination_order")
    if "out of our own pocket" in lowered or "out of pocket" in lowered:
        asks.append("out_of_pocket")
    if "pre-auth" in lowered or "pre auth" in lowered or "preauthor" in lowered:
        asks.append("preauth_letters")
    if "surgery" in lowered:
        asks.append("surgery_estimate")

    document.fields["asks"] = Field(asks, 0.95 if asks else 0.3, "text")
    document.fields["plans_mentioned"] = Field(
        sorted(set(re.findall(r"plan\s*([ab])", lowered))), 0.9, "text"
    )
    document.fields["patients"] = Field(
        [name for name in ("Aarav", "Priya") if name.lower() in lowered], 0.9, "text"
    )
    return document


PARSERS = {
    "invoice_image": parse_invoice,
    "estimate_image": parse_estimate,
    "radiology_pdf": parse_mri_report,
    "transcript": parse_transcript,
}
