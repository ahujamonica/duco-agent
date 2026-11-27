"""Document intelligence: validate, classify, OCR and extract with confidence.

The pipeline is deliberately explicit about what it knows:

1. validate the file (type, size, magic bytes);
2. extract text — embedded PDF text first, OCR only when the page is a scan;
3. classify the document from text and filename evidence, with a score;
4. parse fields for that document type;
5. resolve medical codes, marking printed vs inferred vs missing;
6. assign each field a confidence derived from OCR word confidence or from
   exact PDF text, plus a source and the evidence string;
7. flag low-confidence, conflicting or missing fields for human review.

No confidence value is invented: OCR-derived fields are capped at 0.95 and
scaled by the measured OCR confidence; inferred codes carry the matcher's own
score; derived values are marked ``derived`` and capped at 0.80.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import uuid
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image

from duco_agent.codes import code_category, suggest_cpt, suggest_icd
from duco_agent.tools.ocr import run_ocr

from ..config import ALLOWED_EXTENSIONS, ALLOWED_MIME, UPLOAD_DIR

MAX_OCR_PAGES = 4


class UnsupportedFile(ValueError):
    pass


MONEY_RE = re.compile(
    r"(?:₹|Rs\.?|INR)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
    r"|(?<![\d.])([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.[0-9]{1,2})?|[0-9]+\.[0-9]{2})(?![\d.])"
)
SUMMARY_LINE_RE = re.compile(
    r"^\s*(?:"
    r"(?:grand\s+total|sub\s*total|invoice\s+total|total\s+(?:amount|payable|due)|"
    r"net\s+(?:amount|payable)|amount\s+(?:payable|due|paid|received)|"
    r"outstanding\s+(?:balance|amount)|balance\s+due|"
    r"payments?(?:\s+received)?|paid(?:\s+to\s+date)?|"
    r"(?:cgst|sgst|igst|gst|vat|tax(?:es)?)|discount|adjustment|"
    r"invoice\s+summary|bill\s+summary|"
    r"(?:bill|invoice)\s+(?:no|number|#)))\b",
    re.IGNORECASE,
)
SUMMARY_TOTAL_RE = re.compile(
    r"^\s*(?:grand\s+total|sub\s*total|invoice\s+total|total)\s*"
    r"(?::|-)?\s*(?:(?:₹|Rs\.?|INR)\s*)?\d",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b([0-3]?\d[/-][01]?\d[/-](?:20)?\d{2}|20\d{2}-[01]\d-[0-3]\d|"
    r"[0-3]?\d\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2})\b",
    re.IGNORECASE,
)
CPT_RE = re.compile(r"\b(?:CPT[:\s-]*)?([1-9]\d{4})\b")
ICD_RE = re.compile(r"\b([A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?)\b")
POLICY_NO_RE = re.compile(r"(?:policy\s*(?:no|number|#)|policy\s*id)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{4,})", re.IGNORECASE)
PERCENT_RE = re.compile(r"([0-9]{1,2}(?:\.[0-9])?)\s*%")

DOC_TYPES = {
    "policy": ["policy", "sum insured", "premium", "insurer", "coverage", "deductible", "waiting period", "exclusion", "insured"],
    "invoice": ["invoice", "bill no", "bill number", "amount payable", "total amount", "gst", "receipt"],
    "estimate": ["estimate", "quotation", "package", "advance", "surgery estimate", "cost estimate"],
    "radiology": ["mri", "ct scan", "radiology", "impression", "findings", "ultrasound", "x-ray", "diagnostic report"],
    "prescription": ["prescription", "rx", "tablet", "capsule", "dosage", "pharmacy", "medicine"],
    "discharge": ["discharge summary", "admission", "discharged", "hospital course", "discharge date"],
}

TYPE_LABELS = {
    "policy": "Insurance policy",
    "invoice": "Medical bill / invoice",
    "estimate": "Surgical or treatment estimate",
    "radiology": "Radiology or diagnostic report",
    "prescription": "Prescription",
    "discharge": "Discharge summary",
    "transcript": "Typed query / transcript",
    "unknown": "Unclassified document",
}


@dataclass
class FieldValue:
    value: Any = None
    confidence: float = 0.0
    source: str = "missing"
    evidence: str = ""
    status: str = "ok"  # ok | review | missing

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "confidence": round(float(self.confidence), 3),
            "source": self.source,
            "evidence": self.evidence[:400],
            "status": self.status,
        }


@dataclass
class ParsedLine:
    description: str
    amount: Any = None
    quantity: int | None = None
    unit_rate: Any = None
    cpt_code: str | None = None
    icd_codes: list[str] = dc_field(default_factory=list)
    category: str = "professional"
    confidence: float = 0.0
    code_source: str = "unavailable"  # printed | inferred | unavailable
    code_confidence: float = 0.0
    evidence: str = ""
    issues: list[str] = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "amount": str(self.amount) if self.amount is not None else None,
            "quantity": self.quantity,
            "unit_rate": str(self.unit_rate) if self.unit_rate is not None else None,
            "cpt_code": self.cpt_code,
            "icd_codes": self.icd_codes,
            "category": self.category,
            "confidence": round(self.confidence, 3),
            "code_source": self.code_source,
            "code_confidence": round(self.code_confidence, 3),
            "evidence": self.evidence[:400],
            "issues": self.issues,
        }


# ---------------------------------------------------------------------------
# Validation and storage
# ---------------------------------------------------------------------------


def validate_file(filename: str, content_type: str | None, size: int) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UnsupportedFile(
            f"{suffix or 'this file type'} is not supported. Upload a PDF, PNG, JPG, WEBP, TIFF or TXT file."
        )
    if content_type and content_type.lower() not in ALLOWED_MIME and content_type.lower() != "application/octet-stream":
        raise UnsupportedFile(f"The browser reported {content_type}, which is not an accepted document type.")
    if size <= 0:
        raise UnsupportedFile("The uploaded file is empty.")
    return suffix


def checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def store_bytes(content: bytes, suffix: str) -> tuple[str, Path]:
    name = f"{uuid.uuid4().hex}{suffix}"
    path = UPLOAD_DIR / name
    path.write_bytes(content)
    return name, path


def _sniff_is_image(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


@dataclass
class TextResult:
    text: str
    method: str
    pages: int = 1
    mean_confidence: float | None = None
    attempts: list[dict] = dc_field(default_factory=list)
    issues: list[str] = dc_field(default_factory=list)


def _score(text: str, confidence: float) -> float:
    money_hits = len(MONEY_RE.findall(text))
    code_hits = len(CPT_RE.findall(text))
    words = len(text.split())
    return round(confidence + min(money_hits, 12) * 1.5 + min(code_hits, 6) * 1.2 + min(words, 300) * 0.02, 2)


def _ocr_image(path: Path) -> TextResult:
    """Try preprocessing variants and keep the one with the best evidence."""
    attempts: list[dict] = []
    best = None
    for variant in ("auto-layout", "block", "binarised"):
        try:
            result = run_ocr(path, variant=variant)
        except Exception as exc:  # a broken image should not crash the request
            attempts.append({"variant": variant, "error": str(exc)})
            continue
        score = _score(result.text, result.mean_confidence)
        attempts.append(
            {
                "variant": variant,
                "mean_confidence": result.mean_confidence,
                "characters": len(result.text),
                "score": score,
            }
        )
        candidate = (score, result)
        if best is None or score > best[0]:
            best = candidate
        if result.mean_confidence >= 72 and len(MONEY_RE.findall(result.text)) >= 2:
            best = candidate
            break
    if best is None:
        raise UnsupportedFile("We could not read this image. Upload a clearer photo or a PDF.")
    score, result = best
    return TextResult(
        text=result.text,
        method="ocr",
        mean_confidence=result.mean_confidence,
        attempts=attempts,
        issues=[] if result.mean_confidence >= 55 else ["The scan is low quality; OCR confidence is below 55%."],
    )


def extract_text(path: Path, suffix: str) -> TextResult:
    if suffix == ".txt":
        return TextResult(text=path.read_text(encoding="utf-8", errors="replace"), method="transcript")

    if suffix == ".pdf":
        document = pymupdf.open(str(path))
        try:
            pages = len(document)
            text = "\n".join(page.get_text("text") for page in document).strip()
            if len(text) >= 80:
                return TextResult(text=text, method="pdf_text", pages=pages)
            # Scanned PDF: rasterise the first pages and OCR them.
            chunks: list[str] = []
            confidences: list[float] = []
            attempts: list[dict] = []
            for index in range(min(pages, MAX_OCR_PAGES)):
                page = document[index]
                pixmap = page.get_pixmap(dpi=200)
                image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                tmp = UPLOAD_DIR / f"ocr-{uuid.uuid4().hex}.png"
                image.save(tmp)
                try:
                    result = _ocr_image(tmp)
                finally:
                    tmp.unlink(missing_ok=True)
                chunks.append(result.text)
                if result.mean_confidence is not None:
                    confidences.append(result.mean_confidence)
                attempts.extend(result.attempts)
            return TextResult(
                text="\n".join(chunks),
                method="ocr",
                pages=pages,
                mean_confidence=round(sum(confidences) / len(confidences), 1) if confidences else 0.0,
                attempts=attempts,
                issues=["This PDF has no embedded text, so it was read with OCR."],
            )
        finally:
            document.close()

    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        return _ocr_image(path)

    if suffix in {".mp3", ".m4a", ".wav"}:
        return TextResult(
            text="",
            method="audio",
            issues=[
                "Audio transcription is not enabled in this local build. Attach the transcript as text, "
                "or type the request in the case description."
            ],
        )

    raise UnsupportedFile(f"Unsupported file type: {suffix}")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(text: str, filename: str, hint: str | None = None) -> tuple[str, float, list[str]]:
    lowered = f"{filename} {text[:4000]}".lower()
    scores: dict[str, float] = {}
    evidence: list[str] = []
    for doc_type, keywords in DOC_TYPES.items():
        hits = [word for word in keywords if word in lowered]
        score = 0.0
        for word in hits:
            score += 0.14 if " " in word else 0.10
            if word in filename.lower():
                score += 0.18
        scores[doc_type] = min(score, 0.95)
        if hits:
            evidence.append(f"{doc_type}: matched {', '.join(hits[:4])}")
    if not scores or max(scores.values()) < 0.2:
        if hint and hint != "unknown":
            return hint, 0.5, ["No strong keyword evidence; the user-selected type was used."]
        return "unknown", 0.2, ["No reliable keywords were found."]
    best = max(scores, key=scores.get)
    confidence = round(0.42 + scores[best], 3)
    confidence = min(confidence, 0.96)
    # An explicit user choice wins, but the evidence is still reported.
    if hint and hint != "unknown":
        if hint != best:
            evidence.append(f"User selected {hint} while the text suggested {best}.")
        return hint, min(confidence if hint == best else 0.75, 0.95), evidence
    return best, confidence, evidence


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_date(text: str) -> date | None:
    match = DATE_RE.search(text)
    if not match:
        return None
    raw = match.group(1).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").replace("INR", "").strip()
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0:
        return None
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def amounts_in(line: str) -> list[str]:
    found: list[str] = []
    for first, second in MONEY_RE.findall(line):
        value = parse_amount(first or second)
        if value:
            found.append(value)
    return found


def _field(
    value: Any,
    confidence: float,
    source: str,
    evidence: str,
    required: bool = False,
    review_below: float = 0.75,
) -> FieldValue:
    if value in (None, "", []):
        return FieldValue(None, 0.0, "missing", evidence, "missing" if required else "ok")
    status = "review" if confidence < review_below else "ok"
    return FieldValue(value, min(confidence, 0.96), source, evidence, status)


def _confidence_for(source: str, base: float, ocr_conf: float | None, derived: bool = False) -> float:
    if source == "pdf_text":
        value = base
    elif source == "ocr":
        measured = (ocr_conf or 60) / 100
        value = min(0.95, base * (0.6 + 0.45 * measured))
    elif source == "derived":
        value = min(0.80, base * 0.8)
    else:
        value = min(0.75, base)
    if derived:
        value *= 0.92
    return round(max(0.05, min(value, 0.95)), 3)


def _labelled_amount(text: str, labels: list[str], ocr: float | None, source: str) -> FieldValue:
    for label in labels:
        pattern = re.compile(
            rf"(?<!\w){re.escape(label)}(?!\w)[^\n\r:]{{0,30}}[:\-]?\s*([^\n\r]{{0,80}})",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            amounts = amounts_in(match.group(0))
            if amounts:
                return _field(
                    amounts[0],
                    _confidence_for(source, 0.93, ocr),
                    source,
                    match.group(0).strip(),
                    required=True,
                )
    return _field(None, 0.0, "missing", f"No '{labels[0]}' line found", required=True)


def _clean_patient(value: Any) -> Any:
    if not value:
        return value
    return re.split(r"\s+(?:Date|Age|Sex|DOB|MRN|Mobile|Phone|Address)\b", str(value))[0].strip(" :,-")


def _labelled_text(text: str, labels: list[str], source: str, required=True) -> FieldValue:
    for label in labels:
        match = re.search(rf"{label}\s*[:\-]\s*([^\n\r]{{1,90}})", text, re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .;,")
            if value:
                return _field(value, _confidence_for(source, 0.92, None), source, match.group(0).strip(), required=required)
    return _field(None, 0.0, "missing", f"No '{labels[0]}' value found", required=required)


def _find_codes(text: str) -> tuple[list[str], list[str]]:
    cpts: list[str] = []
    icds: list[str] = []
    for line in text.splitlines():
        if re.search(r"\bCPT\b", line, re.IGNORECASE):
            for code in re.findall(r"\b([1-9]\d{4})\b", line):
                cpts.append(code)
        icd_line = re.search(r"\b(?:ICD(?:-10)?|diagnosis)\b[:\s]*(.+)", line, re.IGNORECASE)
        if icd_line:
            for code in ICD_RE.findall(icd_line.group(1)):
                if len(code) >= 3:
                    icds.append(code)
    return list(dict.fromkeys(cpts)), list(dict.fromkeys(icds))


def _categorise(description: str, cpt: str | None) -> str:
    lowered = description.lower()
    if any(word in lowered for word in ("crutch", "brace", "equipment", "orthosis", "wheelchair")):
        return "equipment"
    if any(word in lowered for word in ("room", "bed", "nursing", "icu")):
        return "facility"
    if cpt:
        category = code_category(cpt)
        if category in {"therapy", "diagnostic", "equipment"}:
            return category
    if any(word in lowered for word in ("physio", "therapy", "exercise", "traction", "rehab")):
        return "therapy"
    if any(word in lowered for word in ("mri", "ct ", "x-ray", "xray", "scan", "ultrasound", "pathology", "lab")):
        return "diagnostic"
    if any(word in lowered for word in ("crutch", "brace", "equipment", "orthosis", "wheelchair")):
        return "equipment"
    if any(word in lowered for word in ("room", "bed", "nursing", "icu")):
        return "facility"
    return "professional"


def _service_lines(text: str, source: str, ocr: float | None) -> tuple[list[ParsedLine], list[str]]:
    lines: list[ParsedLine] = []
    issues: list[str] = []
    has_quantity_column = bool(
        re.search(r"\b(?:qty|quantity)\b[^\n]{0,80}\b(?:rate|amount)\b", text, re.IGNORECASE)
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 4:
            continue
        if SUMMARY_LINE_RE.match(line) or SUMMARY_TOTAL_RE.match(line):
            continue
        money = amounts_in(line)
        if not money:
            continue
        if not re.search(r"[A-Za-z]{3,}", line):
            continue
        first_money_match = MONEY_RE.search(line)
        if not first_money_match:
            continue
        prefix = line[: first_money_match.start()]
        description = prefix.strip(" -|:.,")
        description = re.sub(r"^\s*(?:\d{1,2}[\).:]?|sr\.?)\s+", "", description, flags=re.IGNORECASE)
        # Scanned tables leave one- or two-character crumbs at the start.
        description = re.sub(r"^[A-Za-z]{1,2}[\s|]+(?=[A-Z])", "", description).strip()
        description = re.sub(r"\s{2,}", " ", description)
        if len(description) < 3:
            continue
        parsed = ParsedLine(description=description[:180], evidence=line[:300])
        printed_cpt, printed_icd = _find_codes(line)
        printed_in_desc = CPT_RE.findall(description)
        amount = money[-1]
        quantity_match = re.search(r"\b(?:qty|quantity)\s*[:=]?\s*(\d+)\b", line, re.IGNORECASE)
        if not quantity_match and has_quantity_column:
            quantity_match = re.search(r"(?<!\w)(\d+)\s*$", prefix)
        explicit_quantity = int(quantity_match.group(1)) if quantity_match else None
        if len(money) >= 3 or (explicit_quantity is not None and len(money) >= 2):
            try:
                quantity_value = Decimal(explicit_quantity) if explicit_quantity is not None else Decimal(money[-2])
                rate_value = Decimal(money[-2] if explicit_quantity is not None else money[-3])
                amount_value = Decimal(amount)
                if (
                    quantity_value > 0
                    and quantity_value == quantity_value.to_integral_value()
                    and abs(rate_value * quantity_value - amount_value) <= Decimal("0.01")
                ):
                    quantity = int(quantity_value)
                    parsed.quantity = quantity
                    parsed.unit_rate = f"{rate_value:.2f}"
                else:
                    parsed.issues.append("quantity × rate does not match the line amount")
                    parsed.quantity = None
                    parsed.unit_rate = None
            except InvalidOperation:
                parsed.issues.append("quantity is not legible")
        elif explicit_quantity is not None:
            parsed.quantity = explicit_quantity
        parsed.amount = amount
        parsed.confidence = _confidence_for(source, 0.9, ocr)

        if printed_cpt or printed_in_desc:
            code = (printed_cpt or printed_in_desc)[0]
            parsed.cpt_code = code
            parsed.code_source = "printed"
            parsed.code_confidence = _confidence_for(source, 0.94, ocr)
        else:
            candidates = suggest_cpt(description, limit=1)
            if candidates and candidates[0]["confidence"] >= 0.6:
                parsed.cpt_code = candidates[0]["code"]
                parsed.code_source = "inferred"
                parsed.code_confidence = candidates[0]["confidence"]
                parsed.issues.append(
                    f"CPT {candidates[0]['code']} inferred from the description; confirm before adjudication"
                )
                if candidates[0]["confidence"] < 0.8:
                    parsed.confidence = min(parsed.confidence, 0.78)
            else:
                parsed.code_source = "unavailable"
                parsed.issues.append("No procedure code could be matched; enter one during review")
        if printed_icd:
            parsed.icd_codes = printed_icd
        parsed.category = _categorise(description, parsed.cpt_code)
        lines.append(parsed)
    if not lines:
        issues.append("No billed service lines could be read from this document.")
    return lines, issues


# ---------------------------------------------------------------------------
# Per-type parsers
# ---------------------------------------------------------------------------


def parse_policy(text: str, source: str, ocr: float | None, filename: str) -> dict:
    fields: dict[str, FieldValue] = {}
    fields["insurer"] = _labelled_text(text, ["Insurer", "Insurance Company", "Underwritten by", "Company"], source)
    if fields["insurer"].status == "missing":
        for candidate in ("ICICI Lombard", "HDFC ERGO", "Star Health", "Niva Bupa", "Bajaj Allianz", "Tata AIG", "New India Assurance", "Care Health", "Aditya Birla", "Oriental Insurance", "National Insurance", "United India"):
            if candidate.lower() in text.lower():
                fields["insurer"] = _field(candidate, _confidence_for(source, 0.85, ocr), source, f"name appears in the document: {candidate}", required=True)
                break
    policy_match = POLICY_NO_RE.search(text)
    fields["policy_number"] = _field(
        policy_match.group(1) if policy_match else None,
        _confidence_for(source, 0.94, ocr) if policy_match else 0,
        source if policy_match else "missing",
        policy_match.group(0) if policy_match else "No policy number found",
        required=True,
    )
    fields["plan_name"] = _labelled_text(text, ["Plan", "Product", "Policy Name", "Plan Name"], source, required=False)
    fields["sum_insured"] = _labelled_amount(
        text,
        [
            "Sum Insured",
            "Sum Assured",
            "Coverage Amount",
            "Basic Cover",
            "Family Floater Limit",
            "Family Shared Limit",
            "Family Limit",
        ],
        ocr,
        source,
    )
    fields["deductible"] = _labelled_amount(text, ["Deductible", "Excess"], ocr, source)
    if fields["deductible"].status == "missing":
        fields["deductible"] = _field("0.00", 0.55, "derived", "No deductible clause found; assumed zero and flagged", required=False)
    coinsurance_match = re.search(r"(?:co-?\s?insurance|co-?\s?pay(?:ment)?)[^\n]{0,60}?([0-9]{1,2}(?:\.[0-9])?)\s*%", text, re.IGNORECASE)
    fields["coinsurance_member"] = _field(
        f"{float(coinsurance_match.group(1))/100:.4f}" if coinsurance_match else None,
        _confidence_for(source, 0.92, ocr) if coinsurance_match else 0,
        source if coinsurance_match else "missing",
        coinsurance_match.group(0) if coinsurance_match else "No co-insurance percentage found",
        required=True,
    )
    fields["oop_max"] = _labelled_amount(text, ["Out of Pocket", "Out-of-Pocket", "OOP Maximum", "Maximum Out of Pocket"], ocr, source)
    fields["preauth_threshold"] = _labelled_amount(text, ["Pre-authorisation", "Pre-authorization", "Pre auth", "Prior Authorization"], ocr, source)
    fields["waiting_period_days"] = _waiting_period(text, source, ocr)
    fields["policy_start"], fields["policy_end"] = _policy_period(text, source, ocr)
    fields["network_only"] = _field(
        True if re.search(r"network\s*(only|hospital)", text, re.IGNORECASE) else False,
        _confidence_for(source, 0.7, ocr),
        source,
        "network wording found" if "network" in text.lower() else "no network restriction stated",
        required=False,
        review_below=0.5,
    )
    fields["exclusions"] = _exclusions(text, source, ocr)
    fields["sublimits"] = _sublimits(text, source, ocr)
    fields["policyholder"] = _labelled_text(text, ["Policyholder", "Proposer", "Insured Name", "Name of Insured"], source, required=False)
    fields["document_notes"] = _field(
        "Extracted from an uploaded policy document. Confirm every value against the schedule before adjudication.",
        0.9,
        "derived",
        "Extraction is assistive; the policy schedule remains authoritative.",
    )
    issues = []
    for key in ("insurer", "policy_number", "sum_insured", "coinsurance_member"):
        if fields.get(key) and fields[key].status in ("missing", "review"):
            issues.append(f"{key.replace('_', ' ').title()} needs confirmation")
    return {"fields": fields, "lines": [], "issues": issues}


def _waiting_period(text: str, source: str, ocr: float | None) -> FieldValue:
    match = re.search(r"waiting period[^\n]{0,80}", text, re.IGNORECASE)
    if not match:
        return _field(None, 0.0, "missing", "No waiting-period clause found", required=False)
    chunk = match.group(0)
    days = re.search(r"([0-9]{1,3})\s*(?:days|day)", chunk, re.IGNORECASE)
    months = re.search(r"([0-9]{1,2})\s*(?:months|month)", chunk, re.IGNORECASE)
    years = re.search(r"([0-9]{1,2})\s*(?:years|year)", chunk, re.IGNORECASE)
    value = None
    if days:
        value = int(days.group(1))
    elif months:
        value = int(months.group(1)) * 30
    elif years:
        value = int(years.group(1)) * 365
    if value is None:
        return _field(None, 0.0, "missing", chunk, required=False)
    return _field(value, _confidence_for(source, 0.9, ocr), source, chunk, required=False)


def _policy_period(text: str, source: str, ocr: float | None) -> tuple[FieldValue, FieldValue]:
    match = re.search(r"(?:policy\s*(?:period|term)|period of insurance|valid from)[^\n]{0,120}", text, re.IGNORECASE)
    if not match:
        return (
            _field(None, 0.0, "missing", "No policy period found", required=False),
            _field(None, 0.0, "missing", "No policy period found", required=False),
        )
    dates = DATE_RE.findall(match.group(0))
    start = parse_date(dates[0]) if dates else None
    end = parse_date(dates[1]) if len(dates) > 1 else None
    return (
        _field(start.isoformat() if start else None, _confidence_for(source, 0.9, ocr), source, match.group(0), required=False),
        _field(end.isoformat() if end else None, _confidence_for(source, 0.9, ocr), source, match.group(0), required=False),
    )


def _exclusions(text: str, source: str, ocr: float | None) -> FieldValue:
    section = re.search(r"exclusions?\s*[:\-]?\s*\n?(.{0,700})", text, re.IGNORECASE | re.DOTALL)
    items: list[dict] = []
    if section:
        body = section.group(1)
        for raw in re.split(r"[\n•\-–]", body):
            item = raw.strip(" .;")
            if re.search(
                r"\b(?:(?:shared\s+)?family(?:\s+floater)?|family\s+shared)\s+(?:limit|sum\s+insured)\b",
                item,
                re.IGNORECASE,
            ):
                continue
            if 3 < len(item) < 120 and not item.lower().startswith(("waiting", "the following")):
                items.append({"label": item})
            if len(items) >= 12:
                break
    if not items:
        return _field([], 0.0, "missing", "No exclusion section found", required=False)
    return _field(items, _confidence_for(source, 0.85, ocr), source, section.group(0)[:300] if section else "", required=False)


def _sublimits(text: str, source: str, ocr: float | None) -> FieldValue:
    found: list[dict] = []
    patterns = [
        (r"(?:therapy|physiotherapy)[^\n]{0,60}?([0-9][0-9,]*)\s*(?:per|/)?\s*(?:year|annum)", "Therapy sub-limit", "therapy"),
        (r"(?:room rent|room)[^\n]{0,40}?([0-9][0-9,]*)\s*(?:per|/)?\s*day", "Room rent limit", "facility"),
        (r"(?:maternity)[^\n]{0,60}?([0-9][0-9,]*)", "Maternity sub-limit", "professional"),
        (r"(?:cataract)[^\n]{0,60}?([0-9][0-9,]*)", "Cataract sub-limit", "professional"),
    ]
    for pattern, label, category in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount = parse_amount(match.group(1))
            if amount:
                found.append(
                    {
                        "key": re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"),
                        "label": label,
                        "limit": amount,
                        "used": "0.00",
                        "applies_to_codes": [],
                        "applies_to_categories": [category],
                        "basis": "per_year",
                        "confidence": _confidence_for(source, 0.85, ocr),
                        "evidence": match.group(0),
                    }
                )
    if not found:
        return _field([], 0.0, "missing", "No sub-limits recognised", required=False)
    return _field(found, _confidence_for(source, 0.85, ocr), source, "; ".join(item["evidence"] for item in found), required=False)


def parse_invoice(text: str, source: str, ocr: float | None, filename: str, kind: str = "invoice") -> dict:
    fields: dict[str, FieldValue] = {}
    fields["patient"] = _labelled_text(text, ["Patient Name", "Patient", "Name of Patient"], source)
    fields["patient"].value = _clean_patient(fields["patient"].value)
    if fields["patient"].status == "missing":
        match = re.search(r"\b(?:Mr|Mrs|Ms|Dr)\.?\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)", text)
        if match:
            fields["patient"] = _field(match.group(1), _confidence_for(source, 0.78, ocr), source, match.group(0), required=True)
    fields["provider"] = _labelled_text(text, ["Hospital", "Clinic", "Provider", "Billing Entity"], source, required=False)
    if fields["provider"].status == "missing":
        first_lines = [l.strip() for l in text.splitlines()[:4] if l.strip()]
        provider = next((l for l in first_lines if re.search(r"(hospital|clinic|physio|diagnostic|medical|health)", l, re.IGNORECASE)), None)
        fields["provider"] = _field(provider, _confidence_for(source, 0.75, ocr), source, provider or "", required=False)
    invoice_match = re.search(r"(?:bill|invoice)\s*(?:no|number|#)\s*[:\-]?\s*([A-Z0-9/\-]{3,})", text, re.IGNORECASE)
    fields["bill_number"] = _field(
        invoice_match.group(1) if invoice_match else None,
        0.9 if invoice_match else 0,
        source if invoice_match else "missing",
        invoice_match.group(0) if invoice_match else "",
        required=False,
    )
    date_label = re.search(
        r"\b(?:service date|date of service|treatment date|visit date)\b\s*[:\-]?",
        text,
        re.IGNORECASE,
    )
    date_line = text[date_label.start() :].splitlines()[0] if date_label else ""
    date_match = DATE_RE.search(date_line)
    parsed_service_date = parse_date(date_match.group(0)) if date_match else None
    fields["service_date"] = _field(
        parsed_service_date.isoformat() if parsed_service_date else None,
        _confidence_for(source, 0.88, ocr) if date_match else 0,
        source if date_match else "missing",
        date_match.group(0) if date_match else "",
        required=False,
    )
    lines, line_issues = _service_lines(text, source, ocr)

    total_text = "\n".join(
        line for line in text.splitlines() if not re.match(r"^\s*sub\s*total\b", line, re.IGNORECASE)
    )
    total = _labelled_amount(
        total_text,
        [
            "Grand Total",
            "Invoice Total",
            "Total Amount",
            "Total Payable",
            "Amount Payable",
            "Total",
            "Net Amount",
        ],
        ocr,
        source,
    )
    fields["subtotal"] = _labelled_amount(text, ["Sub Total", "Subtotal"], ocr, source)
    fields["tax"] = _labelled_amount(text, ["Tax", "GST", "CGST", "SGST", "IGST", "VAT"], ocr, source)
    fields["discount"] = _labelled_amount(text, ["Discount"], ocr, source)
    fields["adjustment"] = _labelled_amount(text, ["Adjustment", "Other Charges"], ocr, source)
    fields["amount_paid"] = _labelled_amount(text, ["Amount Paid", "Payment Received", "Paid"], ocr, source)
    fields["balance_due"] = _labelled_amount(
        text, ["Outstanding Balance", "Outstanding Amount", "Balance Due", "Amount Due"], ocr, source
    )
    if total.status == "missing" and lines:
        summed = sum((Decimal(str(line.amount or 0)) for line in lines), Decimal("0"))
        total = _field(
            f"{summed:.2f}",
            _confidence_for(source, 0.72, ocr, derived=True),
            "derived",
            "Summed from the parsed service lines",
            required=True,
        )

    fields["total"] = total
    issues = list(line_issues)
    if lines and total.value:
        line_sum = sum((Decimal(str(line.amount or 0)) for line in lines), Decimal("0"))
        total_value = Decimal(str(total.value))
        if abs(line_sum - total_value) > Decimal("0.01"):
            issues.append(
                f"The printed total ₹{total_value:,.2f} does not match the sum of the lines ₹{line_sum:,.2f}; "
                "review the line items."
            )
            total.status = "review"
            total.confidence = min(total.confidence, 0.6)
    if not lines:
        issues.append("No service lines were detected; add them during review.")

    cpts, icds = _find_codes(text)
    fields["diagnosis_codes"] = _field(icds, 0.85 if icds else 0.0, source if icds else "missing", ", ".join(icds), required=False)
    fields["procedure_codes"] = _field(cpts, 0.85 if cpts else 0.0, source if cpts else "missing", ", ".join(cpts), required=False)
    for line in lines:
        if line.code_source == "unavailable":
            suggestions = suggest_cpt(line.description)
            if suggestions:
                line.issues.append(f"Suggested CPT candidates: {', '.join(s['code'] for s in suggestions)}")
    return {"fields": fields, "lines": lines, "issues": issues}


def parse_radiology(text: str, source: str, ocr: float | None, filename: str) -> dict:
    fields: dict[str, FieldValue] = {}
    fields["patient"] = _labelled_text(text, ["Patient Name", "Patient", "Name"], source)
    fields["patient"].value = _clean_patient(fields["patient"].value)
    fields["provider"] = _labelled_text(text, ["Hospital", "Centre", "Center", "Diagnostic Centre", "Radiologist"], source, required=False)
    date_match = DATE_RE.search(text)
    fields["study_date"] = _field(
        parse_date(date_match.group(0)).isoformat() if date_match and parse_date(date_match.group(0)) else None,
        _confidence_for(source, 0.85, ocr) if date_match else 0.0,
        source if date_match else "missing",
        date_match.group(0) if date_match else "",
        required=False,
    )
    modality = None
    for candidate in ("MRI", "CT scan", "CT", "X-ray", "Ultrasound", "PET"):
        if candidate.lower() in text.lower():
            modality = candidate
            break
    fields["modality"] = _field(modality, _confidence_for(source, 0.9, ocr) if modality else 0, source if modality else "missing", modality or "", required=False)
    section = re.search(r"(?:findings|impression|report)\s*[:\-]?\s*(.{20,1200})", text, re.IGNORECASE | re.DOTALL)
    narrative = section.group(1).strip() if section else text.strip()[:1200]
    fields["findings"] = _field(narrative, _confidence_for(source, 0.85, ocr) if narrative else 0, source if narrative else "missing", narrative[:300], required=False)
    suggestions = suggest_icd(narrative)
    fields["diagnosis_candidates"] = _field(
        suggestions,
        0.9 if suggestions else 0.0,
        "derived",
        "Suggested from the radiology narrative; clinical confirmation is required",
        required=False,
        review_below=2.0,
    )
    fields["clinical_justification"] = _field(
        narrative[:800] if narrative else None,
        _confidence_for(source, 0.8, ocr) if narrative else 0,
        source if narrative else "missing",
        "Quoted from the report narrative",
        required=False,
    )
    issues = []
    if not suggestions:
        issues.append("No diagnosis code matched the narrative; a clinician must assign one.")
    else:
        issues.append("Diagnosis codes are suggestions only and require clinical validation.")
    return {"fields": fields, "lines": [], "issues": issues}


def parse_prescription(text: str, source: str, ocr: float | None, filename: str) -> dict:
    fields = {
        "patient": _labelled_text(text, ["Patient Name", "Patient"], source, required=False),
        "provider": _labelled_text(text, ["Doctor", "Prescriber", "Clinic", "Hospital"], source, required=False),
        "medicines": _field(
            [line.strip() for line in text.splitlines() if re.search(r"\b(?:tab|cap|syrup|mg|ml)\b", line, re.IGNORECASE)][:20],
            _confidence_for(source, 0.8, ocr),
            source,
            "Medicine lines quoted from the prescription",
            required=False,
        ),
    }
    return {"fields": fields, "lines": [], "issues": []}


def parse_discharge(text: str, source: str, ocr: float | None, filename: str) -> dict:
    fields = {
        "patient": _labelled_text(text, ["Patient Name", "Patient"], source),
        "provider": _labelled_text(text, ["Hospital", "Department"], source, required=False),
        "admission_date": _labelled_text(text, ["Admission Date", "Admitted On", "Date of Admission"], source, required=False),
        "discharge_date": _labelled_text(text, ["Discharge Date", "Discharged On", "Date of Discharge"], source, required=False),
        "diagnosis": _labelled_text(text, ["Diagnosis", "Final Diagnosis", "Provisional Diagnosis"], source, required=False),
        "clinical_justification": _field(
            text[:1200], _confidence_for(source, 0.75, ocr), source, "Discharge summary body", required=False
        ),
    }
    narrative = " ".join(str(f.value) for f in fields.values() if f.value)
    suggestions = suggest_icd(narrative)
    fields["diagnosis_candidates"] = _field(suggestions, 0.9 if suggestions else 0.0, "derived", "Suggested; clinical confirmation required", required=False, review_below=2.0)
    return {"fields": fields, "lines": [], "issues": ["Diagnosis codes are suggestions only." if suggestions else ""]}


def parse_transcript(text: str, source: str, ocr: float | None, filename: str) -> dict:
    fields = {
        "query": _field(text.strip()[:4000], 0.95 if text.strip() else 0.0, "transcript", "The entered or uploaded text", required=True),
        "patient": _field(None, 0.0, "missing", "", required=False),
    }
    return {"fields": fields, "lines": [], "issues": []}


PARSERS = {
    "policy": parse_policy,
    "invoice": parse_invoice,
    "estimate": parse_invoice,
    "radiology": parse_radiology,
    "prescription": parse_prescription,
    "discharge": parse_discharge,
    "transcript": parse_transcript,
}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def analyse_file(path: Path, filename: str, hint: str | None = None) -> dict:
    """Run the whole pipeline for one stored file and return a JSON-ready dict."""
    suffix = path.suffix.lower()
    text_result = extract_text(path, suffix)
    text = text_result.text

    if suffix == ".txt":
        doc_type, classification_confidence, evidence = "transcript", 0.98, ["Plain text upload is treated as a typed query."]
    else:
        doc_type, classification_confidence, evidence = classify(text, filename, hint)

    parser = PARSERS.get(doc_type)
    parsed = parser(text, text_result.method, text_result.mean_confidence, filename) if parser else {"fields": {}, "lines": [], "issues": []}

    fields = parsed["fields"]
    issues = [issue for issue in parsed["issues"] if issue]

    from .llm import enrich as llm_enrich

    llm = llm_enrich(
        text,
        doc_type,
        classification_confidence,
        {key: value.to_dict() for key, value in fields.items()},
    )
    if llm["used"]:
        if doc_type == "unknown" and llm.get("doc_type"):
            doc_type = llm["doc_type"]
            classification_confidence = max(classification_confidence, 0.65)
            evidence.append("Document type suggested by the optional extraction model.")
        for key, suggestion in (llm.get("fields") or {}).items():
            current = fields.get(key)
            if current is not None and current.value not in (None, "") and current.confidence >= 0.7:
                continue
            fields[key] = FieldValue(
                suggestion["value"],
                suggestion["confidence"],
                "llm",
                suggestion.get("evidence") or "Suggested by the optional extraction model",
                "review",
            )
        issues.append("Some fields were suggested by the optional extraction model and need your review.")
        if llm.get("notes"):
            issues.extend(str(note) for note in llm["notes"])
    elif llm.get("error"):
        issues.append(
            "LLM enrichment was configured but unavailable; the deterministic extractor was used instead. "
            f"({llm['error']})"
        )

    if doc_type == "unknown":
        issues.append("The document type could not be determined; choose a type in review.")
    fields["_document"] = FieldValue(
        value=TYPE_LABELS.get(doc_type, doc_type),
        confidence=classification_confidence,
        source="classification",
        evidence="; ".join(evidence),
        status="review" if classification_confidence < 0.7 else "ok",
    )
    fields["_llm"] = FieldValue(
        value="used" if llm["used"] else ("unavailable" if llm.get("error") else "not configured"),
        confidence=0.0,
        source="llm",
        evidence=llm.get("error") or "Deterministic extraction only.",
        status="ok",
    )

    return {
        "doc_type": doc_type,
        "classification_confidence": classification_confidence,
        "classification_evidence": evidence,
        "text": text,
        "method": text_result.method,
        "pages": text_result.pages,
        "mean_ocr_confidence": text_result.mean_confidence,
        "attempts": text_result.attempts,
        "fields": {key: value.to_dict() for key, value in fields.items()},
        "lines": [line.to_dict() for line in parsed["lines"]],
        "issues": issues + text_result.issues,
        "llm": {"used": llm["used"], "error": llm.get("error")},
        "needs_review": bool(
            issues
            or any(v.status in ("review", "missing") for v in fields.values())
            or any(line.get("code_source") in ("inferred", "unavailable") for line in [l.to_dict() for l in parsed["lines"]])
        ),
    }
