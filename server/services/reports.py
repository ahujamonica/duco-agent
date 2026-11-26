"""Report, letter and audio generation from real case results."""

from __future__ import annotations

import html
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..config import AUDIO_DIR, REPORT_DIR
from ..models import Case, Claim, Document, FamilyMember, Policy, Preauthorization, Report, utcnow
from .results import build_results, build_trace

NAVY = "#14243A"
BLUE = "#3867D6"
TEAL = "#16A39A"
AMBER = "#B7791F"
RED = "#C53030"
SOFT = "#F5F7FB"


def inr(value, symbol: str = "₹") -> str:
    try:
        amount = Decimal(str(value or 0))
    except Exception:
        amount = Decimal("0")
    text = f"{amount:,.2f}"
    return f"{symbol}{text}"


def _case_dir(case: Case, run_id: str) -> Path:
    path = REPORT_DIR / f"case-{case.id}" / (run_id or "run")
    path.mkdir(parents=True, exist_ok=True)
    return path


def generate_reports(ctx) -> list[dict]:
    """Generate every deliverable for the case and register it."""
    case: Case = ctx.db.get(Case, ctx.case.id)
    case_dir = _case_dir(case, ctx.run_id)
    # Clear previous artefacts for this run so a retry does not duplicate them.
    for old in ctx.db.query(Report).filter(Report.case_id == case.id).all():
        try:
            Path(old.path).unlink(missing_ok=True)
        except OSError:
            pass
        ctx.db.delete(old)
    ctx.db.commit()

    payload = build_results(ctx.db, case)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["run_id"] = ctx.run_id
    trace = build_trace(ctx.db, case, 0, 500)
    claims = ctx.db.query(Claim).filter(Claim.case_id == case.id).order_by(Claim.id).all()
    preauths = ctx.db.query(Preauthorization).filter(Preauthorization.case_id == case.id).all()
    artifacts: list[dict] = []

    # 1. Machine-readable JSON
    json_path = case_dir / "financial_breakdown.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    artifacts.append(_register(ctx, case, "json", "Financial breakdown (JSON)", json_path, "application/json", {}))

    # 2. Printable HTML cost flow
    html_path = case_dir / "cost_flow.html"
    html_path.write_text(_render_html(payload, trace), encoding="utf-8")
    artifacts.append(_register(ctx, case, "html", "Cost-flow report", html_path, "text/html", {}))

    # 3. Trace
    trace_path = case_dir / "execution_trace.json"
    trace_path.write_text(
        json.dumps({"case_id": case.id, "run_id": ctx.run_id, **trace}, indent=2), encoding="utf-8"
    )
    artifacts.append(_register(ctx, case, "trace", "Execution trace (JSON)", trace_path, "application/json", {}))

    # 4. Pre-authorisation letters
    for preauth in preauths:
        if not preauth.required:
            continue
        policy = ctx.db.get(Policy, preauth.policy_id)
        if not policy:
            continue
        claims_for_policy = []
        if preauth.claim_id:
            claim = ctx.db.get(Claim, preauth.claim_id)
            if claim:
                claims_for_policy = [claim]
        if not claims_for_policy:
            claims_for_policy = [
                claim
                for claim in claims
                if any(
                    item.get("plan_key", "").startswith(f"P{policy.id}V")
                    for item in ((case.workflow_state or {}).get("orders", {}).get(str(claim.id)) or [])
                )
            ]
        if not claims_for_policy:
            continue
        path = case_dir / f"preauth_letter_{_slug(policy.insurer_name)}_{policy.id}.pdf"
        _render_letter(path, case, policy, preauth, claims_for_policy, ctx.db, payload)
        artifacts.append(
            _register(
                ctx,
                case,
                "pdf_letter",
                f"Pre-authorisation letter — {policy.insurer_name}",
                path,
                "application/pdf",
                {"policy_id": policy.id, "preauth_id": preauth.id, "status": preauth.status},
            )
        )

    # 5. Audio briefing
    script = _briefing_script(case, payload)
    audio_path = AUDIO_DIR / f"case-{case.id}-{ctx.run_id}.mp3"
    audio_status = "generated"
    try:
        from gtts import gTTS

        gTTS(script, lang="en", tld="co.in").save(str(audio_path))
    except Exception as exc:  # noqa: BLE001 - audio is optional
        audio_status = f"unavailable: {type(exc).__name__}"
        audio_path = AUDIO_DIR / f"case-{case.id}-{ctx.run_id}.txt"
        audio_path.write_text(script, encoding="utf-8")
    artifacts.append(
        _register(
            ctx,
            case,
            "audio",
            "Audio briefing" if audio_status == "generated" else "Audio briefing (script only)",
            audio_path,
            "audio/mpeg" if audio_status == "generated" else "text/plain",
            {"status": audio_status, "script": script[:1200]},
        )
    )

    return artifacts


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")[:50] or "insurer"


def _register(ctx, case: Case, kind: str, title: str, path: Path, mime: str, meta: dict) -> dict:
    report = Report(case_id=case.id, kind=kind, title=title, path=str(path), mime=mime, meta=meta or {})
    ctx.db.add(report)
    ctx.db.commit()
    return {
        "id": report.id,
        "kind": kind,
        "title": title,
        "path": str(path),
        "mime": mime,
        "exists": path.exists(),
        "tool": "reportlab" if mime == "application/pdf" else ("gtts" if kind == "audio" else "template"),
    }


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------


def _render_html(payload: dict, trace: dict) -> str:
    case = payload["case"]
    totals = payload.get("totals") or {}
    billed = Decimal(str(totals.get("billed") or 0))
    allowed = Decimal(str(totals.get("allowed") or 0))
    adjustment = Decimal(str(totals.get("contractual_adjustment") or 0))
    primary = Decimal(str(totals.get("primary_paid") or 0))
    secondary = Decimal(str(totals.get("secondary_paid") or 0))
    patient = Decimal(str(totals.get("patient_liability") or 0))

    def bar(label: str, amount: Decimal, colour: str) -> str:
        width = float(min(Decimal("100"), (amount / billed) * 100)) if billed > 0 else 0
        return (
            f'<div class="bar-row"><div class="bar-label">{html.escape(label)}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%;background:{colour}"></div></div>'
            f'<div class="bar-value">{inr(amount)}</div></div>'
        )

    claim_sections = []
    for claim in payload.get("claims") or []:
        rows = []
        for line in claim.get("lines") or []:
            plans = line.get("plans") or []
            primary_paid = sum(
                (Decimal(str(p.get("plan_paid") or 0)) for p in plans if p.get("role") == "primary"), Decimal("0")
            )
            secondary_paid = sum(
                (Decimal(str(p.get("plan_paid") or 0)) for p in plans if p.get("role") != "primary"), Decimal("0")
            )
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(line.get('description') or ''))}</td>"
                f"<td class='mono'>{html.escape(str(line.get('cpt_code') or '—'))}</td>"
                f"<td class='num'>{inr(line.get('billed'))}</td>"
                f"<td class='num'>{inr(line.get('allowed'))}</td>"
                f"<td class='num'>{inr(primary_paid)}</td>"
                f"<td class='num'>{inr(secondary_paid)}</td>"
                f"<td class='num strong'>{inr(line.get('patient'))}</td>"
                "</tr>"
            )
        order = " → ".join(
            f"{html.escape(item.get('plan_key',''))} ({html.escape(item.get('role',''))})"
            for item in claim.get("order") or []
        )
        totals_claim = claim.get("totals") or {}
        claim_sections.append(
            f"""
            <section class="claim">
              <div class="claim-head">
                <div><h3>{html.escape(claim.get('patient') or 'Patient')}</h3>
                <p class="muted">{html.escape(claim.get('provider') or '')} · {html.escape(str(claim.get('service_date') or ''))}
                {(' · bill ' + html.escape(str(claim.get('bill_number')))) if claim.get('bill_number') else ''}</p></div>
                <div class="claim-total"><span>You pay</span><strong>{inr(totals_claim.get('patient_liability'))}</strong></div>
              </div>
              <p class="muted small">Payer order: {html.escape(order) or '—'}</p>
              <table>
                <thead><tr><th>Service</th><th>CPT</th><th>Billed</th><th>Allowed</th><th>Primary</th><th>Secondary</th><th>You pay</th></tr></thead>
                <tbody>{''.join(rows) or '<tr><td colspan="7">No lines</td></tr>'}</tbody>
              </table>
            </section>
            """
        )

    gap_items = "".join(
        f"<li><strong>{html.escape(str(gap.get('title') or ''))}</strong> — {html.escape(str(gap.get('detail') or ''))}"
        f"{('<div class=\"muted small\">Action: ' + html.escape(str(gap.get('action'))) + '</div>') if gap.get('action') else ''}</li>"
        for gap in payload.get("gaps") or []
    ) or "<li>No coverage gaps were detected.</li>"

    accum_cards = "".join(
        f"""
        <div class="accum">
          <div class="muted small">{html.escape(item['insurer'])} · v{item['version']}</div>
          <div class="accum-title">{html.escape(item['plan_name'])}</div>
          <div class="deduct"><span>Deductible used</span><strong>{inr(item['deductible_used'])} / {inr(item['deductible'])}</strong></div>
          <div class="deduct"><span>Out-of-pocket used</span><strong>{inr(item['oop_used'])} / {inr(item['oop_max'])}</strong></div>
          <div class="deduct"><span>Annual limit used</span><strong>{inr(item['annual_limit_used'])} / {inr(item['annual_limit'])}</strong></div>
        </div>
        """
        for item in payload.get("accumulators") or []
    )

    preauth_rows = "".join(
        f"<tr><td>{html.escape(item.get('insurer') or '')}</td><td>{html.escape(item.get('status') or '')}</td>"
        f"<td class='mono'>{html.escape(item.get('reference') or '—')}</td><td>{html.escape(item.get('reason') or '')}</td></tr>"
        for item in payload.get("preauth") or []
    ) or "<tr><td colspan='4'>No pre-authorisation was required.</td></tr>"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DuCO Agent — {html.escape(case['title'])}</title>
<style>
  :root {{ --navy:{NAVY}; --blue:{BLUE}; --teal:{TEAL}; --amber:{AMBER}; --red:{RED}; --soft:{SOFT}; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Arial,sans-serif; color:#1f2937; background:#fff; line-height:1.5; }}
  .page {{ max-width:1040px; margin:0 auto; padding:48px 40px; }}
  header {{ display:flex; justify-content:space-between; align-items:flex-start; border-bottom:2px solid var(--navy); padding-bottom:20px; }}
  .brand {{ font-weight:800; letter-spacing:-.02em; color:var(--navy); font-size:20px; }}
  .brand span {{ color:var(--teal); }}
  h1 {{ font-size:30px; letter-spacing:-.02em; margin:6px 0 4px; color:var(--navy); }}
  h2 {{ font-size:17px; margin:34px 0 12px; color:var(--navy); letter-spacing:-.01em; }}
  h3 {{ margin:0 0 2px; font-size:16px; }}
  .muted {{ color:#6b7280; }}
  .small {{ font-size:12px; }}
  .badge {{ display:inline-block; padding:4px 10px; border-radius:999px; background:#eef2ff; color:#3730a3; font-size:11px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; }}
  .badge.sim {{ background:#fef3c7; color:#92400e; }}
  .summary {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-top:24px; }}
  .card {{ border:1px solid #e5e7eb; border-radius:12px; padding:16px; }}
  .card .k {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:#6b7280; }}
  .card .v {{ font-size:22px; font-weight:750; color:var(--navy); margin-top:4px; letter-spacing:-.02em; }}
  .waterfall {{ margin-top:18px; border:1px solid #e5e7eb; border-radius:12px; padding:18px; }}
  .bar-row {{ display:grid; grid-template-columns:150px 1fr 130px; gap:12px; align-items:center; margin:9px 0; font-size:13px; }}
  .bar-track {{ height:10px; background:#eef1f6; border-radius:6px; overflow:hidden; }}
  .bar-fill {{ height:100%; border-radius:6px; }}
  .bar-value {{ text-align:right; font-variant-numeric:tabular-nums; font-weight:650; }}
  table {{ width:100%; border-collapse:collapse; margin-top:8px; font-size:13px; }}
  th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:#6b7280; padding:8px 8px; border-bottom:1px solid #e5e7eb; }}
  td {{ padding:9px 8px; border-bottom:1px solid #f1f3f7; vertical-align:top; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
  .strong {{ font-weight:700; color:var(--navy); }}
  .claim {{ margin-top:26px; border-top:1px solid #e5e7eb; padding-top:18px; }}
  .claim-head {{ display:flex; justify-content:space-between; align-items:flex-start; }}
  .claim-total {{ text-align:right; }} .claim-total span {{ font-size:11px; text-transform:uppercase; color:#6b7280; display:block; }}
  .claim-total strong {{ font-size:20px; color:var(--teal); }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
  .accum {{ border:1px solid #e5e7eb; border-radius:10px; padding:14px; margin-bottom:10px; }}
  .accum-title {{ font-weight:650; margin-bottom:8px; }}
  .deduct {{ display:flex; justify-content:space-between; font-size:12px; padding:3px 0; color:#374151; }}
  .notice {{ background:#fffbeb; border:1px solid #fde68a; border-radius:10px; padding:14px 16px; font-size:12.5px; color:#78350f; }}
  .gaps li {{ margin:8px 0; }}
  footer {{ margin-top:40px; border-top:1px solid #e5e7eb; padding-top:14px; font-size:11px; color:#6b7280; }}
  @media print {{ .page {{ padding:20px; }} body {{ font-size:12px; }} .card .v {{ font-size:18px; }} }}
  @media (max-width:800px) {{ .summary {{ grid-template-columns:1fr 1fr; }} .grid2 {{ grid-template-columns:1fr; }} .bar-row {{ grid-template-columns:110px 1fr 90px; }} }}
</style></head><body><div class="page">
<header>
  <div><div class="brand">DuCO <span>Agent</span></div>
  <h1>{html.escape(case['title'])}</h1>
  <p class="muted small">{html.escape(case.get('family') or '')} · {html.escape(case.get('provider') or '')} · service {html.escape(str(case.get('service_date') or ''))}</p></div>
  <div style="text-align:right"><span class="badge sim">Simulated insurer data</span><br>
  <span class="muted small">Generated {html.escape(str(payload.get('generated_at') or ''))}<br>Run {html.escape(str(payload.get('run_id') or ''))}</span></div>
</header>
<div class="summary">
  <div class="card"><div class="k">Total billed</div><div class="v">{inr(billed)}</div></div>
  <div class="card"><div class="k">Insurers pay</div><div class="v" style="color:{TEAL}">{inr(primary + secondary)}</div></div>
  <div class="card"><div class="k">You pay</div><div class="v">{inr(patient)}</div></div>
  <div class="card"><div class="k">Adjustments</div><div class="v">{inr(adjustment)}</div></div>
</div>
<h2>Cost flow</h2>
<div class="waterfall">
  {bar("Total billed", billed, NAVY)}
  {bar("Allowed amount", allowed, "#5b6b82")}
  {bar("Contractual adjustment", adjustment, "#c3cad6")}
  {bar("Primary insurer", primary, BLUE)}
  {bar("Secondary insurer", secondary, TEAL)}
  {bar("Your liability", patient, AMBER)}
</div>
<h2>Claims</h2>
{''.join(claim_sections)}
<h2>Pre-authorisation</h2>
<table><thead><tr><th>Insurer</th><th>Status</th><th>Reference</th><th>Basis</th></tr></thead><tbody>{preauth_rows}</tbody></table>
<div class="grid2">
  <div><h2>Deductible and benefit utilisation</h2>{accum_cards}</div>
  <div><h2>Coverage gaps</h2><ul class="gaps">{gap_items}</ul></div>
</div>
<h2>Assumptions</h2>
<ul>{''.join(f'<li>{html.escape(str(a))}</li>' for a in payload.get('assumptions') or []) or '<li>None recorded.</li>'}</ul>
<h2>Audit</h2>
<p class="small">This report was produced from {payload.get('audit', {}).get('events', 0)} agent events and
{payload.get('audit', {}).get('api_calls', 0)} simulated insurer calls. The execution trace is attached as JSON.</p>
<div class="notice"><strong>Important.</strong> Insurer responses in this report come from the local mock insurer sandbox and are not
approvals. Calculations are estimates based on the policy terms stored for this case. A pre-authorisation letter is a request,
not a guarantee. Confirm every policy term and clinical code with the insurer and the treating clinician.</div>
<footer>DuCO Agent · coordination-of-benefits prototype · {html.escape(case.get('family') or '')} · This document contains health information; store it securely.</footer>
</div></body></html>"""


# ---------------------------------------------------------------------------
# PDF letters
# ---------------------------------------------------------------------------


def _render_letter(
    path: Path,
    case: Case,
    policy: Policy,
    preauth: Preauthorization,
    claims: list[Claim],
    db,
    payload: dict,
) -> None:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.2, leading=13, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=colors.HexColor("#555555"))
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=15, leading=18, textColor=colors.HexColor(NAVY), spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=10.5, leading=13, textColor=colors.HexColor(NAVY), spaceBefore=10, spaceAfter=4)
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
        title=f"Pre-authorisation request — {policy.insurer_name}", author="DuCO Agent",
    )
    flow = []
    flow.append(Paragraph("DuCO <font color='#16A39A'>Agent</font>", ParagraphStyle("brand", parent=body, fontSize=16, leading=18, textColor=colors.HexColor(NAVY))))
    flow.append(Paragraph("Coordination-of-benefits desk", small))
    flow.append(Spacer(1, 8))
    flow.append(Paragraph(f"Pre-authorisation request — {html.escape(policy.insurer_name)}", h1))
    flow.append(
        Paragraph(
            f"<b>Prepared:</b> {utcnow().date().isoformat()} &nbsp;·&nbsp; "
            f"<b>Request reference:</b> {html.escape(preauth.reference or 'not yet filed')} &nbsp;·&nbsp; "
            f"<b>Simulated insurer response:</b> {html.escape(preauth.status)}",
            small,
        )
    )
    flow.append(Spacer(1, 6))
    flow.append(
        Paragraph(
            "<b>This letter is a request for authorisation. It is not an approval, a guarantee of payment or a "
            "clinical opinion.</b>",
            ParagraphStyle("warn", parent=body, textColor=colors.HexColor("#92400E"), backColor=colors.HexColor("#FEF3C7"), borderPadding=6),
        )
    )

    member = next((m for m in case.family.members if m.id == (claims[0].member_id if claims else None)), None)
    patient_name = member.name if member else claims[0].patient_name
    dob = member.date_of_birth.isoformat() if member and member.date_of_birth else "on file"
    flow.append(Paragraph("Patient and policy", h2))
    patient_rows = [
        ["Patient", patient_name],
        ["Date of birth", dob],
        ["Policy number", policy.policy_number],
        ["Plan", f"{policy.plan_name} (version {policy.current_version.version if policy.current_version else '—'})"],
        ["Policyholder", _policyholder_name(policy, db)],
        ["Policy period", f"{policy.start_date or '—'} to {policy.end_date or '—'}"],
        ["Requesting provider", claims[0].provider_name or case.provider_name or "—"],
    ]
    flow.append(_table(patient_rows, [42 * mm, 110 * mm]))

    procedures = []
    diagnoses = []
    for claim in claims:
        for line in claim.lines:
            if line.cpt_code and line.cpt_code not in procedures:
                procedures.append(line.cpt_code)
            for code in line.icd_codes or []:
                if code not in diagnoses:
                    diagnoses.append(code)
    estimate = sum((line.billed_amount for claim in claims for line in claim.lines), Decimal("0"))
    flow.append(Paragraph("Requested services", h2))
    service_rows = [["CPT / HCPCS", "Service", "Billed estimate"]]
    for claim in claims:
        for line in claim.lines:
            service_rows.append([line.cpt_code or "—", Paragraph(html.escape(line.description), body), inr(line.billed_amount, "Rs. ")])
    flow.append(_table(service_rows, [26 * mm, 96 * mm, 30 * mm], header=True))
    flow.append(Spacer(1, 4))
    flow.append(
        Paragraph(
            f"<b>Estimated cost:</b> {inr(estimate, 'Rs. ')} &nbsp;·&nbsp; "
            f"<b>Expected service date:</b> {claims[0].service_date or case.service_date or '—'}",
            body,
        )
    )

    flow.append(Paragraph("Clinical basis", h2))
    if diagnoses:
        flow.append(Paragraph(f"<b>Diagnosis codes on the claim:</b> {', '.join(html.escape(code) for code in diagnoses)}", body))
    else:
        flow.append(Paragraph("<b>Diagnosis codes:</b> not recorded — the insurer may reject the request until a clinician assigns a code.", body))
    justification = (claims[0].narrative or case.narrative or "").strip()
    flow.append(
        Paragraph(
            html.escape(justification[:1800]) if justification else "Clinical justification was not present in the supplied documents.",
            body,
        )
    )
    flow.append(Paragraph("Codes are taken from the uploaded documents and are subject to clinician confirmation.", small))

    flow.append(Paragraph("Coordination of benefits", h2))
    order_items = []
    for claim in claims:
        for item in ((case.workflow_state or {}).get("orders", {}).get(str(claim.id)) or []):
            if item.get("plan_key", "").startswith(f"P{policy.id}V"):
                order_items.append((claim.patient_name, item.get("role"), item.get("rule"), item.get("evidence") or []))
    if order_items:
        for patient_name, role, rule, evidence in order_items:
            flow.append(
                Paragraph(
                    f"<b>{html.escape(str(patient_name))}</b> — this policy is modelled as <b>{html.escape(str(role))}</b> "
                    f"under the '{html.escape(str(rule))}' rule. " + html.escape("; ".join(evidence[:2])),
                    body,
                )
            )
    else:
        flow.append(Paragraph("No coordination position is recorded for this policy.", body))
    flow.append(
        Paragraph(
            "Primary/secondary ordering is a modelling choice; the insurers may instead settle on a contribution basis. "
            "Confirm the coordination position with both insurers.",
            small,
        )
    )

    documents = [doc.original_filename for doc in db.query(Document).filter(Document.id.in_(case.document_ids or [])).all()]
    flow.append(Paragraph("Supporting documents", h2))
    flow.append(Paragraph(", ".join(html.escape(name) for name in documents) or "None attached.", body))

    flow.append(Paragraph("Declaration", h2))
    flow.append(
        Paragraph(
            "This request was prepared by an automated coordination assistant from documents supplied by the patient. "
            "The patient or treating clinician must verify every clinical detail. The insurer's decision, not this letter, "
            "determines cover.",
            body,
        )
    )
    flow.append(Spacer(1, 8))
    flow.append(
        Paragraph(
            "SIMULATED SANDBOX — this letter was generated by a prototype. No real insurer has received or approved it.",
            ParagraphStyle("sim", parent=small, textColor=colors.HexColor("#92400E")),
        )
    )
    doc.build(flow)


def _policyholder_name(policy: Policy, db) -> str:
    if not policy.policyholder_member_id:
        return "—"
    member = db.get(FamilyMember, policy.policyholder_member_id)
    return member.name if member else "—"


def _table(rows: list[list], widths: list, header: bool = False):
    table = Table(rows, colWidths=widths)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.6),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#4B5563")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5F7FB")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#14243A")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    table.setStyle(TableStyle(style))
    return table


def _briefing_script(case: Case, payload: dict) -> str:
    totals = payload.get("totals") or {}
    claims = payload.get("claims") or []
    patient = claims[0].get("patient") if claims else "the patient"
    def spoken(value) -> str:
        return f"{Decimal(str(value or 0)):,.0f} rupees"

    script = (
        f"Here is your DuCO Agent briefing for {case.title}. "
        f"The total billed amount is {spoken(totals.get('billed'))}. "
        f"Your insurers are estimated to pay {spoken(totals.get('insurer_paid'))}, "
        f"split as {spoken(totals.get('primary_paid'))} from the primary policy and "
        f"{spoken(totals.get('secondary_paid'))} from the secondary policy. "
        f"Your estimated share is {spoken(totals.get('patient_liability'))}. "
    )
    pending = [item for item in payload.get("preauth") or [] if item.get("status") in ("pending", "rejected")]
    if pending:
        script += (
            f"{len(pending)} pre-authorisation request needs attention: "
            + "; ".join(f"{item.get('insurer')} is {item.get('status')}" for item in pending)
            + ". "
        )
    else:
        script += "The pre-authorisation requests are in order. "
    script += (
        "These figures use simulated insurer responses and the policy terms stored for this case. "
        "They are estimates for planning, not a guarantee of payment. "
        "Open the report to see every line and its calculation. This briefing was generated by DuCO Agent."
    )
    return script
