"""Pre-authorisation letter rendering (clinically structured, print-ready)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .. import codes
from ..config import MEMBERS, PLANS
from ..models import Claim, PlanTerms, money, money_str

NAVY = colors.HexColor("#12304f")
ACCENT = colors.HexColor("#0f766e")
GREY = colors.HexColor("#5b6570")


@dataclass
class PreAuthLetter:
    claim: Claim
    plan: PlanTerms
    reference: str
    role: str
    diagnosis_codes: list[str]
    justification: str
    request_date: date = field(default_factory=date.today)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim.claim_id,
            "plan_id": self.plan.plan_id,
            "insurer": self.plan.insurer_name,
            "reference": self.reference,
            "role": self.role,
            "diagnoses": self.diagnosis_codes,
            "estimated_cost": str(self.claim.total_billed),
        }


def _styles():
    sheet = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=sheet["Title"], fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", parent=sheet["Normal"], fontName="Helvetica", fontSize=9, textColor=GREY, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=sheet["Heading2"], fontName="Helvetica-Bold", fontSize=10.5, textColor=ACCENT, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("body", parent=sheet["BodyText"], fontName="Helvetica", fontSize=9.4, leading=13.6, spaceAfter=5),
        "small": ParagraphStyle("small", parent=sheet["BodyText"], fontName="Helvetica", fontSize=8.2, leading=11, textColor=GREY),
        "cell": ParagraphStyle("cell", parent=sheet["BodyText"], fontName="Helvetica", fontSize=8.6, leading=11.5),
        "cell_bold": ParagraphStyle("cellb", parent=sheet["BodyText"], fontName="Helvetica-Bold", fontSize=8.6, leading=11.5),
    }


def _kv_table(rows: list[tuple[str, str]], styles) -> Table:
    table = Table([[Paragraph(label, styles["cell_bold"]), Paragraph(value, styles["cell"])] for label, value in rows], colWidths=[42 * mm, 118 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#dde3e8")),
            ]
        )
    )
    return table


def build_letter(claim: Claim, plan: PlanTerms, reference: str, role: str, diagnosis_codes: list[str], justification: str, output: Path) -> PreAuthLetter:
    styles = _styles()
    member = MEMBERS[claim.member_id]
    letter = PreAuthLetter(
        claim=claim,
        plan=plan,
        reference=reference,
        role=role,
        diagnosis_codes=diagnosis_codes,
        justification=justification,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Pre-authorisation request {reference}",
        author="DuCO-Agent",
    )
    story = [
        Paragraph(f"PRE-AUTHORISATION REQUEST &nbsp;|&nbsp; {plan.insurer_name} - {plan.plan_name}", styles["title"]),
        Paragraph(
            f"Reference {reference} &nbsp;&nbsp; Request date {letter.request_date.strftime('%d %B %Y')} &nbsp;&nbsp; "
            f"Plan {plan.plan_id} &nbsp;&nbsp; Policy year 2026",
            styles["subtitle"],
        ),
        Paragraph("1. Member and policy", styles["h2"]),
        _kv_table(
            [
                ("Patient", f"{member['name']} (MRN {claim.member_id})"),
                ("Date of birth / relationship", f"{member['date_of_birth']} / {member['relationship']}"),
                ("Coverage role", f"{role.capitalize()} under this policy"),
                ("Policy", f"{plan.plan_name}, {plan.insurer_name}, group policy 2026"),
                ("Network", "Cashless" if plan.plan_id == "PLAN_A" else "Reimbursement"),
            ],
            styles,
        ),
        Paragraph("2. Treating provider", styles["h2"]),
        _kv_table(
            [
                ("Provider", f"{claim.provider_name}, Mumbai"),
                ("Registration", "Maharashtra Medical Council reg. 2011/09/2345"),
                ("Planned service date", claim.service_date.strftime("%d %B %Y")),
                ("Estimated cost", f"INR {money_str(claim.total_billed)}"),
            ],
            styles,
        ),
        Paragraph("3. Clinical information", styles["h2"]),
        Paragraph(
            "Diagnosis: "
            + "; ".join(f"{code} ({codes.describe(code)})" for code in diagnosis_codes)
            + ".",
            styles["body"],
        ),
        Paragraph(justification, styles["body"]),
    ]

    rows = [[Paragraph("CPT", styles["cell_bold"]), Paragraph("Procedure", styles["cell_bold"]), Paragraph("Amount (INR)", styles["cell_bold"])]]
    for line in claim.lines:
        rows.append(
            [
                Paragraph(line.cpt_code or "n/a", styles["cell"]),
                Paragraph(f"{line.description}" + ("" if not line.non_covered else " <i>(excluded benefit)</i>"), styles["cell"]),
                Paragraph(money_str(line.billed_amount), styles["cell"]),
            ]
        )
    rows.append([Paragraph("", styles["cell"]), Paragraph("Total estimate", styles["cell_bold"]), Paragraph(money_str(claim.total_billed), styles["cell_bold"])])
    table = Table(rows, colWidths=[20 * mm, 100 * mm, 40 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5dde4")),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story += [
        Paragraph("4. Requested services and cost", styles["h2"]),
        table,
        Spacer(1, 8),
        Paragraph("5. Declaration", styles["h2"]),
        Paragraph(
            "The above services are medically necessary for the diagnosis stated. The treating surgeon confirms that "
            "conservative management has been considered and that the procedure is not for cosmetic purposes. "
            "Supporting documents enclosed: MRI report (right knee), surgeon's estimate, previous physiotherapy records. "
            f"The primary/secondary coordination position for this member is: {role} under this policy.",
            styles["body"],
        ),
        Spacer(1, 18),
        KeepTogether(
            [
                Paragraph("Authorised signatory - treating surgeon", styles["cell_bold"]),
                Spacer(1, 22),
                Paragraph("Dr. Rohit Naik, MS (Orthopaedics) &nbsp;&nbsp; Maharashtra Medical Council 2011/09/2345", styles["small"]),
                Spacer(1, 6),
                Paragraph("Generated by DuCO-Agent from the claim documents; verify all clinical details before submission.", styles["small"]),
            ]
        ),
    ]
    doc.build(story)
    return letter
