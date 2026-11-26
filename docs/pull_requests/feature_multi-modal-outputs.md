# feature/multi-modal-outputs

## What this adds

The deliverables and the supervisor that produces them.

- `duco_agent/agents/compliance.py` — checks each claim/plan pair for a pre-auth requirement, files it against the mock API, and renders a letter per insurer carrying member details, provider registration, diagnosis and CPT codes, amounts and the coordination position.
- `duco_agent/engines/preauth.py` — the letter template (ReportLab, print-ready).
- `duco_agent/agents/reporting.py` — the printable cost-flow page (self-contained HTML), the machine-readable breakdown and the spoken briefing (local TTS when available, script otherwise).
- `duco_agent/orchestrator.py` — goals with dependencies, dispatch, a critic over the finished artifacts, and the trace of the whole run.
- `run_demo.py` — one command, in-process or HTTP mock APIs.

## Evidence

- `pytest tests/test_pipeline.py` — retry loop accepts the second attempt and traces both; a full run writes every artifact, both letters exist, both claims conserve, and the pre-auth gap and COB saving are positive.
- `outputs/` in this branch is a reference run: cost flow page, breakdown JSON, two letter PDFs, briefing MP3 and the full trace.

## Notes for review

The critic is deliberately strict: a missing artifact or a claim whose payments do not conserve sends the run into a repair pass and is recorded as a failed check. The report page prints the checks it passed, so a reader can see what was verified rather than taking the numbers on trust.
