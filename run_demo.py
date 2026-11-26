#!/usr/bin/env python3
"""Run the whole DuCO-Agent story end to end.

    python run_demo.py                 # in-process mock insurer API
    python run_demo.py --mode http     # same story over HTTP (start the server first)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from duco_agent.orchestrator import Orchestrator  # noqa: E402


def _ensure_fixtures() -> None:
    fixtures = ROOT / "fixtures"
    required = ["priya_pt_invoice.png", "aarav_mri_report.pdf", "surgeon_estimate.jpg", "user_query.txt"]
    if all((fixtures / name).exists() for name in required):
        return
    print("Generating the mock input documents ...")
    sys.path.insert(0, str(fixtures))
    import generate_fixtures  # type: ignore  # noqa: PLC0415

    generate_fixtures.main()


def main() -> int:
    parser = argparse.ArgumentParser(description="DuCO-Agent demo")
    parser.add_argument("--mode", choices=("inprocess", "http"), default="inprocess")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765", help="mock insurer API base URL for --mode http")
    parser.add_argument("--output", default=str(ROOT / "outputs"))
    parser.add_argument("--json", action="store_true", help="print the run summary as JSON")
    args = parser.parse_args()

    _ensure_fixtures()
    output_dir = Path(args.output)
    result = Orchestrator(ROOT, output_dir, client_mode=args.mode, base_url=args.base_url).run()
    summary = result.summary()

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print("\nDuCO-Agent run complete")
    print("=" * 46)
    for claim in result.intake.claims:
        outcome = result.cob.outcomes[claim.claim_id]
        print(f"{claim.patient_name:<12} {claim.total_billed:>12}  billed")
        print(f"{'':<12} {outcome.total_plan_paid:>12}  insurers pay")
        print(f"{'':<12} {outcome.member_out_of_pocket:>12}  you pay")
    print("-" * 46)
    print(f"Saved by coordination: {result.cob.total_savings}")
    print(f"Cost of skipping pre-auth: {result.cob.preauth_gap_cost}")
    print("\nArtifacts:")
    for name, path in result.artifacts.items():
        print(f"  {name:<16} {path}")
    if result.warnings:
        print("\nWarnings:")
        for warning in result.warnings:
            print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
