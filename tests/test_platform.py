"""End-to-end platform tests: auth, dynamic families, policies, documents,
human review, the agent workflow, results, reports and the mock insurer API."""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from server.main import app

ROOT = Path(__file__).resolve().parent.parent
INVOICE = ROOT / "fixtures" / "priya_pt_invoice.png"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/register",
        json={"name": "Test Owner", "email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def make_household(client: TestClient, headers: dict) -> tuple[int, dict[str, int], int, str]:
    family = client.post("/api/families", json={"name": "Rao household"}, headers=headers)
    assert family.status_code == 201, family.text
    family_id = family.json()["id"]
    members: dict[str, int] = {}
    for name, relation, dob in (
        ("Asha Rao", "self", "1990-02-02"),
        ("Vikram Rao", "spouse", "1988-07-07"),
        ("Ira Rao", "child", "2015-09-09"),
    ):
        response = client.post(
            f"/api/families/{family_id}/members",
            json={"name": name, "relation": relation, "date_of_birth": dob},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        members[name] = response.json()["id"]
    terms = {
        "sum_insured": "600000",
        "deductible": "10000",
        "coinsurance_member": "0.15",
        "oop_max": "75000",
        "annual_limit": "600000",
        "preauth_threshold": "40000",
        "preauth_penalty_rate": "0.2",
        "preauth_cpt_codes": ["29888"],
        "sublimits": [
            {
                "key": "therapy",
                "label": "Annual physiotherapy limit",
                "limit": "20000",
                "used": "0",
                "applies_to_categories": ["therapy"],
                "basis": "per_year",
            }
        ],
        "exclusions": [{"label": "Equipment", "keyword": "equipment"}],
    }
    policy_number = f"RAO-{uuid.uuid4().hex[:8].upper()}"
    policy = client.post(
        "/api/policies",
        json={
            "family_id": family_id,
            "insurer_name": "Test Assurance",
            "plan_name": "Family Care",
            "policy_number": policy_number,
            "policyholder_member_id": members["Asha Rao"],
            "status": "active",
            "start_date": "2025-01-01",
            "end_date": "2027-12-31",
            "terms": terms,
            "members": [
                {"member_id": members["Asha Rao"], "role": "policyholder"},
                {"member_id": members["Vikram Rao"], "role": "spouse"},
                {"member_id": members["Ira Rao"], "role": "dependent"},
            ],
        },
        headers=headers,
    )
    assert policy.status_code == 201, policy.text
    return family_id, members, policy.json()["id"], policy_number


def wait_for_run(client: TestClient, headers: dict, case_id: int, timeout: float = 45.0) -> str:
    deadline = time.time() + timeout
    status = "queued"
    while time.time() < deadline:
        detail = client.get(f"/api/cases/{case_id}", headers=headers)
        assert detail.status_code == 200
        status = detail.json()["status"]
        if status not in ("queued", "running"):
            return status
        time.sleep(0.4)
    raise AssertionError(f"case {case_id} did not finish; last status {status}")


def test_registration_and_auth_required(client: TestClient):
    assert client.get("/api/dashboard").status_code == 401
    headers = register(client, "auth@example.com")
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "auth@example.com"
    assert client.post("/api/auth/login", json={"email": "auth@example.com", "password": "wrong"}).status_code == 401


def test_dynamic_family_policy_many_to_many(client: TestClient):
    headers = register(client, "family@example.com")
    family_id, members, policy_id, policy_number = make_household(client, headers)
    detail = client.get(f"/api/families/{family_id}", headers=headers).json()
    assert len(detail["members"]) == 3
    assert len(detail["policies"]) == 1
    policy = client.get(f"/api/policies/{policy_id}", headers=headers).json()
    assert {member["member_id"] for member in policy["members"]} == set(members.values())
    roles = {member["name"]: member["role"] for member in policy["members"]}
    assert roles["Asha Rao"] == "policyholder"
    assert roles["Ira Rao"] == "dependent"
    # A second household cannot see the first one's policy.
    other = register(client, "other@example.com")
    assert client.get(f"/api/policies/{policy_id}", headers=other).status_code == 404
    assert client.get(f"/api/families/{family_id}", headers=other).status_code == 404


def test_document_upload_dedup_and_review(client: TestClient):
    headers = register(client, "docs@example.com")
    family_id, members, policy_id, policy_number = make_household(client, headers)
    with INVOICE.open("rb") as handle:
        response = client.post(
            "/api/documents/upload",
            data={"family_id": str(family_id), "doc_type": "invoice"},
            files={"file": ("invoice.png", handle, "image/png")},
            headers=headers,
        )
    assert response.status_code == 201, response.text
    document = response.json()["document"]
    assert document["doc_type"] == "invoice"
    assert 0.0 < document["classification_confidence"] <= 1.0
    assert document["fields"]["patient"]["value"] == "Priya Sen"
    assert document["fields"]["total"]["value"] == "30000.00"
    assert document["mean_ocr_confidence"] and document["mean_ocr_confidence"] > 0
    with INVOICE.open("rb") as handle:
        duplicate = client.post(
            "/api/documents/upload",
            data={"family_id": str(family_id), "doc_type": "invoice"},
            files={"file": ("invoice-copy.png", handle, "image/png")},
            headers=headers,
        )
    assert duplicate.status_code == 201
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["document"]["id"] == document["id"]


def test_end_to_end_case_review_results_and_reports(client: TestClient):
    headers = register(client, "case@example.com")
    family_id, members, policy_id, policy_number = make_household(client, headers)
    with INVOICE.open("rb") as handle:
        uploaded = client.post(
            "/api/documents/upload",
            data={"family_id": str(family_id), "doc_type": "invoice"},
            files={"file": ("rechnung.png", handle, "image/png")},
            headers=headers,
        ).json()["document"]
    case = client.post(
        "/api/cases",
        json={
            "family_id": family_id,
            "title": "Asha physiotherapy",
            "patient_member_id": members["Asha Rao"],
            "provider_name": "City Physio",
            "service_date": "2026-11-10",
            "document_ids": [uploaded["id"]],
            "policy_ids": [policy_id],
            "narrative": "Physiotherapy after a back injury.",
        },
        headers=headers,
    )
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]
    started = client.post(f"/api/cases/{case_id}/analyze", headers=headers)
    assert started.status_code == 202, started.text
    status = wait_for_run(client, headers, case_id)
    assert status in ("awaiting_review", "complete")
    if status == "awaiting_review":
        detail = client.get(f"/api/cases/{case_id}", headers=headers).json()
        items = [
            {"id": item["id"], "status": "accepted", "value": item["extracted_value"]}
            for item in detail["review_items"]
            if item["status"] == "pending"
        ]
        reviewed = client.post(f"/api/cases/{case_id}/review", json={"items": items, "confirm": True}, headers=headers)
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["review_confirmed"] is True
        assert client.post(f"/api/cases/{case_id}/analyze", headers=headers).status_code == 202
        status = wait_for_run(client, headers, case_id)
    assert status == "complete", client.get(f"/api/cases/{case_id}", headers=headers).json()

    results = client.get(f"/api/cases/{case_id}/results", headers=headers).json()
    totals = results["totals"]
    billed = Decimal(totals["billed"])
    paid = Decimal(totals["insurer_paid"])
    patient = Decimal(totals["patient_liability"])
    adjustments = Decimal(totals["contractual_adjustment"])
    assert billed == Decimal("30000.00")
    assert paid + patient + adjustments == billed
    assert paid > 0
    assert Decimal(totals["excluded"]) == Decimal("2500.00")
    assert results["invariants"] and all(item.get("passed", True) for item in results["invariants"])
    assert results["claims"] and results["claims"][0]["lines"]
    assert all(inv["passed"] for inv in results["claims"][0]["invariants"])

    trace = client.get(f"/api/cases/{case_id}/trace", headers=headers).json()
    assert trace["stage"] == "complete"
    assert len(trace["events"]) >= 15
    assert set(trace["tasks"].values()) == {"done"}

    reports = client.get(f"/api/cases/{case_id}/reports", headers=headers).json()["reports"]
    kinds = {report["kind"] for report in reports}
    assert {"json", "html", "trace", "audio"}.issubset(kinds)
    json_report = next(report for report in reports if report["kind"] == "json")
    download = client.get(f"/api/cases/{case_id}/reports/{json_report['id']}/download", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")

    line_id = results["claims"][0]["lines"][0]["id"]
    explain = client.get(f"/api/cases/{case_id}/lines/{line_id}/explain", headers=headers)
    assert explain.status_code == 200
    assert explain.json()["calculation"]["check"] is True

    simulation = client.post(
        f"/api/cases/{case_id}/simulate",
        json={"policies": {str(policy_id): {"deductible": "0", "coinsurance_member": "0"}}},
        headers=headers,
    )
    assert simulation.status_code == 200
    body = simulation.json()
    assert body["hypothetical"] is True
    assert body["baseline"]["patient_liability"] == totals["patient_liability"]
    assert body["result"]["patient_liability"] != totals["patient_liability"]

    dashboard = client.get("/api/dashboard", headers=headers).json()
    assert dashboard["totals"]["cases"] >= 1
    assert DashboardDecimal(dashboard["totals"]["billed"]) >= billed


def DashboardDecimal(value: str) -> Decimal:
    return Decimal(value)


def test_preauthorization_letter_is_generated_for_a_surgical_estimate(client: TestClient):
    headers = register(client, "surgery@example.com")
    family_id, members, policy_id, policy_number = make_household(client, headers)
    with (ROOT / "fixtures" / "surgeon_estimate.jpg").open("rb") as handle:
        document = client.post(
            "/api/documents/upload",
            data={"family_id": str(family_id), "doc_type": "estimate"},
            files={"file": ("estimate.jpg", handle, "image/jpeg")},
            headers=headers,
        ).json()["document"]
    case = client.post(
        "/api/cases",
        json={
            "family_id": family_id,
            "title": "ACL reconstruction",
            "patient_member_id": members["Asha Rao"],
            "provider_name": "Sunrise Hospital",
            "service_date": "2026-11-20",
            "document_ids": [document["id"]],
            "policy_ids": [policy_id],
        },
        headers=headers,
    ).json()
    client.post(f"/api/cases/{case['id']}/analyze", headers=headers)
    status = wait_for_run(client, headers, case["id"])
    if status == "awaiting_review":
        detail = client.get(f"/api/cases/{case['id']}", headers=headers).json()
        items = [
            {"id": item["id"], "status": "accepted", "value": item["extracted_value"]}
            for item in detail["review_items"]
            if item["status"] == "pending"
        ]
        client.post(f"/api/cases/{case['id']}/review", json={"items": items, "confirm": True}, headers=headers)
        client.post(f"/api/cases/{case['id']}/analyze", headers=headers)
        status = wait_for_run(client, headers, case["id"])
    assert status == "complete"
    letters = client.get(f"/api/cases/{case['id']}/letters", headers=headers).json()["letters"]
    assert letters, "a surgical estimate above the pre-auth threshold must produce a letter"
    download = client.get(letters[0]["download_url"], headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    text = ""
    path = Path(f"/tmp/duco-letter-{case['id']}.pdf")
    path.write_bytes(download.content)
    pdf = pymupdf.open(str(path))
    for page in pdf:
        text += page.get_text()
    pdf.close()
    assert "not an approval" in text.lower()
    assert "SIMULATED SANDBOX" in text


def test_mock_insurer_endpoints_are_dynamic(client: TestClient):
    headers = register(client, "mock@example.com")
    family_id, members, policy_id, policy_number = make_household(client, headers)
    eligible = client.post(
        "/mock-insurers/eligibility",
        json={"policy_number": policy_number, "member_name": "Asha Rao", "service_date": "2026-06-01"},
    )
    assert eligible.status_code == 200
    assert eligible.json()["simulated"] is True
    assert eligible.json()["eligible"] is True
    ineligible = client.post(
        "/mock-insurers/eligibility",
        json={"policy_number": policy_number, "member_name": "Nobody At All", "service_date": "2026-06-01"},
    )
    assert ineligible.json()["eligible"] is False
    benefits = client.post(
        "/mock-insurers/benefits",
        json={"policy_number": policy_number, "member_name": "Asha Rao"},
    ).json()
    assert benefits["benefits"]["deductible_remaining"] == "10000.00"
    claim = client.post(
        "/mock-insurers/claims",
        json={
            "policy_number": policy_number,
            "member_name": "Asha Rao",
            "service_date": "2026-06-01",
            "provider": "City Physio",
            "lines": [{"description": "Therapeutic exercise", "billed": "20000", "cpt_code": "97110", "category": "therapy"}],
        },
    ).json()
    assert claim["simulated"] is True
    assert claim["status"] in ("approved", "partially_approved")
    fetched = client.get(f"/mock-insurers/claims/{claim['reference']}")
    assert fetched.status_code == 200
    assert fetched.json()["reference"] == claim["reference"]
    rejected = client.post(
        "/mock-insurers/pre-authorization",
        json={
            "policy_number": policy_number,
            "member_name": "Asha Rao",
            "procedure_codes": ["29888"],
            "diagnosis_codes": [],
            "estimated_cost": "450000",
            "documents": [],
        },
    ).json()
    assert rejected["status"] == "rejected"
    assert any("diagnosis" in reason for reason in rejected["reasons"])


def test_document_classification_and_code_resolution():
    from server.services.document_intel import classify
    from duco_agent.codes import suggest_cpt, suggest_icd

    invoice_type, confidence, _ = classify(
        "TAX INVOICE Bill No: X1 Amount Payable 2,500 Patient: Asha Rao Total 2,500", "bill.png"
    )
    assert invoice_type == "invoice"
    assert confidence >= 0.6
    policy_type, _, _ = classify(
        "Policy Schedule Sum Insured 500000 Insurer Deductible Co-insurance Waiting Period Exclusions", "policy.pdf"
    )
    assert policy_type == "policy"
    cpt = suggest_cpt("arthroscopically aided ACL reconstruction")
    assert cpt and cpt[0]["code"] == "29888"
    icd = suggest_icd("Complete tear of the anterior cruciate ligament with a medial meniscus tear")
    assert icd and icd[0]["code"] == "S83.511A"
    assert 0.0 < icd[0]["confidence"] <= 0.95


def test_inactive_policy_is_kept_in_trace_but_not_paid(client: TestClient):
    headers = register(client, "inactive@example.com")
    family_id, members, policy_id, policy_number = make_household(client, headers)
    client.patch(f"/api/policies/{policy_id}", json={"status": "inactive"}, headers=headers)
    with INVOICE.open("rb") as handle:
        document = client.post(
            "/api/documents/upload",
            data={"family_id": str(family_id), "doc_type": "invoice"},
            files={"file": ("invoice.png", handle, "image/png")},
            headers=headers,
        ).json()["document"]
    case = client.post(
        "/api/cases",
        json={
            "family_id": family_id,
            "title": "Lapsed policy check",
            "patient_member_id": members["Asha Rao"],
            "document_ids": [document["id"]],
            "policy_ids": [policy_id],
        },
        headers=headers,
    ).json()
    client.post(f"/api/cases/{case['id']}/analyze", headers=headers)
    status = wait_for_run(client, headers, case["id"])
    if status == "awaiting_review":
        detail = client.get(f"/api/cases/{case['id']}", headers=headers).json()
        items = [
            {"id": item["id"], "status": "accepted", "value": item["extracted_value"]}
            for item in detail["review_items"]
            if item["status"] == "pending"
        ]
        client.post(f"/api/cases/{case['id']}/review", json={"items": items, "confirm": True}, headers=headers)
        client.post(f"/api/cases/{case['id']}/analyze", headers=headers)
        status = wait_for_run(client, headers, case["id"])
    assert status == "complete"
    detail = client.get(f"/api/cases/{case['id']}", headers=headers).json()
    assert any("inactive" in (gap.get("detail") or "").lower() or "inactive" in (gap.get("title") or "").lower() for gap in detail["gaps"])


def _policy_pdf(path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=A4)
    lines = [
        "TEST ASSURANCE — FAMILY HEALTH POLICY SCHEDULE",
        "Insurer: Test Assurance",
        "Plan Name: Family Care Plus",
        "Policy Number: TST-POLICY-7788",
        "Policyholder: Asha Rao",
        "Policy Period: 01/04/2025 to 31/03/2027",
        "Sum Insured: 6,00,000",
        "Deductible: 10,000",
        "Co-insurance: 15%",
        "Out of Pocket Maximum: 75,000",
        "Pre-authorisation threshold: 40,000",
        "Waiting Period: 30 days",
        "Network: Cashless at network hospitals",
        "Exclusions",
        "Home traction and durable equipment",
        "Cosmetic surgery",
    ]
    height = 800
    pdf.setFont("Helvetica", 10)
    for line in lines:
        pdf.drawString(50, height, line)
        height -= 20
    pdf.save()


def test_policy_pdf_extraction_and_versioning(client: TestClient):
    headers = register(client, "policy-pdf@example.com")
    family_id, members, policy_id, _ = make_household(client, headers)
    path = Path("/tmp/duco-policy-fixture.pdf")
    _policy_pdf(path)
    with path.open("rb") as handle:
        uploaded = client.post(
            "/api/documents/upload",
            data={"family_id": str(family_id), "doc_type": "policy"},
            files={"file": ("policy.pdf", handle, "application/pdf")},
            headers=headers,
        ).json()["document"]
    assert uploaded["doc_type"] == "policy"
    assert uploaded["method"] == "pdf_text"
    extracted = client.post(
        "/api/policies/extract", json={"document_id": uploaded["id"]}, headers=headers
    ).json()
    assert extracted["basics"]["insurer_name"] == "Test Assurance"
    assert extracted["basics"]["policy_number"] == "TST-POLICY-7788"
    assert extracted["terms"]["sum_insured"] == "600000.00"
    assert extracted["terms"]["deductible"] == "10000.00"
    assert extracted["terms"]["coinsurance_member"] == "0.1500"
    assert extracted["confidence"]["policy_number"] > 0.8
    assert "insurer" not in extracted["missing"]

    # Editing benefit terms must create a new version, not mutate the old one.
    before = client.get(f"/api/policies/{policy_id}", headers=headers).json()
    old_version = before["current_version"]["version"]
    updated = client.patch(
        f"/api/policies/{policy_id}",
        json={
            "terms": {
                **before["current_version"]["terms"],
                "deductible": "20000",
                "coinsurance_member": "0.1",
                "deductible_used": "0",
            },
            "change_note": "Annual renewal terms",
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    after = updated.json()
    assert after["current_version"]["version"] == old_version + 1
    assert after["current_version"]["terms"]["deductible"] == "20000.00"
    assert len(after["versions"]) == old_version + 1
    # The earlier version is still readable and unchanged.
    assert after["versions"][0]["terms"]["deductible"] == "10000.00"
    assert after["version_count"] == old_version + 1
