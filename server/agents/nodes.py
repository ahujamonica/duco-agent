"""Specialist agent nodes for the DuCO workflow.

Each node is a function ``(RunContext) -> "done" | "pause" | "failed"``. Nodes
call real tools (OCR, PDF parsing, the mock insurer API, the deterministic
engine) and log every observation to the case trace. No node calculates the
final patient share itself: only the Financial Calculation Agent calls the
engine.
"""

from __future__ import annotations

import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from duco_agent.codes import suggest_cpt
from duco_agent.engines.coordination import OrderDecision, adjudicate_claim, preauth_requirement

from ..models import (
    Adjudication,
    Case,
    Claim,
    ClaimLine,
    Document,
    EligibilityCheck,
    Family,
    FamilyMember,
    Policy,
    PolicyVersion,
    Preauthorization,
    ReviewItem,
    utcnow,
)
from ..services import reports as report_service
from ..services.accumulators import get_accumulator
from ..services.coverage import (
    claim_input,
    determine_order,
    member_policies_for_claim,
    plan_from_version,
    selected_policies,
    version_for,
)
from ..config import UPLOAD_DIR
from ..services.document_intel import analyse_file
from ..services.insurer_mock import MockInsurerService
from .runtime import RunContext

REVIEW_THRESHOLD = 0.72
CRITICAL_FIELDS = {
    "invoice": ["patient", "total", "service_date"],
    "estimate": ["patient", "total", "service_date"],
    "policy": ["insurer", "policy_number", "sum_insured", "coinsurance_member"],
    "radiology": ["patient"],
    "prescription": ["patient"],
    "discharge": ["patient"],
    "unknown": ["_document"],
}


def _family(ctx: RunContext) -> Family:
    family = ctx.db.get(Family, ctx.case.family_id)
    if not family:
        raise ValueError("Family not found")
    return family


def _lead_member(ctx: RunContext) -> FamilyMember:
    member = ctx.db.get(FamilyMember, ctx.case.patient_member_id)
    if not member:
        family = _family(ctx)
        if not family.members:
            raise ValueError("This family has no members yet.")
        member = family.members[0]
    return member


def _normalise(name: str | None) -> str:
    return re.sub(r"[^a-z ]", "", (name or "").lower()).strip()


def _match_member(name: str | None, members: list[FamilyMember]) -> tuple[FamilyMember | None, float]:
    if not name:
        return None, 0.0
    target = _normalise(name)
    if not target:
        return None, 0.0
    for member in members:
        candidate = _normalise(member.name)
        if target == candidate:
            return member, 0.98
        if target and candidate and (target in candidate or candidate in target):
            return member, 0.9
    # Fall back to a token overlap score.
    target_tokens = set(target.split())
    best = (None, 0.0)
    for member in members:
        tokens = set(_normalise(member.name).split())
        overlap = len(target_tokens & tokens) / max(1, len(target_tokens | tokens))
        if overlap > best[1]:
            best = (member, round(overlap, 2))
    return best if best[1] >= 0.5 else (None, best[1])


def _claim_docs(ctx: RunContext) -> list[Document]:
    ids = [int(i) for i in (ctx.case.document_ids or [])]
    if not ids:
        return []
    return ctx.db.query(Document).filter(Document.id.in_(ids)).order_by(Document.id).all()


def _positive_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed > 0 else None


def _positive_quantity(value: object) -> int | None:
    parsed = _positive_decimal(value)
    if parsed is None or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


def intake_node(ctx: RunContext) -> str:
    started = time.perf_counter()
    family = _family(ctx)
    lead = _lead_member(ctx)
    documents = _claim_docs(ctx)
    policies = selected_policies(ctx.db, ctx.case)
    if not policies:
        all_policies = (
            ctx.db.query(Policy).filter(Policy.family_id == family.id).order_by(Policy.id).all()
        )
        auto = [p.current_version.id for p in all_policies if p.current_version]
        if auto:
            ctx.case.policy_version_ids = auto
            ctx.db.add(ctx.case)
            ctx.db.commit()
            policies = selected_policies(ctx.db, ctx.case)
            ctx.assume(
                "No policies were selected on the case, so every policy in the household was included."
            )
    docs_summary = [
        {"id": doc.id, "filename": doc.original_filename, "type": doc.doc_type, "status": doc.status}
        for doc in documents
    ]
    ctx.save(
        members=[{"id": m.id, "name": m.name, "relationship": m.relation} for m in family.members],
        policy_count=len(policies),
        document_ids=[doc.id for doc in documents],
    )
    checks = [
        {"name": "Family has members", "passed": bool(family.members), "detail": f"{len(family.members)} member(s)"},
        {"name": "At least one policy is available", "passed": bool(policies), "detail": f"{len(policies)} policy version(s)"},
        {"name": "At least one source document or manual bill", "passed": bool(documents) or bool((ctx.case.workflow_state or {}).get("manual_lines")), "detail": f"{len(documents)} document(s)"},
        {"name": "Lead patient is a family member", "passed": lead is not None, "detail": lead.name if lead else "missing"},
    ]
    ctx.emit(
        "Intake Agent",
        "intake",
        "assemble_case",
        tool="database",
        inputs={
            "case": ctx.case.title,
            "family": family.name,
            "lead_patient": lead.name,
            "documents": docs_summary,
            "policies": len(policies),
            "coordination_rule": ctx.case.coordination_rule,
        },
        observation=(
            f"Case '{ctx.case.title}' for {lead.name} includes {len(documents)} document(s) and "
            f"{len(policies)} policy version(s)."
        ),
        checks=checks,
        decision="Proceed to document intelligence." if all(c["passed"] for c in checks) else "Ask for the missing input.",
        next_action="documents",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    if not policies:
        ctx.gap(
            "no_policy",
            "blocking",
            "No insurance policy is available",
            "Add at least one policy for this household before the claim can be coordinated.",
            "Open Policies and add the policy schedule.",
        )
        ctx.save()
        return "pause"
    ctx.resolve_gap("no_policy")
    if not documents and not (ctx.case.workflow_state or {}).get("manual_lines"):
        ctx.gap(
            "no_documents",
            "blocking",
            "Attach a bill or estimate",
            "No medical bill, estimate or manually entered service line is attached to this case.",
            "Upload the hospital bill or surgeon's estimate.",
        )
        ctx.save()
        return "pause"
    ctx.resolve_gap("no_documents")
    if not family.members:
        ctx.gap("no_members", "blocking", "Add family members", "A claim needs at least one covered person.", "Open Family.")
        ctx.save()
        return "pause"
    ctx.resolve_gap("no_members")
    return "done"


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def _review_candidates(doc: Document) -> list[dict]:
    fields = doc.fields or {}
    items: list[dict] = []
    for key in CRITICAL_FIELDS.get(doc.doc_type, ["patient"]):
        field = fields.get(key) or {}
        status = field.get("status")
        if status in ("missing", "review"):
            value = field.get("value")
            items.append(
                {
                    "field_key": key,
                    "label": key.replace("_", " ").title(),
                    "value": "" if value is None else str(value),
                    "confidence": float(field.get("confidence") or 0),
                    "source_text": field.get("evidence") or "",
                    "reason": (
                        f"Confidence {float(field.get('confidence') or 0):.0%} is below the {REVIEW_THRESHOLD:.0%} "
                        "review threshold"
                        if status == "review"
                        else "This required field was not found in the document"
                    ),
                }
            )
    return items


def _line_review_items(doc: Document) -> list[dict]:
    items: list[dict] = []
    lines = doc.fields.get("_lines") if isinstance(doc.fields, dict) else None
    # Lines are stored separately by the API in document meta; fall back to the
    # parsed lines kept under the `_lines` key when present.
    if not lines:
        return items
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            continue
        code_source = (line.get("code") or {}).get("source") or line.get("code_source")
        confidence = float((line.get("code") or {}).get("confidence") or line.get("code_confidence") or 0)
        if code_source == "inferred" or (
            bool(line.get("cpt_code")) and confidence < 0.7
        ):
            items.append(
                {
                    "field_key": f"line:{index}:cpt",
                    "label": f"Procedure code — {line.get('description') or 'service line'}",
                    "value": line.get("cpt_code") or "",
                    "confidence": confidence if code_source != "unavailable" else 0.0,
                    "source_text": line.get("evidence") or "",
                    "reason": (
                        "The code was inferred from the description and must be confirmed"
                        if code_source == "inferred"
                        else "No code could be matched; enter the correct CPT/HCPCS code"
                    ),
                }
            )
        if line.get("issues") and any("quantity" in str(issue).lower() for issue in line.get("issues") or []):
            items.append(
                {
                    "field_key": f"line:{index}:quantity",
                    "label": f"Quantity — {line.get('description') or 'service line'}",
                    "value": str(line.get("quantity") or ""),
                    "confidence": 0.5,
                    "source_text": line.get("evidence") or "",
                    "reason": "The quantity on the scan is unclear.",
                }
            )
    return items


def _sync_review_items(ctx: RunContext, documents: list[Document]) -> int:
    """Reconcile review candidates without deleting the review history."""
    existing_items = (
        ctx.db.query(ReviewItem)
        .filter(ReviewItem.case_id == ctx.case.id)
        .all()
    )
    existing_by_key = {
        (item.document_id, item.field_key): item for item in existing_items
    }

    pending_count = 0
    candidate_keys: set[tuple[int, str]] = set()

    for doc in documents:
        candidates = _review_candidates(doc)
        candidates += _line_review_items(doc)
        if doc.doc_type == "unknown":
            candidates.append(
                {
                    "field_key": "_document_type",
                    "label": "Document type",
                    "value": "",
                    "confidence": float(doc.classification_confidence or 0),
                    "source_text": "; ".join((doc.issues or [])[:2]),
                    "reason": "The document type could not be identified; choose the right one.",
                }
            )

        for candidate in candidates:
            if candidate["field_key"] == "service_date" and ctx.case.service_date:
                continue
            key = (doc.id, candidate["field_key"])
            candidate_keys.add(key)
            existing = existing_by_key.get(key)

            if existing and existing.status in ("accepted", "corrected"):
                continue

            if existing and existing.status == "pending":
                existing.label = candidate["label"]
                existing.extracted_value = candidate["value"]
                existing.confidence = Decimal(str(round(candidate["confidence"], 3)))
                existing.source_text = candidate["source_text"]
                existing.reason = candidate["reason"]
                ctx.db.add(existing)
            else:
                review_item = ReviewItem(
                    case_id=ctx.case.id,
                    document_id=doc.id,
                    field_key=candidate["field_key"],
                    label=candidate["label"],
                    extracted_value=candidate["value"],
                    confidence=Decimal(str(round(candidate["confidence"], 3))),
                    source_text=candidate["source_text"],
                    reason=candidate["reason"],
                )
                ctx.db.add(review_item)
                existing_by_key[key] = review_item

            pending_count += 1


    ctx.db.commit()
    return pending_count


def _apply_review_results(ctx: RunContext, documents: list[Document]) -> None:
    """Write confirmed/corrected review values back onto the document fields."""
    items = ctx.db.query(ReviewItem).filter(ReviewItem.case_id == ctx.case.id).all()
    for item in items:
        if item.status not in ("accepted", "corrected"):
            continue
        value = item.corrected_value if item.status == "corrected" else item.extracted_value
        doc = next((d for d in documents if d.id == item.document_id), None)
        if not doc:
            continue
        fields = dict(doc.fields or {})
        lines = list(doc.fields.get("_lines") or []) if isinstance(doc.fields, dict) else []
        if item.field_key.startswith("line:"):
            _, index, attr = item.field_key.split(":")
            try:
                line = lines[int(index)]
            except (ValueError, IndexError):
                continue
            if attr == "cpt":
                line["cpt_code"] = str(value).strip() or None
                line["code_source"] = "corrected" if line.get("cpt_code") else "unavailable"
                line["code_confidence"] = 0.99 if line.get("cpt_code") else 0.0
            elif attr == "quantity":
                cleaned = str(value or "").strip()
                try:
                    quantity = int(cleaned) if cleaned else None
                except ValueError:
                    quantity = None
                line["quantity"] = quantity if quantity and quantity > 0 else None
            fields["_lines"] = lines
        elif item.field_key == "_document_type":
            if str(value).strip():
                doc.doc_type = str(value).strip()
        else:
            field = dict(fields.get(item.field_key) or {})
            numeric = item.field_key in {"total", "sum_insured", "deductible", "oop_max", "preauth_threshold"}
            coinsurance = item.field_key == "coinsurance_member"
            clean_value = value
            if numeric:
                try:
                    amount = Decimal(
                        str(value).replace(",", "").replace("₹", "").replace("Rs.", "").replace("INR", "").strip()
                    )
                    clean_value = f"{amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
                except InvalidOperation:
                    clean_value = value
            elif coinsurance:
                try:
                    clean_value = f"{float(str(value).replace('%', '')) / 100:.4f}" if float(str(value).replace('%', '')) > 1 else str(value)
                except ValueError:
                    clean_value = value
            field.update(
                {
                    "value": clean_value,
                    "confidence": 1.0,
                    "source": "reviewed",
                    "status": "ok",
                }
            )
            fields[item.field_key] = field
        doc.fields = fields
        doc.status = "confirmed"
        doc.confirmed_at = doc.confirmed_at or utcnow()
        ctx.db.add(doc)
    ctx.db.commit()


def documents_node(ctx: RunContext) -> str:
    started = time.perf_counter()
    documents = _claim_docs(ctx)
    processed = []
    for doc in documents:
        if doc.status in ("processed", "needs_review", "confirmed") and doc.fields:
            processed.append({"id": doc.id, "cached": True, "type": doc.doc_type, "confidence": float(doc.classification_confidence or 0)})
            continue
        began = time.perf_counter()
        result = analyse_file(
            UPLOAD_DIR / doc.stored_name,
            doc.original_filename,
            hint=doc.doc_type if doc.doc_type not in ("unknown", "", None) else None,
        )
        doc.doc_type = result["doc_type"]
        doc.classification_confidence = Decimal(str(round(result["classification_confidence"], 3)))
        doc.method = result["method"]
        doc.pages = result["pages"]
        doc.mean_ocr_confidence = result["mean_ocr_confidence"]
        doc.raw_text = result["text"][:20000]
        fields = dict(result["fields"])
        fields["_lines"] = result["lines"]
        fields["_classification"] = {
            "confidence": result["classification_confidence"],
            "evidence": result["classification_evidence"],
        }
        doc.fields = fields
        doc.issues = result["issues"]
        doc.status = "needs_review" if result["needs_review"] else "processed"
        ctx.db.add(doc)
        ctx.db.commit()
        processed.append(
            {
                "id": doc.id,
                "filename": doc.original_filename,
                "type": doc.doc_type,
                "method": doc.method,
                "confidence": result["classification_confidence"],
                "ocr_confidence": result["mean_ocr_confidence"],
                "attempts": result["attempts"],
                "lines": len(result["lines"]),
                "issues": result["issues"],
            }
        )
        ctx.emit(
            "Document Intelligence Agent",
            "documents",
            "extract_document",
            tool=f"{result['method']}_pipeline",
            inputs={"document": doc.original_filename, "declared_type": doc.doc_type},
            observation=(
                f"Read {doc.original_filename} as {doc.doc_type} ({result['classification_confidence']:.0%} type "
                f"confidence, {len(result['lines'])} service line(s))."
            ),
            checks=[
                {"name": "Text extracted", "passed": bool(result["text"].strip()), "detail": f"{len(result['text'])} characters"},
                {"name": "Type identified", "passed": result["classification_confidence"] >= 0.6, "detail": doc.doc_type},
                {"name": "Fields need review", "passed": not result["needs_review"], "detail": "; ".join(result["issues"][:2]) or "none"},
            ],
            decision="Send uncertain fields to human review." if result["needs_review"] else "Extraction is confident enough to continue.",
            next_action="review" if result["needs_review"] else "coverage",
            duration_ms=int((time.perf_counter() - began) * 1000),
        )

    manual_lines = (ctx.case.workflow_state or {}).get("manual_lines") or []
    if not documents and not manual_lines:
        ctx.gap("no_documents", "blocking", "No documents", "Attach a bill, estimate or policy document.", "Upload a document.")
        return "pause"
    ctx.resolve_gap("no_documents")

    if ctx.case.review_confirmed:
        _apply_review_results(ctx, documents)

    review_count = 0
    if not ctx.case.review_confirmed:
        review_count = _sync_review_items(ctx, documents)
        if review_count:
            ctx.emit(
                "Document Intelligence Agent",
                "documents",
                "open_human_review",
                inputs={"review_items": review_count},
                observation=f"{review_count} field(s) are missing or below the confidence gate.",
                checks=[{"name": "Confidence gate", "passed": False, "detail": f"{review_count} item(s) awaiting a person"}],
                decision="Pause before adjudication; a person must confirm these values.",
                next_action="awaiting_review",
                status="waiting",
            )
            ctx.gap(
                "review_required",
                "action",
                "Confirm extracted fields",
                f"{review_count} field(s) need confirmation before the claim can be adjudicated.",
                "Open the document review screen and confirm or correct each field.",
            )
            ctx.save(stage="review", documents=processed, review_pending=review_count)
            return "pause"
    else:
        ctx.gaps = [gap for gap in ctx.gaps if gap.get("code") != "review_required"]
        ctx.state["review_pending"] = 0
        ctx.emit(
            "Document Intelligence Agent",
            "documents",
            "review_confirmed",
            observation="The household already confirmed the extracted values for this case.",
            checks=[{"name": "Human review", "passed": True, "detail": "confirmed"}],
            decision="Use the reviewed values and continue.",
            next_action="coverage",
        )

    claims = _build_claims(ctx, documents)
    if claims:
        ctx.resolve_gap("no_claims")
    if any(gap.get("severity") == "blocking" for gap in ctx.gaps):
        ctx.save(documents=processed, documents_processed=True, claims=[c.id for c in claims])
        return "pause"
    ctx.save(documents=processed, documents_processed=True, claims=[c.id for c in claims])
    if not claims:
        ctx.gap(
            "no_claims",
            "blocking",
            "No claim could be built",
            "No invoice, estimate or manual service lines were available to create a claim.",
            "Upload a bill or estimate, or add service lines manually.",
        )
        ctx.emit(
            "Document Intelligence Agent",
            "documents",
            "build_claims",
            observation="No claim could be built from the available documents.",
            checks=[{"name": "Claim created", "passed": False, "detail": "0 claims"}],
            decision="Stop and ask for a bill.",
            next_action="awaiting_review",
            status="failed",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return "pause"
    ctx.emit(
        "Document Intelligence Agent",
        "documents",
        "build_claims",
        tool="database",
        inputs={"documents": [d.id for d in documents]},
        observation=f"Built {len(claims)} claim(s) with {sum(len(c.lines) for c in claims)} service line(s).",
        checks=[
            {"name": "Every claim has a patient", "passed": all(c.member_id for c in claims), "detail": f"{len(claims)} claim(s)"},
            {"name": "Every claim has lines", "passed": all(c.lines for c in claims), "detail": "lines attached"},
        ],
        decision="Continue to eligibility and benefits.",
        next_action="coverage",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return "done"

def _build_claims(ctx: RunContext, documents: list[Document]) -> list[Claim]:
    """Build claims only when document ownership is unambiguous and selected."""

    # Rebuild from scratch so a re-run is deterministic.
    existing = ctx.db.query(Claim).filter(Claim.case_id == ctx.case.id).all()
    for claim in existing:
        ctx.db.query(Adjudication).filter(Adjudication.claim_id == claim.id).delete()
        ctx.db.delete(claim)
    ctx.db.commit()

    family = _family(ctx)
    family_members = {member.id: member for member in family.members}

    workflow_state = dict(ctx.case.workflow_state or {})
    selected_ids = workflow_state.get("selected_member_ids")

    # Backward compatibility with cases created before multi-member selection.
    if not selected_ids:
        selected_ids = [ctx.case.patient_member_id]

    selected_ids = list(dict.fromkeys(int(member_id) for member_id in selected_ids))

    invalid_ids = [member_id for member_id in selected_ids if member_id not in family_members]
    if invalid_ids:
        ctx.gap(
            "invalid_selected_members",
            "blocking",
            "Selected household members are invalid",
            f"These member IDs do not belong to this household: {invalid_ids}.",
            "Reopen the case and select valid household members.",
        )
        return []
    ctx.resolve_gap("invalid_selected_members")

    if not selected_ids:
        ctx.gap(
            "no_selected_members",
            "blocking",
            "No household members selected",
            "At least one household member must be selected before claims can be built.",
            "Reopen the case and select one or more household members.",
        )
        return []
    ctx.resolve_gap("no_selected_members")

    selected_members = {member_id: family_members[member_id] for member_id in selected_ids}

    claims: list[Claim] = []
    diagnosis_by_member: dict[int, list[str]] = {}
    justification_by_member: dict[int, str] = {}

    def match_selected_member(document: Document):
        """Require one exact, unique household-member name match."""
        fields = document.fields or {}
        patient_field = fields.get("patient") or {}
        name = str(patient_field.get("value") or "").strip()
        normalized_name = _normalise(name)

        if not normalized_name:
            return None, "The document does not contain a patient name."

        matches = [
            member
            for member in selected_members.values()
            if _normalise(member.name) == normalized_name
        ]

        if len(matches) == 1:
            ctx.resolve_gap(f"patient_match_{document.id}")
            ctx.resolve_gap(f"document_member_{document.id}")
            return matches[0], None

        if len(matches) > 1:
            return None, f"The patient name '{name}' matches multiple selected members."

        household_matches = [
            member
            for member in family.members
            if _normalise(member.name) == normalized_name
        ]

        if household_matches:
            return None, (
                f"The document identifies {household_matches[0].name}, "
                "but that household member was not selected for this analysis."
            )

        return None, f"The patient name '{name}' does not exactly match a household member."

    # First pass: attach clinical context only to the correct selected member.
    for doc in documents:
        if doc.doc_type in ("radiology", "discharge"):
            member, error = match_selected_member(doc)

            if not member:
                ctx.gap(
                    f"document_member_{doc.id}",
                    "blocking",
                    "Clinical document ownership needs confirmation",
                    f"{doc.original_filename}: {error}",
                    "Correct the patient field during document review, or select the correct household member.",
                )
                continue

            fields = doc.fields or {}
            candidates = (fields.get("diagnosis_candidates") or {}).get("value") or []

            codes = []
            if isinstance(candidates, list):
                codes = [
                    item.get("code")
                    for item in candidates
                    if isinstance(item, dict) and item.get("code")
                ]

            diagnosis_by_member.setdefault(member.id, [])
            for code in codes:
                if code not in diagnosis_by_member[member.id]:
                    diagnosis_by_member[member.id].append(code)

            justification = (fields.get("clinical_justification") or {}).get("value")
            if justification and member.id not in justification_by_member:
                justification_by_member[member.id] = str(justification)[:1500]

        # A transcript/query is household-level context, not a patient claim.
        if doc.doc_type == "transcript" and not ctx.case.narrative:
            query = (doc.fields or {}).get("query") or {}
            ctx.case.narrative = str(query.get("value") or "")[:4000]
            ctx.db.add(ctx.case)
            ctx.db.commit()

    # Second pass: create separate claims for invoices and estimates.
    for doc in documents:
        if doc.doc_type not in ("invoice", "estimate"):
            continue

        fields = doc.fields or {}
        member, error = match_selected_member(doc)

        if not member:
            ctx.gap(
                f"patient_match_{doc.id}",
                "blocking",
                "Invoice or estimate needs patient confirmation",
                f"{doc.original_filename}: {error}",
                "Correct the patient name in document review before running the analysis again.",
            )
            continue

        provider = str(
            (fields.get("provider") or {}).get("value")
            or ctx.case.provider_name
            or ""
        )

        service_date = ctx.case.service_date
        raw_date = (fields.get("service_date") or {}).get("value")

        if raw_date:
            try:
                service_date = date.fromisoformat(str(raw_date))
            except ValueError:
                ctx.gap(
                    f"service_date_{doc.id}",
                    "blocking",
                    "Service date needs confirmation",
                    f"The service date in {doc.original_filename} could not be parsed.",
                    "Correct the service date in case details and run the analysis again.",
                )
                continue

        if service_date is None:
            ctx.gap(
                f"service_date_{doc.id}",
                "blocking",
                "Service date is required",
                f"No service date is available for {doc.original_filename}.",
                "Enter the actual service date in case details before running the analysis again.",
            )
            continue
        ctx.resolve_gap(f"service_date_{doc.id}")

        claim = Claim(
            case_id=ctx.case.id,
            member_id=member.id,
            patient_name=member.name,
            provider_name=provider,
            service_date=service_date,
            bill_number=str((fields.get("bill_number") or {}).get("value") or "") or None,
            document_id=doc.id,
            narrative=(
                justification_by_member.get(member.id)
                or ctx.case.narrative
            ),
        )

        ctx.db.add(claim)
        ctx.db.flush()

        icds = diagnosis_by_member.get(member.id, [])
        lines_added = 0

        for line in fields.get("_lines") or []:
            if not isinstance(line, dict):
                continue

            billed = _positive_decimal(line.get("amount"))
            if billed is None:
                ctx.gap(
                    f"invalid_line_amount_{doc.id}_{len(claim.lines)}",
                    "blocking",
                    "Service line amount is invalid",
                    f"A service line in {doc.original_filename} has an unreadable amount.",
                    "Correct the line amount during document review.",
                )
                continue

            raw_quantity = line.get("quantity")
            known_quantity = _positive_quantity(raw_quantity)
            quantity_known = known_quantity is not None
            quantity = known_quantity or 1

            unit_rate = line.get("unit_rate")
            known_unit_rate = _positive_decimal(unit_rate)
            unit_rate_known = known_unit_rate is not None
            unit = known_unit_rate or Decimal("0")

            ctx.db.add(
                ClaimLine(
                    claim_id=claim.id,
                    description=str(line.get("description") or "Service")[:300],
                    quantity=quantity,
                    quantity_known=quantity_known and quantity > 0,
                    unit_rate=unit,
                    unit_rate_known=unit_rate_known,
                    billed_amount=billed,
                    cpt_code=(
                        str(line.get("cpt_code"))
                        if line.get("cpt_code")
                        else None
                    ),
                    icd_codes=list(
                        dict.fromkeys(
                            list(line.get("icd_codes") or []) + icds
                        )
                    )[:6],
                    category=str(line.get("category") or "professional"),
                    excluded=False,
                    code_confidence=Decimal(
                        str(round(float(line.get("code_confidence") or 0), 3))
                    ),
                    code_source=str(line.get("code_source") or "unavailable"),
                    evidence=str(line.get("evidence") or "")[:1000],
                    note="; ".join(line.get("issues") or [])[:1000] or None,
                )
            )
            lines_added += 1

        if lines_added:
            ctx.resolve_gap(f"no_valid_lines_{doc.id}")
            ctx.db.commit()
            claims.append(claim)
        else:
            ctx.db.delete(claim)
            ctx.db.commit()
            ctx.gap(
                f"no_valid_lines_{doc.id}",
                "blocking",
                "No usable service lines found",
                f"No valid positive-amount service lines could be read from {doc.original_filename}.",
                "Review the extracted service lines and correct the missing or invalid amounts.",
            )

    # Manual service lines must also identify their household member.
    manual_lines = workflow_state.get("manual_lines") or []
    manual_lines_by_member: dict[int, list[dict]] = {}

    for index, line in enumerate(manual_lines):
        if not isinstance(line, dict):
            continue

        raw_member_id = line.get("member_id")

        if raw_member_id in (None, ""):
            if len(selected_members) == 1:
                member_id = next(iter(selected_members))
            else:
                ctx.gap(
                    f"manual_line_member_{index}",
                    "blocking",
                    "Manual service line needs a patient",
                    f"Manual service line {index + 1} does not identify a household member.",
                    "Assign this service line to the correct selected household member.",
                )
                continue
        else:
            try:
                member_id = int(raw_member_id)
            except (TypeError, ValueError):
                member_id = -1

        if member_id not in selected_members:
            ctx.gap(
                f"manual_line_member_{index}",
                "blocking",
                "Manual service line has an invalid patient",
                f"Manual service line {index + 1} refers to a member who is not selected for this case.",
                "Assign the service line to a valid selected household member.",
            )
            continue

        ctx.resolve_gap(f"manual_line_member_{index}")
        manual_lines_by_member.setdefault(member_id, []).append(line)

    if manual_lines and ctx.case.service_date is None:
        ctx.gap(
            "service_date_manual",
            "blocking",
            "Service date is required",
            "A service date is required for manually entered service lines.",
            "Enter the actual service date in case details before running the analysis again.",
        )
    else:
        ctx.resolve_gap("service_date_manual")

    # One manual claim per member, never one household-wide claim assigned to the lead.
    for member_id, member_lines in manual_lines_by_member.items():
        if ctx.case.service_date is None:
            continue
        member = selected_members[member_id]

        claim = Claim(
            case_id=ctx.case.id,
            member_id=member.id,
            patient_name=member.name,
            provider_name=ctx.case.provider_name or "Self-declared provider",
            service_date=ctx.case.service_date,
            bill_number=None,
            narrative=ctx.case.narrative,
        )

        ctx.db.add(claim)
        ctx.db.flush()

        lines_added = 0

        for line in member_lines:
            billed = _positive_decimal(line.get("amount"))
            if billed is None:
                ctx.gap(
                    f"invalid_manual_line_amount_{member_id}_{len(claim.lines)}",
                    "blocking",
                    "Manual service line amount is invalid",
                    f"A manually entered line for {member.name} has an unreadable amount.",
                    "Correct the manual line amount and rerun the analysis.",
                )
                continue

            raw_quantity = line.get("quantity")
            known_quantity = _positive_quantity(raw_quantity)
            quantity_known = known_quantity is not None
            quantity = known_quantity or 1

            unit_rate = line.get("unit_rate")
            known_unit_rate = _positive_decimal(unit_rate)
            unit_rate_known = known_unit_rate is not None
            unit = known_unit_rate or Decimal("0")

            cpt_code = str(line.get("cpt_code") or "").strip() or None

            ctx.db.add(
                ClaimLine(
                    claim_id=claim.id,
                    description=str(line.get("description") or "Service")[:300],
                    quantity=quantity,
                    quantity_known=quantity_known and quantity > 0,
                    unit_rate=unit,
                    unit_rate_known=unit_rate_known,
                    billed_amount=billed,
                    cpt_code=cpt_code,
                    icd_codes=list(line.get("icd_codes") or []),
                    category=str(line.get("category") or "professional"),
                    code_confidence=(
                        Decimal("1") if cpt_code else Decimal("0")
                    ),
                    code_source="manual" if cpt_code else "unavailable",
                )
            )
            lines_added += 1

        if lines_added:
            ctx.resolve_gap(f"manual_lines_empty_{member_id}")
            ctx.db.commit()
            claims.append(claim)
        else:
            ctx.db.delete(claim)
            ctx.db.commit()
            ctx.gap(
                f"manual_lines_empty_{member_id}",
                "blocking",
                "No valid manual service lines",
                f"No valid positive-amount manual service lines were provided for {member.name}.",
                "Correct the manual service line amounts.",
            )

    return claims


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def coverage_node(ctx: RunContext) -> str:
    started = time.perf_counter()
    service = MockInsurerService(ctx.db)
    claims = ctx.db.query(Claim).filter(Claim.case_id == ctx.case.id).all()
    if not claims:
        ctx.gap("no_claims", "blocking", "No claims", "There is nothing to check coverage for.", "Upload a bill.")
        return "pause"
    selected = selected_policies(ctx.db, ctx.case)
    ctx.db.query(EligibilityCheck).filter(EligibilityCheck.case_id == ctx.case.id).delete()
    ctx.db.commit()
    eligibility_state: dict[str, dict] = {}
    checked = 0
    for claim in claims:
        member = ctx.db.get(FamilyMember, claim.member_id) if claim.member_id else None
        if not member:
            ctx.gap("claim_member_missing", "blocking", "Claim has no patient", "Assign a family member to the claim.", "Edit the case.")
            continue
        covering = []
        for policy, version in selected:
            link = next(
                (
                    link
                    for link in policy.member_links
                    if link.member_id == member.id
                ),
                None,
            )
            if not link:
                continue
            covering.append((policy, version))
            response = service.eligibility(
                {
                    "case_id": ctx.case.id,
                    "policy_id": policy.id,
                    "member_id": member.id,
                    "member_name": member.name,
                    "service_date": claim.service_date.isoformat(),
                }
            )
            benefits = service.benefits(
                {
                    "case_id": ctx.case.id,
                    "policy_id": policy.id,
                    "member_id": member.id,
                    "member_name": member.name,
                }
            )
            ctx.db.add(
                EligibilityCheck(
                    case_id=ctx.case.id,
                    policy_id=policy.id,
                    member_id=member.id,
                    endpoint="POST /mock-insurers/eligibility + /benefits",
                    status=str(response.get("status") or "unknown"),
                    simulated=True,
                    request={
                        "policy_number": policy.policy_number,
                        "member": member.name,
                        "service_date": claim.service_date.isoformat(),
                    },
                    response={"eligibility": response, "benefits": benefits},
                )
            )
            ctx.db.commit()
            eligibility_state.setdefault(str(claim.id), {})[str(policy.id)] = {
                "eligible": response.get("eligible"),
                "status": response.get("status"),
                "reasons": response.get("reasons"),
                "benefits": benefits.get("benefits"),
            }
            checked += 1
            ctx.emit(
                "Coverage Agent",
                "coverage",
                "check_eligibility",
                tool="POST /mock-insurers/eligibility",
                inputs={"policy": policy.policy_number, "member": member.name, "service_date": response.get("service_date")},
                observation=(
                    f"{policy.insurer_name}: member {member.name} is "
                    f"{'eligible' if response.get('eligible') else 'not eligible'} "
                    f"({'active' if response.get('status') == 'active' else response.get('status')})."
                ),
                checks=[
                    {"name": f"{policy.insurer_name} policy active", "passed": response.get("status") == "active", "detail": str(response.get("status"))},
                    {"name": f"{policy.insurer_name} member covered", "passed": bool(response.get("eligible")), "detail": ", ".join(response.get("reasons") or [])},
                    {"name": "Benefits on file", "passed": bool(benefits.get("benefits")), "detail": benefits.get("status", "")},
                ],
                decision="Eligible for coordination." if response.get("eligible") else "Keep the policy in the trace but exclude it from payment.",
                next_action="cob",
                duration_ms=int((time.perf_counter() - started) * 1000) // max(1, checked),
            )
            if not response.get("eligible"):
                ctx.gap(
                    f"ineligible_{policy.id}",
                    "action",
                    f"{policy.insurer_name} cannot pay for {member.name}",
                    "; ".join(response.get("reasons") or []),
                    "Check the policy status, dates or member enrolment with the insurer.",
                )
        if not covering:
            ctx.gap(
                f"no_cover_{claim.id}",
                "blocking",
                f"No selected policy covers {member.name}",
                "Every selected policy either excludes this member or does not list them.",
                "Select a policy that covers this member, or add the member to the policy.",
            )
        else:
            ctx.resolve_gap(f"no_cover_{claim.id}")
    ctx.save(eligibility=eligibility_state)
    ctx.emit(
        "Coverage Agent",
        "coverage",
        "summarise_benefits",
        tool="database",
        inputs={"claims": len(claims), "checks": checked},
        observation=f"Checked {checked} policy/member combination(s) against the simulated insurer API.",
        checks=[{"name": "Every claim has a coverage check", "passed": checked >= len(claims), "detail": f"{checked} checks"}],
        decision="Proceed to coordination of benefits.",
        next_action="cob",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return "done" if checked else "pause"


# ---------------------------------------------------------------------------
# COB
# ---------------------------------------------------------------------------


def cob_node(ctx: RunContext) -> str:
    started = time.perf_counter()
    claims = ctx.db.query(Claim).filter(Claim.case_id == ctx.case.id).all()
    selected = selected_policies(ctx.db, ctx.case)
    rule = ctx.case.coordination_rule or _family(ctx).coordination_rule or "policyholder"
    explicit = (ctx.case.workflow_state or {}).get("policy_order") or None
    orders: dict[str, list[dict]] = {}
    all_plans = 0
    for claim in claims:
        member = ctx.db.get(FamilyMember, claim.member_id) if claim.member_id else None
        if not member:
            continue
        plans, decisions, assumptions, warnings = determine_order(
            ctx.db, ctx.case, member, selected, rule, explicit, claim.service_date
        )
        for assumption in assumptions:
            ctx.assume(assumption)
        for warning in warnings:
            ctx.gap(f"cob_{claim.id}", "action", "Coordination warning", warning)
        if not plans:
            ctx.emit(
                "COB Agent",
                "cob",
                "determine_primary",
                inputs={"claim": claim.id, "member": member.name, "rule": rule},
                observation=f"No selected policy covers {member.name}.",
                checks=[{"name": "At least one payer", "passed": False, "detail": "0 policies"}],
                decision="Cannot coordinate this claim.",
                next_action="review",
                status="failed",
            )
            continue
        orders[str(claim.id)] = [decision.to_dict() for decision in decisions]
        all_plans += len(plans)
        primary = plans[0]
        secondary = plans[1] if len(plans) > 1 else None
        ctx.emit(
            "COB Agent",
            "cob",
            "determine_primary",
            tool="coordination_rule",
            inputs={
                "claim": claim.id,
                "member": member.name,
                "rule": rule,
                "policies": [f"{p.insurer} ({p.member_role})" for p in plans],
            },
            observation=(
                f"{primary.insurer} is primary for {member.name}"
                + (f"; {secondary.insurer} is secondary." if secondary else "; there is no secondary payer.")
            ),
            checks=[
                {"name": "Primary payer identified", "passed": True, "detail": primary.insurer},
                {"name": "Rule evidence recorded", "passed": bool(decisions[0].evidence), "detail": "; ".join(decisions[0].evidence[:2])},
                {"name": "Assumptions exposed", "passed": True, "detail": "; ".join(assumptions) or "none"},
            ],
            decision=(
                f"Apply primary-first adjudication under the '{rule}' rule."
                if secondary
                else "Adjudicate under the single covering policy."
            ),
            next_action="compliance",
            duration_ms=int((time.perf_counter() - started) * 1000) // max(1, len(claims)),
        )
    ctx.save(orders=orders)
    if not orders:
        ctx.gap("no_payer", "blocking", "No payer for this case", "None of the selected policies covers the patient(s).", "Fix the policy/member links.")
        return "pause"
    ctx.resolve_gap("no_payer")
    ctx.emit(
        "COB Agent",
        "cob",
        "publish_order",
        inputs={"claims": len(orders), "plans": all_plans},
        observation=f"Published the payer order for {len(orders)} claim(s).",
        checks=[{"name": "Every claim has a payer order", "passed": len(orders) == len(claims), "detail": f"{len(orders)}/{len(claims)}"}],
        decision="Proceed to pre-authorisation and compliance checks.",
        next_action="compliance",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return "done"


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------


def _diagnosis_codes(ctx: RunContext, claim: Claim) -> list[str]:
    codes: list[str] = []
    for line in claim.lines:
        for code in line.icd_codes or []:
            if code and code not in codes:
                codes.append(str(code))
    return codes[:6]


def compliance_node(ctx: RunContext) -> str:
    started = time.perf_counter()
    service = MockInsurerService(ctx.db)
    claims = ctx.db.query(Claim).filter(Claim.case_id == ctx.case.id).all()
    selected = selected_policies(ctx.db, ctx.case)
    state = dict(ctx.case.workflow_state or {})
    orders = state.get("orders") or {}
    ctx.db.query(Preauthorization).filter(Preauthorization.case_id == ctx.case.id).delete()
    ctx.db.commit()
    preauth_state: dict[str, dict] = {}
    required_count = 0
    for claim in claims:
        member = ctx.db.get(FamilyMember, claim.member_id) if claim.member_id else None
        claim_order = orders.get(str(claim.id)) or []
        for decision in claim_order:
            plan_key = decision.get("plan_key")
            policy_id = None
            version_id = None
            for policy, version in selected:
                if plan_key == f"P{policy.id}V{version.id}":
                    policy_id, version_id = policy.id, version.id
                    break
            if not policy_id:
                continue
            policy = ctx.db.get(Policy, policy_id)
            version = ctx.db.get(PolicyVersion, version_id) if version_id else policy.current_version
            plan = plan_from_version(
                policy,
                version,
                next((l for l in policy.member_links if l.member_id == (member.id if member else -1)), None),
                ctx.case.coordination_rule,
            )
            required, reason = preauth_requirement(claim_input(claim, ctx.case.service_date), plan)
            record = Preauthorization(
                case_id=ctx.case.id,
                claim_id=claim.id,
                policy_id=policy.id,
                policy_version_id=version.id,
                required=required,
                status="not_required" if not required else "required",
                reason=reason,
            )
            ctx.db.add(record)
            ctx.db.flush()
            if required:
                required_count += 1
                estimated = sum((line.billed_amount for line in claim.lines if not line.excluded), Decimal("0"))
                diagnosis = _diagnosis_codes(ctx, claim)
                procedures = [line.cpt_code for line in claim.lines if line.cpt_code]
                documents = [
                    doc.original_filename
                    for doc in _claim_docs(ctx)
                    if doc.doc_type in ("radiology", "estimate", "invoice", "prescription", "discharge")
                ]
                justification = claim.narrative or ""
                if not diagnosis:
                    ctx.gap(
                        f"missing_diagnosis_{claim.id}",
                        "action",
                        "Diagnosis code is missing",
                        "A pre-authorisation request needs a diagnosis code. Attach the radiology report or discharge summary, or assign the code during review.",
                        "Upload the report that supports the diagnosis.",
                    )
                request = {
                    "case_id": ctx.case.id,
                    "policy_id": policy.id,
                    "member_id": member.id if member else None,
                    "member_name": member.name if member else claim.patient_name,
                    "service_date": claim.service_date.isoformat(),
                    "procedure_codes": procedures,
                    "diagnosis_codes": diagnosis,
                    "estimated_cost": str(estimated),
                    "documents": documents,
                    "clinical_justification": justification,
                    "provider_in_network": ctx.case.provider_in_network,
                }
                response = service.pre_authorization(request)
                record.request = request
                record.response = response
                record.status = str(response.get("status") or "pending")
                record.reference = str(response.get("reference") or "")
                record.reason = "; ".join(response.get("reasons") or [])
                ctx.db.add(record)
                ctx.db.commit()
                preauth_state.setdefault(str(claim.id), {})[plan.key] = record.status
                ctx.emit(
                    "Compliance Agent",
                    "compliance",
                    "submit_preauthorization",
                    tool="POST /mock-insurers/pre-authorization",
                    inputs={
                        "insurer": policy.insurer_name,
                        "procedures": procedures,
                        "diagnosis": diagnosis,
                        "estimated_cost": str(estimated),
                    },
                    observation=(
                        f"{policy.insurer_name} returned '{record.status}' for the request "
                        f"(reference {record.reference}). This is a simulated response."
                    ),
                    checks=[
                        {"name": "Diagnosis support present", "passed": bool(diagnosis), "detail": ", ".join(diagnosis) or "missing"},
                        {"name": "Procedure codes present", "passed": bool(procedures), "detail": ", ".join(procedures) or "missing"},
                        {"name": "Insurer response received", "passed": record.status in ("approved", "pending", "rejected"), "detail": record.status},
                    ],
                    decision=(
                        "Treat the service as authorised."
                        if record.status == "approved"
                        else "Continue with the policy penalty applied and ask the household to act."
                    ),
                    next_action="financial",
                    duration_ms=int((time.perf_counter() - started) * 1000) // max(1, required_count),
                )
                if record.status == "rejected":
                    ctx.gap(
                        f"preauth_rejected_{policy.id}",
                        "action",
                        f"{policy.insurer_name} rejected the pre-authorisation",
                        record.reason or "The simulated insurer rejected the request.",
                        "Upload the missing clinical documents or correct the codes, then refresh the request.",
                    )
                elif record.status == "pending":
                    ctx.gap(
                        f"preauth_pending_{policy.id}",
                        "action",
                        f"{policy.insurer_name} has not decided yet",
                        record.reason or "The simulated insurer left the request pending.",
                        "Track the request; the calculation applies the policy penalty until it is approved.",
                    )
            else:
                ctx.db.commit()
        # Excluded services are a coverage gap the household should see.
        for line in claim.lines:
            if line.category == "equipment" or line.excluded:
                ctx.gap(
                    f"excluded_{line.id}",
                    "info",
                    f"{line.description[:60]} may not be covered",
                    "Equipment and some ancillary items are commonly excluded; the engine will apply each policy's exclusion list.",
                    "Check the policy schedule and keep the receipt.",
                )
    ctx.save(preauth=preauth_state, preauth_required=required_count)
    ctx.emit(
        "Compliance Agent",
        "compliance",
        "summarise_compliance",
        inputs={"required": required_count, "claims": len(claims)},
        observation=f"{required_count} pre-authorisation request(s) were required across {len(claims)} claim(s).",
        checks=[{"name": "Every required request was filed", "passed": True, "detail": f"{required_count} filed"}],
        decision="Proceed to the deterministic financial calculation.",
        next_action="financial",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return "done"


# ---------------------------------------------------------------------------
# Financial
# ---------------------------------------------------------------------------


def _plan_with_accumulators(plan, overrides: dict, member_id: int):
    data = overrides.get(f"{plan.key}:M{member_id}")
    if data:
        plan.deductible_used = Decimal(str(data["deductible_used"]))
        plan.oop_used = Decimal(str(data["oop_used"]))
        plan.annual_limit_used = Decimal(str(data["annual_limit_used"]))
        for sub in plan.sublimits:
            used = data.get("sublimits", {}).get(sub.key, {}).get("used")
            if used is not None:
                sub.used = Decimal(str(used))
    return plan


def _accumulator_snapshot(accumulator) -> dict:
    return {
        "deductible_used": str(accumulator.deductible_used or 0),
        "oop_used": str(accumulator.oop_used or 0),
        "annual_limit_used": str(accumulator.annual_limit_used or 0),
        "sublimits": {
            str(key): {"used": str(value)} for key, value in (accumulator.sublimits or {}).items()
        },
    }


def financial_node(ctx: RunContext) -> str:
    started = time.perf_counter()
    claims = ctx.db.query(Claim).filter(Claim.case_id == ctx.case.id).all()
    selected = selected_policies(ctx.db, ctx.case)
    state = dict(ctx.case.workflow_state or {})
    orders = state.get("orders") or {}
    preauth_state = state.get("preauth") or {}
    if not claims or not orders:
        ctx.gap("no_calculation", "blocking", "Nothing to calculate", "Claims or payer order are missing.", "Re-run the case.")
        return "pause"
    ctx.db.query(Adjudication).filter(Adjudication.case_id == ctx.case.id).delete()
    ctx.db.commit()

    # Per member, per policy version accumulator state for this run.
    overrides: dict[str, dict] = {}
    baseline: dict[str, dict] = {}
    accumulator_rows = {}
    for policy, version in selected:
        for link in policy.member_links:
            accumulator = get_accumulator(ctx.db, policy, version, link.member_id)
            key = f"P{policy.id}V{version.id}:M{link.member_id}"
            overrides[key] = _accumulator_snapshot(accumulator)
            baseline[key] = _accumulator_snapshot(accumulator)
            accumulator_rows[key] = accumulator

    totals = {
        "billed": Decimal("0"),
        "allowed": Decimal("0"),
        "contractual_adjustment": Decimal("0"),
        "primary_paid": Decimal("0"),
        "secondary_paid": Decimal("0"),
        "insurer_paid": Decimal("0"),
        "patient_liability": Decimal("0"),
        "excluded": Decimal("0"),
    }
    invariant_failures: list[dict] = []
    for claim in claims:
        member = ctx.db.get(FamilyMember, claim.member_id) if claim.member_id else None
        if not member:
            continue
        plan_keys = [d["plan_key"] for d in orders.get(str(claim.id)) or []]
        plans = []
        decisions = []
        for decision in orders.get(str(claim.id)) or []:
            policy_id = None
            version_id = None
            for policy, version in selected:
                if decision["plan_key"] == f"P{policy.id}V{version.id}":
                    policy_id, version_id = policy.id, version.id
                    break
            if not policy_id:
                continue
            policy = ctx.db.get(Policy, policy_id)
            version = ctx.db.get(PolicyVersion, version_id) if version_id else policy.current_version
            link = next((l for l in policy.member_links if l.member_id == member.id), None)
            accumulator = get_accumulator(ctx.db, policy, version, member.id)
            plan = plan_from_version(policy, version, link, ctx.case.coordination_rule, accumulator)
            plan = _plan_with_accumulators(plan, overrides, member.id)
            plans.append(plan)
            decisions.append(
                OrderDecision(
                    plan_key=plan.key,
                    role=decision["role"],
                    order=decision["order"],
                    rule=decision.get("rule") or ctx.case.coordination_rule,
                    evidence=decision.get("evidence") or [],
                    assumption=decision.get("assumption"),
                )
            )
        if not plans:
            continue
        preauth_approved = {
            key: (preauth_state.get(str(claim.id), {}).get(key) == "approved") for key in plan_keys
        }
        attempts = 0
        result = None
        while attempts < 2:
            attempts += 1
            result = adjudicate_claim(
                claim_input(claim, ctx.case.service_date),
                plans,
                decisions,
                preauth_approved,
                provider_in_network=ctx.case.provider_in_network,
            )
            failed = [inv for inv in result.invariants if not inv.passed]
            if not failed:
                break
            ctx.emit(
                "Financial Calculation Agent",
                "financial",
                "recalculate",
                tool="coordination_engine",
                inputs={"claim": claim.id, "attempt": attempts, "failed_checks": [i.name for i in failed]},
                observation="; ".join(f"{i.name}: {i.detail}" for i in failed[:2]),
                checks=[{"name": i.name, "passed": i.passed, "detail": i.detail} for i in failed],
                decision="Invariant failed — recalculate from the same inputs before accepting the result.",
                next_action="financial",
                status="retrying",
            )
        assert result is not None
        for plan_result in result.plans:
            ctx.db.add(
                Adjudication(
                    case_id=ctx.case.id,
                    claim_id=claim.id,
                    policy_id=plan_result.policy_id or 0,
                    policy_version_id=plan_result.version_id or 0,
                    role=plan_result.role,
                    order_index=plan_result.order,
                    result=plan_result.to_dict(),
                    allowed=plan_result.allowed_total,
                    plan_paid=plan_result.plan_paid,
                    member_paid=plan_result.member_paid,
                )
            )
        ctx.db.commit()
        # Carry this member's accumulator state into their next claim.
        for plan_key, acc in result.accumulators.items():
            overrides[f"{plan_key}:M{member.id}"] = {
                "deductible_used": acc["deductible_used"],
                "oop_used": acc["oop_used"],
                "annual_limit_used": acc["annual_limit_used"],
                "sublimits": acc["sublimits"],
            }
        for key, value in result.totals.items():
            if key in totals:
                totals[key] = totals[key] + value
        invariant_failures.extend(
            {"claim": claim.id, "name": inv.name, "detail": inv.detail}
            for inv in result.invariants
            if not inv.passed
        )
        ctx.emit(
            "Financial Calculation Agent",
            "financial",
            "adjudicate_claim",
            tool="coordination_engine",
            inputs={
                "claim": claim.id,
                "patient": claim.patient_name,
                "payer_order": [p.insurer for p in result.plans],
                "billed": str(result.totals["billed"]),
                "preauth_approved": preauth_approved,
                "accumulators": {
                    member.name: {
                        "deductible_used": overrides.get(f"{plan.key}:M{member.id}", {}).get("deductible_used"),
                        "oop_used": overrides.get(f"{plan.key}:M{member.id}", {}).get("oop_used"),
                    }
                    for plan in plans
                },
            },
            observation=(
                f"Insurers pay {result.totals['insurer_paid']} and the household pays "
                f"{result.totals['patient_liability']} of {result.totals['billed']}."
            ),
            checks=[
                {"name": inv.name, "passed": inv.passed, "detail": inv.detail} for inv in result.invariants
            ],
            decision=(
                "Numbers satisfy every invariant."
                if all(inv.passed for inv in result.invariants)
                else "Numbers failed an invariant; the run is held for repair."
            ),
            next_action="reporting",
            duration_ms=int((time.perf_counter() - started) * 1000) // max(1, len(claims)),
        )
        state.setdefault("claim_results", {})[str(claim.id)] = {
            "claim_id": claim.id,
            "patient": claim.patient_name,
            "provider": claim.provider_name,
            "bill_number": claim.bill_number,
            "service_date": (claim.service_date or ctx.case.service_date).isoformat()
            if (claim.service_date or ctx.case.service_date)
            else None,
            "document_id": claim.document_id,
            "totals": {k: str(v) for k, v in result.totals.items()},
            "order": [d.to_dict() for d in result.order],
            "lines": [line.to_dict() for line in result.lines],
            "plans": [
                {
                    "plan_key": plan.plan_key,
                    "insurer": plan.insurer,
                    "plan_name": plan.plan_name,
                    "policy_number": plan.policy_number,
                    "policy_id": plan.policy_id,
                    "version_id": plan.version_id,
                    "role": plan.role,
                    "plan_paid": str(plan.plan_paid),
                    "allowed_total": str(plan.allowed_total),
                    "deductible_total": str(plan.deductible_total),
                    "coinsurance_total": str(plan.coinsurance_total),
                    "penalty_total": str(plan.penalty_total),
                    "member_paid": str(plan.member_paid),
                    "preauth_required": plan.preauth_required,
                    "preauth_reason": plan.preauth_reason,
                }
                for plan in result.plans
            ],
            "warnings": result.warnings,
            "assumptions": result.assumptions,
            "invariants": [i.to_dict() for i in result.invariants],
        }
        ctx.case.workflow_state = {**state}
        ctx.db.add(ctx.case)
        ctx.db.commit()

    # Persist per-member accumulators once, and record the delta for re-runs.
    applied_delta: dict[str, dict] = {}
    for key, final in overrides.items():
        accumulator = accumulator_rows.get(key)
        if not accumulator:
            continue
        old = baseline.get(key, {})
        old_sub = old.get("sublimits") or {}
        sub_delta = {}
        for key_name, value in (final.get("sublimits") or {}).items():
            try:
                sub_delta[key_name] = float(
                    Decimal(str(value.get("used") or 0))
                    - Decimal(str((old_sub.get(key_name) or {}).get("used") or 0))
                )
            except Exception:
                sub_delta[key_name] = 0.0
        applied_delta[str(accumulator.id)] = {
            "deductible": float(Decimal(str(final["deductible_used"])) - Decimal(str(old.get("deductible_used") or 0))),
            "oop": float(Decimal(str(final["oop_used"])) - Decimal(str(old.get("oop_used") or 0))),
            "annual": float(
                Decimal(str(final["annual_limit_used"])) - Decimal(str(old.get("annual_limit_used") or 0))
            ),
            "sublimits": sub_delta,
        }
        accumulator.deductible_used = Decimal(str(final["deductible_used"]))
        accumulator.oop_used = Decimal(str(final["oop_used"]))
        accumulator.annual_limit_used = Decimal(str(final["annual_limit_used"]))
        accumulator.sublimits = {
            key_name: str(value.get("used", "0")) for key_name, value in (final.get("sublimits") or {}).items()
        }
        ctx.db.add(accumulator)
    ctx.db.commit()

    summary = {key: str(value) for key, value in totals.items()}
    summary["claims"] = len(claims)
    ctx.case.totals = summary
    ctx.case.workflow_state = {
        **(ctx.case.workflow_state or {}),
        "applied_accumulators": applied_delta,
        "totals": summary,
        "invariants": invariant_failures or [{"name": "All invariants passed", "passed": True}],
        "gaps": ctx.gaps,
        "assumptions": ctx.assumptions,
    }
    ctx.db.add(ctx.case)
    ctx.db.commit()

    ctx.emit(
        "Financial Calculation Agent",
        "financial",
        "validate_invariants",
        tool="coordination_engine",
        inputs={"invariants_checked": len(invariant_failures) or "all passed"},
        observation=(
            "Every financial invariant passed."
            if not invariant_failures
            else f"{len(invariant_failures)} invariant check(s) failed."
        ),
        checks=(
            [{"name": "All invariants", "passed": True, "detail": "bill, allowed amount and patient share reconcile"}]
            if not invariant_failures
            else [{"name": item["name"], "passed": False, "detail": item["detail"]} for item in invariant_failures]
        ),
        decision=(
            "Accept the calculation and generate deliverables."
            if not invariant_failures
            else "Hold the result for human review instead of publishing a wrong number."
        ),
        next_action="reporting" if not invariant_failures else "review",
        status="succeeded" if not invariant_failures else "failed",
    )
    if invariant_failures:
        ctx.gap(
            "invariant_failure",
            "blocking",
            "The calculation did not reconcile",
            "A financial invariant failed; the result was withheld rather than published.",
            "Review the policy terms and the service lines, then re-run.",
        )
        return "pause"
    return "done"


# ---------------------------------------------------------------------------
# Reporting and critic
# ---------------------------------------------------------------------------


def reporting_node(ctx: RunContext) -> str:
    started = time.perf_counter()
    artifacts = report_service.generate_reports(ctx)
    for artifact in artifacts:
        ctx.emit(
            "Reporting Agent",
            "reporting",
            "generate_report",
            tool=artifact["tool"],
            inputs={"kind": artifact["kind"], "title": artifact["title"]},
            observation=f"Created {artifact['title']} ({artifact['kind']}).",
            checks=[{"name": "File written", "passed": artifact.get("exists", True), "detail": artifact["kind"]}],
            decision="Include it in the case deliverables.",
            next_action="critic",
        )
    ctx.emit(
        "Reporting Agent",
        "reporting",
        "publish_deliverables",
        inputs={"artifacts": len(artifacts)},
        observation=f"Generated {len(artifacts)} deliverable(s), including the financial report and pre-authorisation letters.",
        checks=[{"name": "At least one report", "passed": len(artifacts) > 0, "detail": f"{len(artifacts)} files"}],
        decision="Hand the artefacts to the supervisor critic.",
        next_action="critic",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return "done"


def critic_node(ctx: RunContext) -> str:
    from ..models import Report

    ctx.case = ctx.db.get(Case, ctx.case.id)
    claims = ctx.db.query(Claim).filter(Claim.case_id == ctx.case.id).all()
    adjudications = ctx.db.query(Adjudication).filter(Adjudication.case_id == ctx.case.id).all()
    reports = ctx.db.query(Report).filter(Report.case_id == ctx.case.id).all()
    preauths = ctx.db.query(Preauthorization).filter(Preauthorization.case_id == ctx.case.id).all()
    required_letters = len([p for p in preauths if p.required])
    letter_files = [r for r in reports if r.kind == "pdf_letter"]
    state = ctx.case.workflow_state or {}
    invariants = state.get("invariants") or []
    failed_invariants = [item for item in invariants if item.get("passed") is False]
    blocking_gaps = [gap for gap in (state.get("gaps") or []) if gap.get("severity") == "blocking"]
    trace_count = (
        ctx.db.query(Adjudication).filter(Adjudication.case_id == ctx.case.id).count()
    )
    checks = [
        {"name": "Every claim was adjudicated", "passed": len(adjudications) >= len(claims) and len(claims) > 0, "detail": f"{len(adjudications)} plan results for {len(claims)} claims"},
        {"name": "Every invariant passed", "passed": not failed_invariants, "detail": f"{len(failed_invariants)} failed"},
        {"name": "No blocking gaps remain", "passed": not blocking_gaps, "detail": f"{len(blocking_gaps)} unresolved"},
        {"name": "Financial report generated", "passed": any(r.kind == "json" for r in reports), "detail": ", ".join(sorted({r.kind for r in reports}))},
        {"name": "Letters generated for required pre-auth", "passed": len(letter_files) >= required_letters, "detail": f"{len(letter_files)} letter(s), {required_letters} required"},
        {"name": "Execution trace recorded", "passed": ctx.seq > 0, "detail": f"{ctx.seq} steps"},
    ]
    passed = all(check["passed"] for check in checks)
    ctx.emit(
        "Supervisor Agent",
        "critic",
        "review_deliverables",
        tool="critic",
        inputs={"checks": len(checks), "claims": len(claims), "reports": len(reports)},
        observation="The critic inspected every required artefact for this case.",
        checks=checks,
        decision=(
            "Deliverables are complete and internally consistent."
            if passed
            else "Deliverables are incomplete; keep the case open instead of declaring success."
        ),
        next_action="complete" if passed else "review",
        status="succeeded" if passed else "failed",
    )
    if not passed:
        if not claims:
            ctx.gap("critic_no_claims", "blocking", "No adjudicated claim", "The run produced no claim to report.", "Check the uploaded documents.")
        ctx.save()
        return "pause"
    return "done"
