# Build progress

## 2026-11-26

- Read the assessment brief: DuCO-Agent, agentic + multi-modal COB system, deadline 6:00 PM IST 27 Nov.
- Wrote the report skeleton, domain model, plan terms and the benefit-rules doc first, so the arithmetic had a written contract before any agent code.
- Generated the four mock inputs (scanned invoice without codes, MRI PDF, estimate photo, voice transcript) and tuned the scan effect until OCR was realistic but fair.
- Built extraction with per-field confidence and an OCR retry loop; wired the CPT/ICD inference for the uncoded invoice.
- Built the COB engine (primary/secondary, deductibles, coinsurance, OOP maximum, pre-auth penalty, exclusions) with tests.
- Added the mock insurer APIs (in-process + stdlib HTTP) and the coverage agent that verifies roles and accumulators before any maths.
- Added the compliance agent (pre-auth requirement check, filing, letter rendering) and the second COB pass that turns the penalty into a saving.
- Added reporting: printable cost-flow page, JSON breakdown, spoken briefing.
- Supervisor loop with goals, critic and trace; full demo runs end to end.

### Decisions

- Deterministic maths in a pure engine, agentic control above it — so every rupee is explainable and testable.
- Plan terms are simulated and labelled as such; the letters are drafts, and the report says so.
- Two adjudications by design: the first measures the pre-auth penalty, the second is what the household sees.
- The demo runs offline (local Tesseract, in-process mock APIs); gTTS is optional and only used for the audio sample.

### Still open

- Publish to GitHub as a private repository, open the three pull requests, invite the reviewer. (Blocked on GitHub access from the workspace.)
