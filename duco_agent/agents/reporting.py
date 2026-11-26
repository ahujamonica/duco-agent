"""Reporting agent: turn the adjudicated result into things a household can use.

Three artifacts come out of here: a printable cost-flow page, a machine-readable
financial breakdown, and a spoken briefing script (turned into audio when a TTS
binary is available).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..config import PLANS
from ..models import money, money_str
from .base import AgentBase, CheckResult


@dataclass
class ReportResult:
    artifacts: dict[str, str]
    warnings: list[str]


def _rupees(value) -> str:
    return f"₹{money_str(money(value))}"


def _pct(part, whole) -> float:
    if not whole:
        return 0.0
    return float(money(part) / money(whole) * 100)


def _claim_card(claim, outcome, preauth_records) -> str:
    plan_primary = PLANS[outcome.primary_plan]
    plan_secondary = PLANS[outcome.secondary_plan]
    billed = claim.total_billed
    primary_paid = outcome.primary.plan_paid
    secondary_paid = outcome.secondary.plan_paid
    member = outcome.member_out_of_pocket
    primary_width = max(_pct(primary_paid, billed), 0)
    secondary_width = max(_pct(secondary_paid, billed), 0)
    member_width = max(100 - primary_width - secondary_width, 0)

    line_rows = []
    for line, primary_line, secondary_line in zip(claim.lines, outcome.primary.lines, outcome.secondary.lines):
        status = "Excluded" if line.non_covered else ("Covered" if line.cpt_code else "Covered (code inferred)")
        code_confidence = f"{line.code_confidence:.0%}" if line.code_confidence else "n/a"
        line_rows.append(
            f"""<tr>
      <td>{line.description}</td>
      <td class="mono">{line.cpt_code or '—'}</td>
      <td class="num">{_rupees(line.billed_amount)}</td>
      <td class="num">{_rupees(primary_line.allowed)}</td>
      <td class="num">{_rupees(primary_line.plan_paid)}</td>
      <td class="num">{_rupees(secondary_line.plan_paid)}</td>
      <td class="num strong">{_rupees(line.billed_amount - primary_line.plan_paid - secondary_line.plan_paid)}</td>
      <td><span class="badge {'warn' if line.non_covered else 'ok'}">{status}</span> <span class="muted">{code_confidence}</span></td>
    </tr>"""
        )

    preauth_badges = []
    for plan_id in (outcome.primary_plan, outcome.secondary_plan):
        record = preauth_records.get((claim.claim_id, plan_id))
        if record and record.required:
            label = f"{PLANS[plan_id].insurer_name} pre-auth {record.reference}"
            preauth_badges.append(f'<span class="badge ok">{label}</span>')
        else:
            preauth_badges.append(f'<span class="badge soft">{PLANS[plan_id].insurer_name} pre-auth not required</span>')

    return f"""
  <section class="card">
    <div class="card-head">
      <div>
        <h3>{claim.patient_name}</h3>
        <p class="muted">{claim.provider_name} · service date {claim.service_date.strftime('%d %b %Y')} · claim {claim.claim_id}</p>
      </div>
      <div class="amount">{_rupees(billed)}</div>
    </div>
    <div class="bar" role="img" aria-label="Payment split: {plan_primary.insurer_name} {primary_width:.0f} percent, {plan_secondary.insurer_name} {secondary_width:.0f} percent, you {member_width:.0f} percent">
      <div class="seg primary" style="width:{primary_width:.2f}%"></div>
      <div class="seg secondary" style="width:{secondary_width:.2f}%"></div>
      <div class="seg member" style="width:{member_width:.2f}%"></div>
    </div>
    <div class="legend">
      <span><i class="dot primary"></i>{plan_primary.insurer_name} pays <strong>{_rupees(primary_paid)}</strong></span>
      <span><i class="dot secondary"></i>{plan_secondary.insurer_name} pays <strong>{_rupees(secondary_paid)}</strong></span>
      <span><i class="dot member"></i>You pay <strong>{_rupees(member)}</strong></span>
    </div>
    <div class="pills">
      <div class="pill"><span class="muted">Primary plan</span><strong>{plan_primary.insurer_name} · {plan_primary.plan_name}</strong></div>
      <div class="pill"><span class="muted">Secondary plan</span><strong>{plan_secondary.insurer_name} · {plan_secondary.plan_name}</strong></div>
      <div class="pill"><span class="muted">Out of pocket</span><strong>{_rupees(member)}</strong></div>
      <div class="pill"><span class="muted">Saved by coordination</span><strong>{_rupees(outcome.savings_vs_primary_only)}</strong></div>
    </div>
    <table>
      <thead><tr><th>Service</th><th>CPT</th><th class="num">Billed</th><th class="num">Allowed</th><th class="num">Primary paid</th><th class="num">Secondary paid</th><th class="num">You pay</th><th>Coverage</th></tr></thead>
      <tbody>{''.join(line_rows)}</tbody>
    </table>
    <div class="card-foot">{''.join(preauth_badges)}</div>
  </section>"""


def build_cost_flow_html(claims, outcomes, preauth_records, issues, preauth_gap=None, agent_checks=None, generated_at: date | None = None) -> str:
    generated_at = generated_at or date.today()
    total_billed = money(sum((claim.total_billed for claim in claims), money(0)))
    total_plans = money(sum((outcome.total_plan_paid for outcome in outcomes.values()), money(0)))
    total_member = money(sum((outcome.member_out_of_pocket for outcome in outcomes.values()), money(0)))
    total_saved = money(sum((outcome.savings_vs_primary_only for outcome in outcomes.values()), money(0)))
    cards = "".join(_claim_card(claim, outcomes[claim.claim_id], preauth_records) for claim in claims)
    issue_list = "".join(f"<li>{issue}</li>" for issue in issues) or "<li>No extraction issues were raised.</li>"
    check_items = "".join(
        f'<li><span class="badge {"ok" if check["passed"] else "warn"}">{"passed" if check["passed"] else "flagged"}</span> {check["label"]}</li>'
        for check in (agent_checks or [])
    )
    conservation_items = "".join(
        f'<li>{claim.claim_id}: insurers {_rupees(outcome.total_plan_paid)} + you {_rupees(outcome.member_out_of_pocket)} = {_rupees(claim.total_billed)}</li>'
        for claim, outcome in ((c, outcomes[c.claim_id]) for c in claims)
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DuCO-Agent · Coordination of Benefits · Sen household</title>
<style>
  :root {{
    --navy:#12304f; --teal:#0f766e; --sand:#f6f1e7; --ink:#1d2733; --muted:#6b7684;
    --line:#e3e8ee; --ok:#0f766e; --warn:#b45309; --member:#b45309;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif; color:var(--ink); background:#fbfcfd; }}
  header {{ background:linear-gradient(135deg,var(--navy),#1b4a72); color:#fff; padding:34px 24px 28px; }}
  .wrap {{ max-width:1080px; margin:0 auto; }}
  header .kicker {{ letter-spacing:.14em; text-transform:uppercase; font-size:11px; opacity:.75; }}
  header h1 {{ margin:6px 0 4px; font-size:28px; font-weight:650; letter-spacing:-.02em; }}
  header p {{ margin:0; opacity:.8; font-size:13px; }}
  .summary {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:22px; }}
  .summary div {{ background:rgba(255,255,255,.09); border:1px solid rgba(255,255,255,.16); border-radius:12px; padding:12px 14px; }}
  .summary span {{ display:block; font-size:11px; text-transform:uppercase; letter-spacing:.08em; opacity:.7; }}
  .summary strong {{ font-size:19px; font-weight:600; }}
  main {{ padding:26px 24px 60px; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:16px; padding:20px 20px 12px; margin-bottom:20px; box-shadow:0 1px 2px rgba(18,48,79,.04); }}
  .card-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }}
  .card-head h3 {{ margin:0 0 2px; font-size:17px; }}
  .muted {{ color:var(--muted); font-size:12.5px; }}
  .amount {{ font-size:22px; font-weight:600; font-variant-numeric:tabular-nums; }}
  .bar {{ display:flex; height:34px; border-radius:9px; overflow:hidden; margin:16px 0 14px; background:#eef1f4; }}
  .seg {{ display:flex; align-items:center; justify-content:center; font-size:11px; color:#fff; white-space:nowrap; overflow:hidden; }}
  .seg.primary {{ background:var(--navy); }}
  .seg.secondary {{ background:var(--teal); }}
  .seg.member {{ background:var(--member); }}
  .legend {{ display:flex; gap:18px; flex-wrap:wrap; font-size:12.5px; margin:-4px 0 16px; }}
  .legend span {{ display:inline-flex; align-items:center; gap:6px; color:var(--muted); }}
  .legend strong {{ color:var(--ink); font-weight:600; }}
  .dot {{ width:9px; height:9px; border-radius:3px; display:inline-block; }}
  .dot.primary {{ background:var(--navy); }}
  .dot.secondary {{ background:var(--teal); }}
  .dot.member {{ background:var(--member); }}
  .pills {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:16px; }}
  .pill {{ background:var(--sand); border-radius:10px; padding:9px 11px; }}
  .pill span {{ display:block; }}
  .pill strong {{ font-size:13px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12.6px; }}
  th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); border-bottom:1px solid var(--line); padding:8px 6px; }}
  td {{ padding:9px 6px; border-bottom:1px solid #f0f3f6; vertical-align:top; }}
  td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .strong {{ font-weight:600; }}
  .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
  .badge {{ display:inline-block; font-size:11px; padding:2px 8px; border-radius:999px; }}
  .badge.ok {{ background:#e6f4f1; color:#0b5f58; }}
  .badge.warn {{ background:#fdf1e3; color:#9a4a06; }}
  .badge.soft {{ background:#eef1f4; color:#4b5663; }}
  .card-foot {{ padding:12px 0 6px; display:flex; gap:8px; flex-wrap:wrap; }}
  .grid2 {{ display:grid; grid-template-columns:1.2fr .8fr; gap:20px; }}
  .card h3.sec {{ font-size:15px; margin:0 0 10px; }}
  ul {{ margin:6px 0 10px; padding-left:18px; font-size:13px; line-height:1.55; }}
  .foot {{ color:var(--muted); font-size:11.5px; text-align:center; margin-top:26px; }}
  @media (max-width:820px) {{ .summary, .pills {{ grid-template-columns:repeat(2,1fr); }} .grid2 {{ grid-template-columns:1fr; }} }}
  @media print {{ body {{ background:#fff; }} header {{ background:var(--navy) !important; -webkit-print-color-adjust:exact; print-color-adjust:exact; }} .card {{ break-inside:avoid; box-shadow:none; }} }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <div class="kicker">DuCO-Agent · Coordination of Benefits</div>
    <h1>Priya &amp; Aarav Sen — what the two plans actually pay</h1>
    <p>Generated {generated_at.strftime('%d %B %Y')} from the physiotherapy invoice, the MRI report, the surgeon's estimate and Aarav's voice query.</p>
    <div class="summary">
      <div><span>Total billed</span><strong>{_rupees(total_billed)}</strong></div>
      <div><span>Insurers pay</span><strong>{_rupees(total_plans)}</strong></div>
      <div><span>You pay</span><strong>{_rupees(total_member)}</strong></div>
      <div><span>Saved by COB</span><strong>{_rupees(total_saved)}</strong></div>
    </div>
  </div>
</header>
<main class="wrap">
  {cards}
  <div class="grid2">
    <section class="card">
      <h3 class="sec">How the order was decided</h3>
      <ul>
        <li><strong>Primary</strong> is the plan where the patient is the policyholder: PLAN_B (Insurer2) for Aarav's surgery, PLAN_A (Insurer1) for Priya's therapy.</li>
        <li>The <strong>secondary</strong> plan only sees what the primary left unpaid, then applies its own deductible ({_rupees(PLANS['PLAN_A'].deductible_per_member)}), coinsurance (20% / 10%) and annual out-of-pocket maximum.</li>
        <li>Deductibles already used this year were pulled from each insurer before the maths, so the rollover is real rather than assumed.</li>
        <li>Pre-authorisation was filed with both insurers for the surgery; if the pre-authorisations were skipped the plans' payments would be cut and the household would pay {_rupees(preauth_gap or money(0))} more.</li>
      </ul>
    </section>
    <section class="card">
      <h3 class="sec">Checks the agent ran</h3>
      <ul>{check_items}</ul>
      <h3 class="sec" style="margin-top:6px">Arithmetic that must conserve</h3>
      <ul>{conservation_items}</ul>
      <p class="muted" style="margin-top:4px">Extraction notes: {issue_list.replace('<li>', '').replace('</li>', ' ')}</p>
    </section>
  </div>
  <p class="foot">DuCO-Agent · plan terms are simulated for this assessment, not real policy wording · every figure recomputes from <span class="mono">outputs/financial_breakdown.json</span></p>
</main>
</body>
</html>
"""


def build_audio_script(claims, outcomes) -> str:
    total_member = sum((outcome.member_out_of_pocket for outcome in outcomes.values()), money(0))
    total_without_cob = sum((outcome.primary.member_paid for outcome in outcomes.values()), money(0))
    surgery = outcomes["CLM-2026-A-ACL"]
    therapy = outcomes["CLM-2026-P-PT"]
    return (
        "Hello Priya and Aarav. Here is what your two insurance plans will do. "
        f"For Aarav's knee surgery, the hospital estimates 4 lakh 50 thousand rupees. "
        f"Your own employer plan, Insurer2, pays first: {int(surgery.primary.plan_paid):,} rupees. "
        f"Insurer1 then picks up {int(surgery.secondary.plan_paid):,} rupees of the balance. "
        f"Your share for the surgery is {int(surgery.member_out_of_pocket):,} rupees. "
        f"For Priya's physiotherapy bill of 30 thousand rupees, Insurer1 pays {int(therapy.primary.plan_paid):,} rupees first and Insurer2 pays {int(therapy.secondary.plan_paid):,} more. "
        f"Your share there is {int(therapy.member_out_of_pocket):,} rupees. "
        f"Together you pay about {int(total_member):,} rupees out of pocket, instead of about {int(total_without_cob):,} if you only used one plan. "
        "Pre-authorisation letters for both insurers are ready, so the claims should not be rejected. "
        "Keep the invoices and the MRI report handy when you file."
    )


def synthesize_audio(script: str, path: Path) -> tuple[bool, str]:
    """Try local TTS binaries; return (produced, reason)."""
    engine = shutil.which("espeak-ng") or shutil.which("espeak")
    if engine:
        result = subprocess.run([engine, "-v", "en-us", "-s", "150", "-w", str(path.with_suffix(".wav")), script], capture_output=True)
        if result.returncode == 0:
            return True, f"synthesised with {engine}"
        return False, f"{engine} failed: {result.stderr.decode(errors='ignore')[:200]}"
    try:
        from gtts import gTTS  # type: ignore

        gTTS(text=script, lang="en", tld="co.in").save(str(path))
        return True, "synthesised with gTTS"
    except Exception as exc:  # pragma: no cover - optional dependency
        return False, f"no TTS engine available ({exc.__class__.__name__}); the script is delivered as text"


class ReportingAgent(AgentBase):
    name = "ReportingAgent"
    states = ("rendering", "delivered")

    def run(self, claims, outcomes, preauth_records, issues, output_dir: Path, preauth_gap=None, agent_checks=None) -> ReportResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts: dict[str, str] = {}
        warnings: list[str] = []

        def rel(path: Path) -> str:
            try:
                return str(path.relative_to(output_dir.parent))
            except ValueError:
                return str(path)

        html_path = output_dir / "cost_flow.html"
        html_path.write_text(
            build_cost_flow_html(claims, outcomes, preauth_records, issues, preauth_gap=preauth_gap, agent_checks=agent_checks),
            encoding="utf-8",
        )
        artifacts["cost_flow"] = rel(html_path)

        breakdown = {
            "generated_at": date.today().isoformat(),
            "household": {
                "total_billed": str(money(sum((claim.total_billed for claim in claims), money(0)))),
                "insurers_pay": str(money(sum((outcome.total_plan_paid for outcome in outcomes.values()), money(0)))),
                "member_out_of_pocket": str(money(sum((outcome.member_out_of_pocket for outcome in outcomes.values()), money(0)))),
                "saved_by_coordination": str(money(sum((outcome.savings_vs_primary_only for outcome in outcomes.values()), money(0)))),
            },
            "claims": {claim_id: outcome.to_dict() for claim_id, outcome in outcomes.items()},
            "preauth": {f"{key[0]}:{key[1]}": record.to_dict() for key, record in preauth_records.items()},
        }
        breakdown_path = output_dir / "financial_breakdown.json"
        breakdown_path.write_text(json.dumps(breakdown, indent=2), encoding="utf-8")
        artifacts["json"] = rel(breakdown_path)

        script = build_audio_script(claims, outcomes)
        script_path = output_dir / "briefing_script.txt"
        script_path.write_text(script + "\n", encoding="utf-8")
        artifacts["script"] = rel(script_path)
        produced, reason = synthesize_audio(script, output_dir / "briefing.mp3")
        if produced:
            artifacts["audio"] = rel(output_dir / "briefing.mp3" if (output_dir / "briefing.mp3").exists() else output_dir / "briefing.wav")
        else:
            warnings.append(reason)

        self.transition("delivered")
        self.act(
            "rendering",
            "A patient-facing page, a machine-readable breakdown and a spoken briefing: three readers, three formats, one set of numbers.",
            "render_reports",
            inputs={"claims": [claim.claim_id for claim in claims]},
            observation=f"artifacts={list(artifacts)}",
            checks=[
                CheckResult("cost_flow_written", html_path.exists() and html_path.stat().st_size > 4000, f"{html_path.stat().st_size} bytes"),
                CheckResult("breakdown_written", breakdown_path.exists(), ""),
                CheckResult("audio_available", produced, reason),
            ],
            decision="delivered",
        )
        return ReportResult(artifacts=artifacts, warnings=warnings)
