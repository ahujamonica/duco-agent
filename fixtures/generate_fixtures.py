"""Generate the four mock inputs the DuCO-Agent has to ingest.

Run ``python fixtures/generate_fixtures.py`` from the repository root. The
files are deliberately "unstructured": the physiotherapy invoice is a slightly
crumpled scan with a handwritten note and no billing codes, the MRI report is a
PDF of clinical prose, and the surgeon's estimate is a photo-style billing
sheet. Nothing here contains real patient data.
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent
PRINT_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
PRINT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
HAND_FONT = "/usr/share/fonts/truetype/google-script/DancingScript.ttf"

INVOICE_LINES = [
    ("1", "Physical Therapy Evaluation", "1", "3,500.00", "3,500.00"),
    ("2", "Therapeutic Exercise (Ultrasound + IFT)", "12", "2,000.00", "24,000.00"),
    ("3", "Home traction equipment (sale)", "1", "2,500.00", "2,500.00"),
]


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _paper(width: int, height: int, tone: int = 252) -> Image.Image:
    image = Image.new("RGB", (width, height), (tone, tone, tone - 2))
    noise = Image.effect_noise((width, height), 18).convert("L")
    image = Image.composite(image, Image.new("RGB", (width, height), (238, 236, 230)), noise.point(lambda v: 255 - v // 6))
    return image


def _crumple(image: Image.Image, angle: float = -4.2) -> Image.Image:
    """Approximate a crumpled phone-scan: rotation, soft shading, grain, blur."""
    image = image.rotate(angle, expand=True, fillcolor=(250, 250, 248), resample=Image.BICUBIC)
    width, height = image.size
    overlay = Image.new("L", (width, height), 0)
    pixels = overlay.load()
    for y in range(height):
        for x in range(0, width):
            # gentle diagonal shading, the usual artefact of a phone camera scan
            value = int(10 * (x / width) + 8 * (y / height))
            pixels[x, y] = value
    shading = Image.new("RGB", (width, height), (232, 230, 224))
    image = Image.composite(shading, image, overlay)
    noise = Image.effect_noise((width, height), 16).convert("L").point(lambda v: 26 if v > 132 else 0)
    image = Image.composite(Image.new("RGB", (width, height), (226, 224, 218)), image, noise)
    return image.filter(ImageFilter.GaussianBlur(0.55))


def build_invoice(path: Path) -> None:
    width, height = 1240, 1754  # A4 at ~150 dpi
    image = _paper(width, height)
    draw = ImageDraw.Draw(image)
    left, right = 90, width - 90

    draw.text((left, 70), "LAKSHMI PHYSIOTHERAPY & REHABILITATION CLINIC", font=_font(PRINT_BOLD, 34), fill=(25, 25, 30))
    draw.text((left, 118), "Shop 4, Sai Kripa CHS, Link Road, Andheri (W), Mumbai 400 053", font=_font(PRINT_FONT, 20), fill=(60, 60, 66))
    draw.text((left, 148), "GSTIN 27AABCL1234K1Z5          Tel 022-2673 4411", font=_font(PRINT_FONT, 20), fill=(60, 60, 66))
    draw.line((left, 190, right, 190), fill=(120, 120, 126), width=2)

    draw.text((left, 214), "INVOICE No: LPR/2026/1108", font=_font(PRINT_BOLD, 22), fill=(30, 30, 36))
    draw.text((right - 260, 214), "Date: 12/11/2026", font=_font(PRINT_BOLD, 22), fill=(30, 30, 36))
    draw.text((left, 250), "Patient: Priya Sen", font=_font(PRINT_FONT, 22), fill=(40, 40, 46))
    draw.text((left + 560, 250), "Age / Sex: 31 / F", font=_font(PRINT_FONT, 22), fill=(40, 40, 46))
    draw.text((left, 284), "Referred by: Dr. K. Rane (Orthopaedics)", font=_font(PRINT_FONT, 22), fill=(40, 40, 46))

    draw.rectangle((left, 336, right, 380), fill=(232, 233, 238))
    headers = ["Sr", "Service", "Qty", "Rate (INR)", "Amount (INR)"]
    xs = [left + 12, left + 70, left + 690, left + 760, right - 175]
    for x, text in zip(xs, headers):
        draw.text((x, 348), text, font=_font(PRINT_BOLD, 20), fill=(30, 30, 36))

    y = 402
    for sr, service, qty, rate, amount in INVOICE_LINES:
        draw.text((left + 12, y), sr, font=_font(PRINT_FONT, 21), fill=(35, 35, 40))
        draw.text((left + 70, y), service, font=_font(PRINT_FONT, 21), fill=(35, 35, 40))
        numeric_font = _font(PRINT_FONT, 21)
        draw.text((left + 690, y), qty, font=numeric_font, fill=(35, 35, 40))
        draw.text((left + 760, y), rate, font=numeric_font, fill=(35, 35, 40))
        draw.text((right - 14 - int(draw.textlength(amount, font=numeric_font)), y), amount, font=numeric_font, fill=(35, 35, 40))
        y += 44

    draw.line((left, y + 10, right, y + 10), fill=(120, 120, 126), width=2)
    draw.text((left + 680, y + 26), "Total", font=_font(PRINT_BOLD, 24), fill=(20, 20, 26))
    total_font = _font(PRINT_BOLD, 24)
    draw.text((right - 14 - int(draw.textlength("30,000.00", font=total_font)), y + 26), "30,000.00", font=total_font, fill=(20, 20, 26))
    draw.text((left, y + 76), "Amount in words: Rupees Thirty Thousand Only", font=_font(PRINT_FONT, 20), fill=(45, 45, 50))
    draw.text((left, y + 108), "Mode of payment: UPI            Status: UNPAID", font=_font(PRINT_FONT, 20), fill=(45, 45, 50))

    hand = _font(HAND_FONT, 40)
    draw.text((left + 40, y + 180), "Pls settle by 30/11. Codes not on bill -", font=hand, fill=(30, 45, 120))
    draw.text((left + 40, y + 224), "share with insurer if they ask.", font=hand, fill=(30, 45, 120))
    draw.text((left + 40, y + 300), "R. Sawant", font=hand, fill=(30, 45, 120))

    draw.text((left, height - 120), "This is a computer generated invoice. Subject to Mumbai jurisdiction.", font=_font(PRINT_FONT, 17), fill=(80, 80, 86))

    image = _crumple(image)
    image.save(path, "PNG")


def build_estimate(path: Path) -> None:
    width, height = 1240, 1500
    image = _paper(width, height, tone=250)
    draw = ImageDraw.Draw(image)
    left, right = 90, width - 90

    draw.text((left, 70), "DR. ROHIT NAIK  |  ORTHOPAEDIC SURGEON", font=_font(PRINT_BOLD, 32), fill=(22, 24, 30))
    draw.text((left, 116), "Knee & Sports Injury Clinic, Bandra (W), Mumbai 400 050", font=_font(PRINT_FONT, 19), fill=(60, 60, 66))
    draw.line((left, 158, right, 158), fill=(110, 110, 116), width=2)
    draw.text((left, 180), "SURGICAL ESTIMATE", font=_font(PRINT_BOLD, 26), fill=(22, 24, 30))
    draw.text((left, 220), "Patient: Aarav Sen            Date: 21/11/2026", font=_font(PRINT_FONT, 21), fill=(35, 35, 40))
    draw.text((left, 254), "Procedure: ACL reconstruction with partial meniscectomy (Right knee)", font=_font(PRINT_FONT, 21), fill=(35, 35, 40))

    rows = [
        ("CPT 29888", "Arthroscopically aided ACL reconstruction", "3,50,000.00"),
        ("CPT 29881", "Arthroscopy, knee, surgical; with meniscectomy", "1,00,000.00"),
    ]
    y = 320
    draw.rectangle((left, y - 10, right, y + 34), fill=(232, 233, 238))
    draw.text((left + 14, y), "Code", font=_font(PRINT_BOLD, 20), fill=(28, 28, 34))
    draw.text((left + 190, y), "Description", font=_font(PRINT_BOLD, 20), fill=(28, 28, 34))
    draw.text((right - 210, y), "Amount (INR)", font=_font(PRINT_BOLD, 20), fill=(28, 28, 34))
    y += 54
    for code, description, amount in rows:
        draw.text((left + 14, y), code, font=_font(PRINT_BOLD, 21), fill=(35, 35, 40))
        draw.text((left + 190, y), description, font=_font(PRINT_FONT, 21), fill=(35, 35, 40))
        draw.text((right - 200, y), amount, font=_font(PRINT_FONT, 21), fill=(35, 35, 40))
        y += 48

    draw.line((left, y + 10, right, y + 10), fill=(110, 110, 116), width=2)
    draw.text((left + 700, y + 26), "Total", font=_font(PRINT_BOLD, 24), fill=(20, 20, 26))
    draw.text((right - 200, y + 26), "4,50,000.00", font=_font(PRINT_BOLD, 24), fill=(20, 20, 26))
    draw.text((left, y + 100), "Pre-authorisation required before admission.", font=_font(PRINT_BOLD, 21), fill=(120, 30, 30))
    draw.text((left, y + 134), "Estimate valid for 30 days. Charges may vary with clinical findings.", font=_font(PRINT_FONT, 19), fill=(60, 60, 66))

    stamp_font = _font(PRINT_BOLD, 26)
    draw.text((right - 320, y + 210), "FOR AARAV SEN", font=stamp_font, fill=(90, 100, 130))
    image = _crumple(image, angle=0.9)
    image.save(path, "JPEG", quality=82)


def build_mri_report(path: Path) -> None:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica", fontSize=10, leading=15)
    head = ParagraphStyle("head", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=16, spaceAfter=6)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    story = [
        Paragraph("SUNRISE DIAGNOSTIC CENTRE - DEPARTMENT OF RADIOLOGY", head),
        Paragraph("MRI Right Knee (Plain) | Study ID: SDC/MRI/2026/18442", body),
        Spacer(1, 6),
        Paragraph("Patient: Aarav Sen &nbsp;&nbsp; Age/Sex: 33 / M &nbsp;&nbsp; MRN: SEN-A-002", body),
        Paragraph("Referred by: Dr. K. Rane (Orthopaedics) &nbsp;&nbsp; Study date: 18/11/2026", body),
        Spacer(1, 10),
        Paragraph("CLINICAL INDICATION", head),
        Paragraph("Twisting injury of the right knee while playing football. Persistent instability and giving way. Suspected ligamentous injury.", body),
        Spacer(1, 8),
        Paragraph("TECHNIQUE", head),
        Paragraph("Sagittal, coronal and axial PD fat-saturated and T2-weighted sequences of the right knee on a 1.5 T scanner.", body),
        Spacer(1, 8),
        Paragraph("FINDINGS", head),
        Paragraph("There is a complete tear of the anterior cruciate ligament (ACL) with discontinuity of the fibres at the femoral attachment. A complex tear of the medial meniscus is seen involving the posterior horn. Small joint effusion is present. The posterior cruciate ligament, lateral collateral ligament and lateral meniscus appear intact. No acute fracture or marrow oedema is identified.", body),
        Spacer(1, 8),
        Paragraph("IMPRESSION", head),
        Paragraph("1. Complete tear of the anterior cruciate ligament, right knee.<br/>2. Tear of the medial meniscus, right knee.<br/>3. Small joint effusion.", body),
        Spacer(1, 10),
        Paragraph("Recommended: orthopaedic correlation and ACL reconstruction. Surgical planning advised.", body),
        Spacer(1, 14),
        Paragraph("Dr. Meera Iyer, MD (Radiodiagnosis) - Consultant Radiologist", body),
    ]
    doc.build(story)


def build_transcript(path: Path) -> None:
    path.write_text(
        "Hi DuCO-Agent, I need to get my knee operated on soon, and Priya has some physical "
        "therapy bills lying around. We have Insurer1 (Plan A) and Insurer2 (Plan B). Can you "
        "help us figure out which plan pays first for my surgery and her bills? How much will "
        "we actually have to pay out of our own pocket? Also, we need the pre-auth letters "
        "generated for both insurers so we don't end up with a claim rejection. Please help!\n",
        encoding="utf-8",
    )


def main() -> None:
    build_invoice(ROOT / "priya_pt_invoice.png")
    build_estimate(ROOT / "surgeon_estimate.jpg")
    build_mri_report(ROOT / "aarav_mri_report.pdf")
    build_transcript(ROOT / "user_query.txt")
    print("fixtures written to", ROOT)


if __name__ == "__main__":
    main()
