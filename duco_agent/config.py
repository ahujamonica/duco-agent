"""Plan terms, members and mock-API configuration for the DuCO-Agent demo.

The numbers below are illustrative benefits written for this assessment. They
are not real Prudential/insurer terms; ``docs/COB_RULES.md`` records every
assumption so a reviewer can follow the arithmetic.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .models import MemberAccumulator, PlanTerms, money

MEMBERS = {
    "SEN-P-001": {
        "name": "Priya Sen",
        "date_of_birth": "1995-04-18",
        "relationship": "primary",
        "plan_a_role": "primary",
        "plan_b_role": "dependent",
    },
    "SEN-A-002": {
        "name": "Aarav Sen",
        "date_of_birth": "1993-09-02",
        "relationship": "primary",
        "plan_a_role": "dependent",
        "plan_b_role": "primary",
    },
}

PLAN_A = PlanTerms(
    plan_id="PLAN_A",
    insurer_name="Insurer1",
    plan_name="SecureShield Corporate Health",
    deductible_per_member=money(5000),
    coinsurance_member=Decimal("0.20"),
    oop_max_per_member=money(60000),
    preauth_threshold=money(50000),
    preauth_penalty_rate=Decimal("0.20"),
    therapy_session_limit=20,
    equipment_covered=False,
)

PLAN_B = PlanTerms(
    plan_id="PLAN_B",
    insurer_name="Insurer2",
    plan_name="HealthGuard Plus",
    deductible_per_member=money(5000),
    coinsurance_member=Decimal("0.10"),
    oop_max_per_member=money(80000),
    preauth_threshold=money(50000),
    preauth_penalty_rate=Decimal("0.25"),
    therapy_session_limit=15,
    equipment_covered=False,
)

PLANS = {PLAN_A.plan_id: PLAN_A, PLAN_B.plan_id: PLAN_B}

# Year-to-date accumulators as recorded by each insurer's mock API.
ACCUMULATORS = {
    ("PLAN_A", "SEN-P-001"): MemberAccumulator("SEN-P-001", "PLAN_A", money(1500), money(1500)),
    ("PLAN_A", "SEN-A-002"): MemberAccumulator("SEN-A-002", "PLAN_A", money(0), money(0)),
    ("PLAN_B", "SEN-P-001"): MemberAccumulator("SEN-P-001", "PLAN_B", money(0), money(0)),
    ("PLAN_B", "SEN-A-002"): MemberAccumulator("SEN-A-002", "PLAN_B", money(2000), money(2000)),
}

# Employer plan membership: each person is primary on their own plan and a
# dependent on the spouse's plan. This is what makes COB necessary.
PRIMARY_PLAN_BY_PATIENT = {
    "Priya Sen": "PLAN_A",
    "Aarav Sen": "PLAN_B",
}

SECONDARY_PLAN_BY_PATIENT = {
    "Priya Sen": "PLAN_B",
    "Aarav Sen": "PLAN_A",
}

BENEFIT_YEAR = 2026

# Documents the intake agent must ingest, in the order they are handed over.
DOCUMENTS = [
    {
        "path": "fixtures/priya_pt_invoice.png",
        "kind": "invoice_image",
        "label": "Priya - physiotherapy invoice (scanned)",
        "patient": "Priya Sen",
    },
    {
        "path": "fixtures/aarav_mri_report.pdf",
        "kind": "radiology_pdf",
        "label": "Aarav - knee MRI radiology report",
        "patient": "Aarav Sen",
    },
    {
        "path": "fixtures/surgeon_estimate.jpg",
        "kind": "estimate_image",
        "label": "Aarav - surgeon billing estimate",
        "patient": "Aarav Sen",
    },
    {
        "path": "fixtures/user_query.txt",
        "kind": "transcript",
        "label": "Aarav - voice query transcript (voice-to-text)",
        "patient": "Aarav Sen",
    },
]

DEMO_OUTPUT_DIR = "outputs"
SERVICE_DATE_SURGERY = date(2026, 12, 4)
SERVICE_DATE_THERAPY = date(2026, 11, 12)
