> **Legacy note:** this document describes the original offline CLI assessment (`run_demo.py`, `duco_agent/engines/cob_engine.py`). The dynamic platform is documented in [`PLATFORM.md`](PLATFORM.md) and [`COORDINATION_RULES.md`](COORDINATION_RULES.md).

# Architecture

## Layers

| Layer | Modules | Responsibility |
| --- | --- | --- |
| Documents | `fixtures/generate_fixtures.py`, `tools/ocr.py`, `tools/pdf.py` | Produce and read the four mock inputs |
| Extraction | `extraction.py`, `codes.py` | Field-level parsing with confidence; CPT/ICD inference |
| Domain | `models.py`, `config.py` | Claims, plans, accumulators, adjudication records |
| Engine | `engines/cob_engine.py`, `engines/preauth.py` | Deterministic COB arithmetic; letter rendering |
| Agents | `agents/*` | Reasoning, tool calls, validation and reflection |
| Supervisor | `orchestrator.py` | Goals, dispatch, critic, trace |
| Transport | `mock_api/service.py`, `mock_api/server.py`, `tools/insurer_api.py` | Mock insurer APIs over two transports |

## Agent loop

Every agent extends `AgentBase` and records each step as:

```
thought  → action → observation → checks[] → decision
```

`TraceRecorder` writes them to `outputs/run_trace.json`. `retry_loop()` formalises the repair pattern: run an attempt, judge it by its checks, and either accept it or try another strategy, keeping every attempt on the trace. The intake agent uses it for OCR variants; the supervisor uses the same idea in the critic stage.

### States

`IntakeAgent` — `intake → extracting → coding → validated` (or `blocked`)
`CoverageAgent` — `coverage → verified`
`COBAgent` — `ordering → adjudicating → validated`
`ComplianceAgent` — `checking → filing → drafted`
`ReportingAgent` — `rendering → delivered`

Transitions are guarded: an unknown state raises, so the state machine cannot silently drift.

## The supervisor

```
goals = [
  extract_and_code,            # IntakeAgent
  verify_coverage,             # depends on extract_and_code
  check_preauth_need,          # depends on verify_coverage
  file_preauth_and_letters,    # depends on check_preauth_need
  adjudicate_cob,              # depends on file_preauth_and_letters
  render_outputs,              # depends on adjudicate_cob
  critic_review,               # depends on render_outputs
]
```

The loop takes the first pending goal whose dependencies are done. A failure marks the goal failed, records the exception, and stops the run rather than shipping partial numbers. The critic then checks that every expected artifact exists, every claim's arithmetic conserves, and every required pre-auth has a letter on disk; a failed check triggers a repair pass before the run is declared finished.

## Data flow for one claim

```
Claim(lines) ──► CoverageAgent ──► (primary plan, secondary plan, accumulators)
      │
      ├─► COBAgent.preliminary  (no pre-auth)  ──► penalty detected
      │            │
      │            └─► ComplianceAgent ──► pre-auth references + letter PDFs
      │
      └─► COBAgent.run (with pre-auth) ──► Adjudication × 2 ──► ClaimOutcome
                                          │
                                          └─► ReportingAgent ──► HTML / JSON / MP3
```

`ClaimOutcome.member_out_of_pocket = primary.member_paid − secondary.plan_paid`, because the secondary payment comes out of the balance the primary left. Conservation — `primary.plan_paid + secondary.plan_paid + member_out_of_pocket = billed` — is asserted by the engine tests and re-checked by the critic.

## Trace format

```json
{
  "index": 21,
  "agent": "ComplianceAgent",
  "state": "filing",
  "thought": "...file the pre-authorisation and render the letter...",
  "action": "submit_preauth_and_draft_letter",
  "inputs": {"claim_id": "CLM-2026-A-ACL", "plan_id": "PLAN_B", "role": "primary"},
  "observation": "reference=PA-B-01001, letter=CLM-2026-A-ACL_PLAN_B.pdf (3833 bytes)",
  "checks": [
    {"name": "submission_approved", "passed": true, "detail": "PA-B-01001"},
    {"name": "letter_written", "passed": true, "detail": "3833 bytes"}
  ],
  "decision": "letter ready to send"
}
```

## Extension points

* **New document type** — add a parser in `extraction.py` and register it in `PARSERS`; the intake agent's retry loop handles the rest.
* **New insurer** — add `PlanTerms` in `config.py` plus member accumulators; the engine and mock API pick it up.
* **Real APIs** — implement the same four calls in `tools/insurer_api.py` (`eligibility`, `benefits`, `submit_preauth`, `submit_claim`); no agent changes.
* **An LLM in the loop** — the `AgentBase.act` boundary is the natural place to let a model choose among candidate actions; the checks and the trace stay as they are.
