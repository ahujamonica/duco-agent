"""Extraction tests: the parsers must work on messy text, not just clean input."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from duco_agent import codes, extraction
from duco_agent.tools.pdf import extract_pdf_text
from server.services.coverage import claim_input
from server.services.document_intel import amounts_in, parse_amount, parse_invoice

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"

INVOICE_TEXT = """LAKSHMI PHYSIOTHERAPY & REHABILITATION CLINIC
Shop 4, Sai Kripa CHS, Link Road, Andheri (W), Mumbai 400 053
INVOICE No: LPR/2026/1108 Date: 12/11/2026
Patient: Priya Sen Age / Sex: 31/F
referred by DR. K. Rane (Orthopaedics)
Sr Service Qty Rate (INR) Amount (INR)
al Physical Therapy Evaluation a, 3,500.00 3,500.00
2 Therapeutic Exercise (Ultrasound + IFT) 12 2,000.00 24,000.00
3 Home traction equipment (sale) al 2,500.00 2,500.00
Total 30,000.00
"""

ESTIMATE_TEXT = """DR. ROHIT NAIK | ORTHOPAEDIC SURGEON
SURGICAL ESTIMATE
Patient: Aarav Sen Date: 21/11/2026
CPT 29888 Arthroscopically aided ACL reconstruction 3,50,000.00
CPT 29881 Arthroscopy, knee, surgical; with meniscectomy 1,00,000.00
Total 4,50,000.00
"""


def test_invoice_parse_survives_noise():
    parsed = extraction.parse_invoice(INVOICE_TEXT)
    assert len(parsed.lines) == 3
    assert parsed.field_value("total") == Decimal("30000.00")
    assert parsed.field_value("sum_reconciles") is True
    # Quantity is illegible on the left of the table; it is derived from amount / rate.
    assert parsed.lines[1].quantity == 12
    assert parsed.lines[2].amount == Decimal("2500.00")


def test_invoice_mismatch_is_flagged():
    broken = INVOICE_TEXT.replace("24,000.00", "24,900.00")
    parsed = extraction.parse_invoice(broken)
    assert parsed.field_value("sum_reconciles") is False
    assert any("does not match" in issue for issue in parsed.issues)


def test_estimate_parse_reads_cpt_codes():
    parsed = extraction.parse_estimate(ESTIMATE_TEXT)
    assert [line.cpt_code for line in parsed.lines] == ["29888", "29881"]
    assert parsed.field_value("total") == Decimal("450000.00")
    assert parsed.field_value("sum_reconciles") is True


def test_mri_report_yields_the_two_tears():
    text, pages = extract_pdf_text(FIXTURES / "aarav_mri_report.pdf")
    parsed = extraction.parse_mri_report(text)
    findings = " ".join(parsed.field_value("findings", []))
    assert pages >= 1
    assert "anterior cruciate" in findings.lower()
    assert "meniscus" in findings.lower()


def test_transcript_becomes_goals():
    parsed = extraction.parse_transcript((FIXTURES / "user_query.txt").read_text(encoding="utf-8"))
    goals = parsed.field_value("asks", [])
    assert "coordination_order" in goals
    assert "preauth_letters" in goals


def test_code_inference_maps_the_invoice_lines():
    assert codes.lookup_cpt("Physical Therapy Evaluation")[0] == "97161"
    assert codes.lookup_cpt("Therapeutic Exercise (Ultrasound + IFT)")[0] == "97110"
    assert codes.lookup_cpt("something entirely unrelated")[0] is None
    assert codes.infer_diagnosis_codes("complete tear of the anterior cruciate ligament")[0][0] == "S83.511A"


def test_server_invoice_parser_preserves_decimal_lines_and_separates_summary_amounts():
    parsed = parse_invoice(
        """INVOICE
Invoice Date: 01/01/2025
Service Date: 02/01/2025
Sr Service Qty Rate Amount
Consultation 2 0.10 0.20
Sub Total: 0.15
CGST: 0.01
Discount: 0.01
Adjustment: 0.02
Amount Paid: 0.10
Balance Due: 0.10
Invoice Total: 0.20
""",
        source="pdf_text",
        ocr=None,
        filename="invoice.txt",
    )

    assert len(parsed["lines"]) == 1
    assert parsed["lines"][0].quantity == 2
    assert parsed["lines"][0].unit_rate == "0.10"
    assert parsed["lines"][0].amount == "0.20"
    assert parsed["fields"]["tax"].value == "0.01"
    assert parsed["fields"]["discount"].value == "0.01"
    assert parsed["fields"]["adjustment"].value == "0.02"
    assert parsed["fields"]["amount_paid"].value == "0.10"
    assert parsed["fields"]["balance_due"].value == "0.10"
    assert parsed["fields"]["total"].value == "0.20"
    assert parsed["fields"]["subtotal"].value == "0.15"
    assert parsed["fields"]["service_date"].value == "2025-01-02"
    assert amounts_in("Service 1.00 1.00 1.00") == ["1.00", "1.00", "1.00"]
    assert parse_amount("1,234,567.89") == "1234567.89"


def test_server_invoice_parser_does_not_infer_missing_quantity_or_rate():
    parsed = parse_invoice(
        "INVOICE\nInvoice Date: 01/01/2025\nService charge 20.00\nInvoice Total: 20.00",
        source="pdf_text",
        ocr=None,
        filename="invoice.txt",
    )

    assert len(parsed["lines"]) == 1
    assert parsed["lines"][0].quantity is None
    assert parsed["lines"][0].unit_rate is None
    assert parsed["lines"][0].amount == "20.00"
    assert parsed["fields"]["service_date"].value is None


def test_claim_input_preserves_unknown_quantity_and_unit_rate():
    line = SimpleNamespace(
        id=1,
        description="Service charge",
        billed_amount=Decimal("20.00"),
        quantity=1,
        quantity_known=False,
        unit_rate=Decimal("0.00"),
        unit_rate_known=False,
        cpt_code=None,
        icd_codes=[],
        category="professional",
        excluded=False,
        evidence="",
    )
    claim = SimpleNamespace(
        id=1,
        patient_name="Test Patient",
        member_id=1,
        provider_name="Test Provider",
        service_date=None,
        lines=[line],
        bill_number=None,
    )

    converted = claim_input(claim, None)

    assert converted.lines[0].billed == Decimal("20.00")
    assert converted.lines[0].quantity is None
    assert converted.lines[0].unit_rate is None
