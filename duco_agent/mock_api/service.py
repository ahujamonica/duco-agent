"""In-memory implementation of the two mock insurer APIs.

The same handler functions back both the in-process client (used by the demo
and the tests) and the HTTP server in ``server.py``, so the behavioural story is
identical whether or not a port is open.
"""

from __future__ import annotations

import itertools
from datetime import datetime
from typing import Any

from ..config import ACCUMULATORS, MEMBERS, PLANS
from ..engines.cob_engine import adjudicate, preauth_required
from ..models import Claim, LineCategory, ServiceLine, money

_claim_ids = itertools.count(1001)
_preauth_store: dict[str, dict] = {}
_claim_store: dict[str, dict] = {}


def _serialise(obj):
    if isinstance(obj, dict):
        return {key: _serialise(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_serialise(value) for value in obj]
    if hasattr(obj, "to_dict"):
        return _serialise(obj.to_dict())
    return obj


def get_plan(plan_id: str) -> dict:
    plan = PLANS.get(plan_id)
    if not plan:
        return {"error": f"unknown plan {plan_id}"}
    return _serialise(plan.to_dict())


def list_plans() -> dict:
    return {"plans": [_serialise(plan.to_dict()) for plan in PLANS.values()]}


def get_member(member_id: str) -> dict:
    member = MEMBERS.get(member_id)
    if not member:
        return {"error": f"unknown member {member_id}"}
    return {"member_id": member_id, **_serialise(member)}


def check_eligibility(plan_id: str, member_id: str) -> dict:
    plan = PLANS.get(plan_id)
    if not plan or member_id not in MEMBERS:
        return {"eligible": False, "reason": "member or plan not found"}
    member = MEMBERS[member_id]
    role = member.get("plan_a_role") if plan_id == "PLAN_A" else member.get("plan_b_role")
    return {
        "eligible": True,
        "plan_id": plan_id,
        "member_id": member_id,
        "role": role,
        "policy_status": "active",
        "benefit_year": 2026,
        "network": "cashless" if plan_id == "PLAN_A" else "reimbursement",
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


def get_benefits(plan_id: str, member_id: str) -> dict:
    """Return plan terms plus this member's year-to-date accumulators."""
    plan = PLANS.get(plan_id)
    accumulator = ACCUMULATORS.get((plan_id, member_id))
    if not plan or not accumulator:
        return {"error": "plan or member accumulator not found"}
    return {
        "plan": _serialise(plan.to_dict()),
        "accumulators": _serialise(accumulator.to_dict()),
        "deductible_remaining": str(money(plan.deductible_per_member - accumulator.deductible_used)),
        "oop_remaining": str(money(plan.oop_max_per_member - accumulator.oop_used)),
    }


def submit_preauth(plan_id: str, member_id: str, claim_id: str, payload: dict | None = None) -> dict:
    plan = PLANS.get(plan_id)
    if not plan:
        return {"status": "rejected", "reason": "unknown plan"}
    reference = f"PA-{plan_id[-1]}-{next(_claim_ids):05d}"
    record = {
        "preauth_id": reference,
        "plan_id": plan_id,
        "member_id": member_id,
        "claim_id": claim_id,
        "status": "approved",
        "valid_until": "2027-03-31",
        "submitted_at": datetime.now().isoformat(timespec="seconds"),
        "payload_summary": payload or {},
    }
    _preauth_store[reference] = record
    return {"status": "approved", "preauth_id": reference, "valid_until": record["valid_until"]}


def get_preauth(preauth_id: str) -> dict:
    return _preauth_store.get(preauth_id, {"error": "preauth not found"})


def _claim_from_payload(payload: dict) -> Claim:
    lines = []
    for item in payload.get("lines", []):
        category = item.get("category", "professional")
        lines.append(
            ServiceLine(
                description=item["description"],
                quantity=int(item.get("quantity", 1) or 1),
                unit_rate=money(item.get("unit_rate") or item.get("billed_amount") or 0),
                billed_amount=money(item.get("billed_amount") or 0),
                cpt_code=item.get("cpt_code"),
                icd_codes=list(item.get("icd_codes", [])),
                category=LineCategory(category),
                non_covered=bool(item.get("non_covered", False)),
            )
        )
    from datetime import date

    return Claim(
        claim_id=payload.get("claim_id", f"CLM-{next(_claim_ids)}"),
        patient_name=payload.get("patient_name", ""),
        member_id=payload["member_id"],
        provider_name=payload.get("provider_name", ""),
        service_date=date.fromisoformat(payload.get("service_date", "2026-11-26")),
        lines=lines,
    )


def submit_claim(payload: dict) -> dict:
    """Adjudicate one claim under one plan (no COB: this is the plan's own view)."""
    claim = _claim_from_payload(payload)
    plan_id = payload["plan_id"]
    plan = PLANS[plan_id]
    accumulator = ACCUMULATORS[(plan_id, claim.member_id)]
    preauth_ok = bool(payload.get("preauth_obtained", False)) or not preauth_required(claim, plan)
    adjudication, _ = adjudicate(claim, plan, accumulator, preauth_obtained=preauth_ok, role="primary")
    record = {
        "claim_id": claim.claim_id,
        "plan_id": plan_id,
        "status": "adjudicated",
        "paid_amount": str(adjudication.plan_paid),
        "member_responsibility": str(adjudication.member_paid),
        "preauth_required": preauth_required(claim, plan),
        "preauth_obtained": preauth_ok,
        "adjudication": _serialise(adjudication.to_dict()),
    }
    _claim_store[claim.claim_id] = record
    return record


def get_claim(claim_id: str) -> dict:
    return _claim_store.get(claim_id, {"error": "claim not found"})


HANDLERS: dict[str, Any] = {
    "plans": lambda **kw: list_plans(),
    "plan": lambda plan_id, **kw: get_plan(plan_id),
    "member": lambda member_id, **kw: get_member(member_id),
    "eligibility": lambda plan_id, member_id, **kw: check_eligibility(plan_id, member_id),
    "benefits": lambda plan_id, member_id, **kw: get_benefits(plan_id, member_id),
    "preauth": lambda plan_id, member_id, claim_id, payload=None, **kw: submit_preauth(plan_id, member_id, claim_id, payload),
    "claim": lambda payload, **kw: submit_claim(payload),
    "claim_status": lambda claim_id, **kw: get_claim(claim_id),
}

PATHS = {
    "/plans": ("plans", []),
    "/eligibility": ("eligibility", ["plan_id", "member_id"]),
    "/benefits": ("benefits", ["plan_id", "member_id"]),
    "/preauth": ("preauth", ["plan_id", "member_id", "claim_id"]),
    "/claim": ("claim", []),
    "/claim/status": ("claim_status", ["claim_id"]),
}
