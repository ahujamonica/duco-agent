"""Read models for the API: results, audit trace, gaps and the what-if simulator."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from duco_agent.engines.coordination import (
    OrderDecision,
    adjudicate_claim,
    money,
    primary_only_totals,
)

from ..models import (
    Adjudication,
    AgentEvent,
    Case,
    Claim,
    EligibilityCheck,
    Family,
    FamilyMember,
    Policy,
    PolicyVersion,
    Preauthorization,
    Report,
    SimulatorRun,
)
from .coverage import claim_input, selected_policies, version_for

DISCLAIMER = (
    "Calculations use the policy terms stored for this case. Insurer responses are simulated. "
    "This is an estimate for planning, not a guarantee of payment."
)


def _s(value: Any) -> str:
    return str(money(value))


def case_summary(case: Case, family: Family | None = None) -> dict:
    totals = case.totals or {}
    return {
        "id": case.id,
        "title": case.title,
        "status": case.status,
        "family_id": case.family_id,
        "family": family.name if family else None,
        "provider": case.provider_name,
        "service_date": case.service_date.isoformat() if case.service_date else None,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        "completed_at": case.completed_at.isoformat() if case.completed_at else None,
        "coordination_rule": case.coordination_rule,
        "totals": {
            "billed": totals.get("billed", "0.00"),
            "insurer_paid": totals.get("insurer_paid", "0.00"),
            "primary_paid": totals.get("primary_paid", "0.00"),
            "secondary_paid": totals.get("secondary_paid", "0.00"),
            "patient_liability": totals.get("patient_liability", "0.00"),
            "claims": totals.get("claims", 0),
        },
    }


def build_results(db: Session, case: Case) -> dict:
    family = db.get(Family, case.family_id)
    state = case.workflow_state or {}
    claim_results = state.get("claim_results") or {}
    claims = db.query(Claim).filter(Claim.case_id == case.id).order_by(Claim.id).all()
    preauths = (
        db.query(Preauthorization).filter(Preauthorization.case_id == case.id).order_by(Preauthorization.id).all()
    )
    reports = db.query(Report).filter(Report.case_id == case.id).order_by(Report.id).all()
    eligibility = db.query(EligibilityCheck).filter(EligibilityCheck.case_id == case.id).all()

    claims_out = []
    for claim in claims:
        stored = claim_results.get(str(claim.id)) or {}
        lines = []
        for line in stored.get("lines") or []:
            lines.append(
                {
                    "id": line.get("line_id"),
                    "description": line.get("description"),
                    "cpt_code": line.get("cpt_code"),
                    "category": line.get("category"),
                    "billed": line.get("billed"),
                    "allowed": line.get("allowed"),
                    "contractual": line.get("contractual"),
                    "excluded": line.get("excluded"),
                    "patient": line.get("patient"),
                    "patient_parts": line.get("patient_parts"),
                    "plans": line.get("plans"),
                    "notes": line.get("notes"),
                }
            )
        claim_out = {
            "id": claim.id,
            "patient": claim.patient_name,
            "member_id": claim.member_id,
            "provider": claim.provider_name,
            "service_date": claim.service_date.isoformat() if claim.service_date else None,
            "bill_number": claim.bill_number,
            "document_id": claim.document_id,
            "totals": stored.get("totals") or {},
            "order": stored.get("order") or [],
            "plans": stored.get("plans") or [],
            "lines": lines,
            "warnings": stored.get("warnings") or [],
            "assumptions": stored.get("assumptions") or [],
            "invariants": stored.get("invariants") or [],
        }
        claims_out.append(claim_out)

    accumulators = []
    from .accumulators import get_accumulator

    for policy, version in selected_policies(db, case):
        for link in policy.member_links:
            member = db.get(FamilyMember, link.member_id)
            if not member:
                continue
            accumulator = get_accumulator(db, policy, version, member.id)
            sublimits = []
            for item in version.sublimits or []:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or item.get("label"))
                sublimits.append(
                    {
                        "key": key,
                        "label": item.get("label"),
                        "limit": _s(item.get("limit")),
                        "used": _s((accumulator.sublimits or {}).get(key, 0)),
                        "basis": item.get("basis") or "per_year",
                    }
                )
            accumulators.append(
                {
                    "policy_id": policy.id,
                    "version_id": version.id,
                    "version": version.version,
                    "insurer": policy.insurer_name,
                    "plan_name": policy.plan_name,
                    "policy_number": policy.policy_number,
                    "status": policy.status,
                    "member_id": member.id,
                    "member": member.name,
                    "role": link.role,
                    "deductible": _s(version.deductible),
                    "deductible_used": _s(accumulator.deductible_used),
                    "coinsurance_member": str(version.coinsurance_member),
                    "oop_max": _s(version.oop_max),
                    "oop_used": _s(accumulator.oop_used),
                    "annual_limit": _s(version.annual_limit),
                    "annual_limit_used": _s(accumulator.annual_limit_used),
                    "sublimits": sublimits,
                }
            )

    letters_by_policy = {}
    for report in reports:
        if report.kind == "pdf_letter" and report.meta.get("policy_id"):
            letters_by_policy[int(report.meta["policy_id"])] = report.id

    preauth_out = []
    for item in preauths:
        policy = db.get(Policy, item.policy_id)
        preauth_out.append(
            {
                "id": item.id,
                "claim_id": item.claim_id,
                "policy_id": item.policy_id,
                "insurer": policy.insurer_name if policy else None,
                "plan_name": policy.plan_name if policy else None,
                "policy_number": policy.policy_number if policy else None,
                "required": item.required,
                "status": item.status,
                "reference": item.reference,
                "reason": item.reason,
                "response": item.response,
                "letter_report_id": letters_by_policy.get(item.policy_id),
            }
        )

    losses = state.get("claim_results") or {}
    savings = []
    for claim_id, stored in losses.items():
        ordered = stored.get("order") or []
        if len(ordered) > 1:
            totals = stored.get("totals") or {}
            primary = next((p for p in stored.get("plans") or [] if p.get("role") == "primary"), None)
            if primary:
                without = money(totals.get("billed", 0)) - money(primary.get("plan_paid", 0)) - money(
                    totals.get("contractual_adjustment", 0)
                )
                savings.append(
                    {
                        "claim_id": int(claim_id),
                        "without_coordination": _s(without),
                        "with_coordination": totals.get("patient_liability", "0.00"),
                        "saving": _s(without - money(totals.get("patient_liability", 0))),
                    }
                )

    return {
        "case": case_summary(case, family),
        "totals": case.totals or {},
        "claims": claims_out,
        "accumulators": accumulators,
        "preauth": preauth_out,
        "eligibility": [
            {
                "policy_id": item.policy_id,
                "status": item.status,
                "response": item.response,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in eligibility
        ],
        "gaps": state.get("gaps") or [],
        "assumptions": state.get("assumptions") or [],
        "savings": savings,
        "invariants": state.get("invariants") or [],
        "reports": [
            {
                "id": report.id,
                "kind": report.kind,
                "title": report.title,
                "mime": report.mime,
                "created_at": report.created_at.isoformat() if report.created_at else None,
                "meta": report.meta or {},
            }
            for report in reports
        ],
        "audit": {
            "events": db.query(AgentEvent).filter(AgentEvent.case_id == case.id).count(),
            "adjudications": db.query(Adjudication).filter(Adjudication.case_id == case.id).count(),
            "api_calls": db.query(EligibilityCheck).filter(EligibilityCheck.case_id == case.id).count(),
            "simulated": True,
        },
        "disclaimer": DISCLAIMER,
    }


def build_trace(db: Session, case: Case, since: int = 0, limit: int = 400) -> dict:
    query = db.query(AgentEvent).filter(AgentEvent.case_id == case.id, AgentEvent.seq > since).order_by(AgentEvent.seq)
    events = query.limit(limit).all()
    return {
        "case_id": case.id,
        "status": case.status,
        "run_id": case.run_token,
        "stage": (case.workflow_state or {}).get("stage"),
        "tasks": (case.workflow_state or {}).get("tasks") or {},
        "events": [
            {
                "seq": event.seq,
                "agent": event.agent,
                "goal": event.goal,
                "state": event.state,
                "action": event.action,
                "tool": event.tool,
                "inputs": event.inputs,
                "observation": event.observation,
                "checks": event.checks,
                "decision": event.decision,
                "next_action": event.next_action,
                "status": event.status,
                "started_at": event.started_at.isoformat() if event.started_at else None,
                "duration_ms": event.duration_ms,
                "run_id": event.run_id,
            }
            for event in events
        ],
        "last_seq": events[-1].seq if events else since,
        "simulated": True,
    }


def explain_line(db: Session, case: Case, line_id: int) -> dict | None:
    state = case.workflow_state or {}
    for claim_id, claim in (state.get("claim_results") or {}).items():
        for line in claim.get("lines") or []:
            if int(line.get("line_id") or 0) == int(line_id):
                billed = money(line.get("billed", 0))
                plans = line.get("plans") or []
                payment = sum((money(p.get("plan_paid", 0)) for p in plans), money(0))
                contractual = money(line.get("contractual", 0))
                return {
                    "line": line,
                    "claim_id": int(claim_id),
                    "patient": claim.get("patient"),
                    "calculation": {
                        "billed": _s(billed),
                        "contractual_adjustment": _s(contractual),
                        "allowed": line.get("allowed"),
                        "insurer_payments": _s(payment),
                        "patient": line.get("patient"),
                        "check": _s(payment + money(line.get("patient", 0)) + contractual) == _s(billed),
                    },
                    "steps": _explain_steps(line, contractual),
                }
    return None


def _explain_steps(line: dict, contractual: Decimal) -> list[dict]:
    steps = [
        {
            "label": "Billed by the provider",
            "amount": line.get("billed"),
            "explanation": "The amount printed on the bill for this service line.",
        }
    ]
    if contractual > 0:
        steps.append(
            {
                "label": "Contractual adjustment",
                "amount": _s(-contractual),
                "explanation": "The difference between the bill and the insurer's agreed rate. The provider writes it off.",
            }
        )
    for plan in line.get("plans") or []:
        role = plan.get("role")
        if plan.get("excluded") and money(plan.get("excluded", 0)) > 0:
            steps.append(
                {
                    "label": f"{role.title()} insurer: excluded",
                    "amount": _s(-money(plan.get("excluded", 0))),
                    "explanation": "; ".join(plan.get("notes") or []) or "This policy does not cover this service.",
                }
            )
            continue
        if plan.get("sublimit_excess") and money(plan["sublimit_excess"]) > 0:
            steps.append(
                {
                    "label": f"{role.title()} insurer: above sub-limit",
                    "amount": _s(-money(plan["sublimit_excess"])),
                    "explanation": "This part of the line is above the policy's sub-limit.",
                }
            )
        steps.append(
            {
                "label": f"{role.title()} insurer: deductible",
                "amount": _s(-money(plan.get("deductible", 0))),
                "explanation": "The part of the allowed amount applied to the remaining deductible.",
            }
        )
        steps.append(
            {
                "label": f"{role.title()} insurer: coinsurance",
                "amount": _s(-money(plan.get("coinsurance", 0))),
                "explanation": "The member's share after the deductible.",
            }
        )
        if money(plan.get("penalty", 0)) > 0:
            steps.append(
                {
                    "label": f"{role.title()} insurer: pre-auth penalty",
                    "amount": _s(-money(plan.get("penalty", 0))),
                    "explanation": "Payment reduced because pre-authorisation was not approved.",
                }
            )
        steps.append(
            {
                "label": f"{role.title()} insurer pays",
                "amount": _s(money(plan.get("plan_paid", 0))),
                "explanation": "What this insurer pays after its deductible and coinsurance.",
            }
        )
    steps.append(
        {
            "label": "You pay",
            "amount": line.get("patient"),
            "explanation": "The amount left after every coordinated insurer payment and adjustment.",
        }
    )
    return steps


def build_gaps(db: Session, case: Case) -> dict:
    state = case.workflow_state or {}
    gaps = list(state.get("gaps") or [])
    claims = db.query(Claim).filter(Claim.case_id == case.id).all()
    for claim in claims:
        if not any(line.icd_codes for line in claim.lines):
            gaps.append(
                {
                    "code": f"missing_diagnosis_{claim.id}",
                    "severity": "action",
                    "title": "Diagnosis code missing",
                    "detail": f"{claim.patient_name}'s claim has no ICD-10 code, which most pre-authorisations require.",
                    "action": "Attach the radiology report or discharge summary, or enter the code during review.",
                }
            )
        for line in claim.lines:
            if line.category == "equipment" and not any(g.get("title", "").startswith(line.description[:20]) for g in gaps):
                gaps.append(
                    {
                        "code": f"equipment_{line.id}",
                        "severity": "info",
                        "title": f"Check cover for {line.description[:48]}",
                        "detail": "Equipment is commonly excluded. The engine applies each policy's exclusion list.",
                        "action": "Keep the invoice; you may have to pay this line yourself.",
                    }
                )
    deduped = []
    seen = set()
    for gap in gaps:
        key = (gap.get("code"), gap.get("title"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(gap)
    return {"gaps": deduped, "assumptions": state.get("assumptions") or []}


def simulate(db: Session, case: Case, overrides: dict) -> dict:
    """Run a hypothetical calculation; never mutates the stored claim."""
    claims = db.query(Claim).filter(Claim.case_id == case.id).order_by(Claim.id).all()
    if not claims:
        return {"error": "This case has no claims to simulate."}
    selected = selected_policies(db, case)
    state = case.workflow_state or {}
    orders = state.get("orders") or {}
    preauths = {
        (item.policy_id): item.status
        for item in db.query(Preauthorization).filter(Preauthorization.case_id == case.id).all()
    }
    claim_outputs = []
    totals = {
        "billed": money(0),
        "allowed": money(0),
        "contractual_adjustment": money(0),
        "insurer_paid": money(0),
        "patient_liability": money(0),
    }
    for claim in claims:
        member = db.get(FamilyMember, claim.member_id) if claim.member_id else None
        if not member:
            continue
        decisions = []
        plans = []
        for decision in orders.get(str(claim.id)) or []:
            policy_id = int(decision["plan_key"].split("V")[0].lstrip("P"))
            policy = db.get(Policy, policy_id)
            if not policy:
                continue
            version = version_for(db, policy, None)
            link = next((l for l in policy.member_links if l.member_id == member.id), None)
            from .accumulators import get_accumulator
            from .coverage import plan_from_version

            accumulator = get_accumulator(db, policy, version, member.id)
            plan = plan_from_version(policy, version, link, case.coordination_rule, accumulator)
            policy_override = (overrides.get("policies") or {}).get(str(policy.id)) or {}
            if policy_override:
                if "deductible" in policy_override:
                    plan.deductible_total = money(policy_override["deductible"])
                    plan.deductible_used = min(plan.deductible_used, plan.deductible_total)
                if "coinsurance_member" in policy_override:
                    plan.coinsurance_member = Decimal(str(policy_override["coinsurance_member"]))
                if "oop_max" in policy_override:
                    plan.oop_max = money(policy_override["oop_max"])
                if "annual_limit" in policy_override:
                    plan.annual_limit = money(policy_override["annual_limit"])
                if "allowed_factor" in policy_override:
                    plan.allowed_factor = Decimal(str(policy_override["allowed_factor"]))
            plans.append(plan)
            decisions.append(
                OrderDecision(
                    plan_key=plan.key,
                    role=decision["role"],
                    order=decision["order"],
                    rule=decision.get("rule") or case.coordination_rule,
                    evidence=["hypothetical override"],
                    assumption="This is a simulation; the stored claim is unchanged.",
                )
            )
        if not plans:
            continue
        result = adjudicate_claim(
            claim_input(claim, case.service_date),
            plans,
            decisions,
            {p.key: preauths.get(p.policy_id) == "approved" for p in plans},
            provider_in_network=case.provider_in_network,
        )
        for key in totals:
            totals[key] += result.totals[key]
        claim_outputs.append(
            {
                "claim_id": claim.id,
                "patient": claim.patient_name,
                "totals": {k: str(v) for k, v in result.totals.items()},
                "plans": [
                    {
                        "insurer": p.insurer,
                        "role": p.role,
                        "plan_paid": str(p.plan_paid),
                    }
                    for p in result.plans
                ],
                "invariants": [i.to_dict() for i in result.invariants],
            }
        )
    baseline = {
        "patient_liability": (case.totals or {}).get("patient_liability", "0.00"),
        "insurer_paid": (case.totals or {}).get("insurer_paid", "0.00"),
    }
    simulated = {key: str(value) for key, value in totals.items()}
    record = SimulatorRun(
        case_id=case.id,
        overrides=overrides,
        result={"claims": claim_outputs, "totals": simulated},
    )
    db.add(record)
    db.commit()
    return {
        "simulated": True,
        "hypothetical": True,
        "case_id": case.id,
        "baseline": baseline,
        "result": {**simulated, "claims": claim_outputs},
        "difference": {
            "patient_liability": str(money(simulated["patient_liability"]) - money(baseline["patient_liability"])),
            "insurer_paid": str(money(simulated["insurer_paid"]) - money(baseline["insurer_paid"])),
        },
        "note": "This what-if run is hypothetical and does not change the stored claim.",
        "run_id": record.id,
    }


def dashboard(db: Session, user_id: int) -> dict:
    families = db.query(Family).filter(Family.owner_id == user_id).all()
    family_ids = [f.id for f in families]
    cases = (
        db.query(Case).filter(Case.family_id.in_(family_ids)).order_by(Case.updated_at.desc()).all()
        if family_ids
        else []
    )
    total_billed = money(0)
    insurer_paid = money(0)
    primary_paid = money(0)
    secondary_paid = money(0)
    patient = money(0)
    pending_auth = 0
    active = 0
    attention = []
    for case in cases:
        totals = case.totals or {}
        total_billed += money(totals.get("billed", 0))
        insurer_paid += money(totals.get("insurer_paid", 0))
        primary_paid += money(totals.get("primary_paid", 0))
        secondary_paid += money(totals.get("secondary_paid", 0))
        patient += money(totals.get("patient_liability", 0))
        if case.status in ("running", "ready", "queued"):
            active += 1
        for item in db.query(Preauthorization).filter(
            Preauthorization.case_id == case.id,
            Preauthorization.status.in_(["pending", "submitted", "required"]),
        ):
            pending_auth += 1
        if case.status in ("awaiting_review", "failed"):
            attention.append(
                {
                    "case_id": case.id,
                    "title": case.title,
                    "status": case.status,
                    "detail": "Review the extracted fields."
                    if case.status == "awaiting_review"
                    else "The run needs attention.",
                }
            )
    recent = [case_summary(case, db.get(Family, case.family_id)) for case in cases[:6]]
    return {
        "totals": {
            "cases": len(cases),
            "families": len(families),
            "active_claims": active,
            "pending_authorizations": pending_auth,
            "billed": str(total_billed),
            "insurer_paid": str(insurer_paid),
            "primary_paid": str(primary_paid),
            "secondary_paid": str(secondary_paid),
            "patient_responsibility": str(patient),
        },
        "recent_cases": recent,
        "attention": attention,
        "simulated": True,
    }
