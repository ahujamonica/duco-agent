# Platform architecture

## Purpose and users

DuCO Agent serves a household, not a single patient. A signed-in owner creates one or more households, adds members and policies, uploads the paperwork for a medical episode, and runs a supervised agent workflow that ends in an auditable cost split.

Two entry journeys share one backend:

- **Live case.** Create household → members → policies → documents → case → human review → agent run → results/letters.
- **Explore demo.** A seeded household with five scenarios. The same tables, agents, engine and mock insurer endpoints are used. There is no separate result page.

## Runtime topology

```
Browser (React 18 + Vite + Tailwind)
        │  JWT bearer
        ▼
FastAPI (server/main.py)
        ├── routers/         auth, families, policies, documents, cases, mock, workspace, demo
        ├── services/        document pipeline, coverage, accumulators, insurer mock, results, reports, demo
        ├── agents/          persisted supervisor graph + 8 nodes
        └── duco_agent/      pure OCR/PDF tools, code catalogue, Decimal engine
        ▼
SQLAlchemy → SQLite (data/duco.db)
Filesystem → data/uploads, data/reports, data/audio
```

The frontend is built into `web/dist`; FastAPI mounts it and falls back to `index.html` for client-side routes. In development Vite runs on `:5173` and proxies `/api` and `/mock-insurers` to `:8000`.

## Database entities

| Entity | Why it exists |
| --- | --- |
| `User` | Account, password hash, locale |
| `Family` | Household, owner, default coordination rule |
| `FamilyMember` | Person, DOB/age, relationship, notes |
| `Policy` / `PolicyVersion` | Insurer/plan identity; versioned benefit terms |
| `PolicyMember` | Many-to-many membership with a role per policy |
| `PolicyAccumulator` | Per-member deductible/OOP/annual-limit/sub-limit usage |
| `Document` | Stored file metadata, classification, method, confidence, fields, lines, issues |
| `Case` | Episode, patient, selected policy versions, documents, workflow state, totals |
| `Claim` / `ClaimLine` | One bill/estimate per claim, service lines with codes and confidence |
| `ReviewItem` | Human-in-the-loop field correction |
| `AgentEvent` | Full execution trace, one row per step |
| `EligibilityCheck` | Mock insurer eligibility + benefits request/response |
| `Adjudication` | Per-plan, per-claim result and line-level JSON |
| `Preauthorization` | Required/not required, simulated response, letter link |
| `MockClaim` / `MockApiLog` | Simulated claim records and API request/response logs |
| `Report` | Generated JSON/HTML/PDF/audio/trace artefacts |
| `SimulatorRun` | Hypothetical what-if runs; never touches the claim |

Money columns are `Numeric(14,2)`. JSON columns hold structured extractions and results; they are not used as a substitute for the calculation tables.

## Case lifecycle

```
draft ──► ready ──► running ──► complete
  │        │          │
  │        │          ├─► awaiting_review (confidence gate; resume after review)
  │        │          └─► failed        (blocking gap or unhandled error)
  │        └─► awaiting_review (review before first run)
  └─► (needs documents / policy)
```

`Case.workflow_state` is the checkpoint: task statuses, stage, result summary, gaps, assumptions, pre-auth statuses, applied accumulator deltas and per-claim results. The supervisor updates it after every node and after every task transition.

## Supervisor and nodes

`server/agents/runtime.py` implements:

- a static goal graph with dependencies (`TASK_GRAPH`);
- a dispatcher that chooses the next pending goal whose prerequisites are done;
- one `RunContext` per run that records events and persists state;
- accumulator reversal before a re-run;
- a background-thread entry point used by `POST /api/cases/{id}/analyze`.

`server/agents/nodes.py` implements:

| Node | What it actually does |
| --- | --- |
| Intake | Validates household, patient, policies, documents and manual lines; auto-selects policies only when none were chosen and records that assumption |
| Documents | Runs validation/classification/OCR extraction, writes review items, pauses on the confidence gate, applies corrections, builds claims, links radiology diagnosis candidates |
| Coverage | Calls the mock eligibility and benefits endpoints per member/policy, stores every request/response, records ineligible policies without dropping them |
| COB | Applies the configured rule, records evidence and assumptions, publishes payer order |
| Compliance | Computes pre-auth requirement with the engine, submits mock pre-auth requests, tracks approved/pending/rejected, records gaps |
| Financial | Loads per-member accumulators, calls the engine per claim, writes adjudications, checks invariants, retries once, persists accumulator deltas and totals |
| Reporting | Writes JSON, HTML, letters, audio/script and trace; registers each artefact |
| Critic | Verifies claims, adjudications, invariants, reports, letters and trace; holds the case rather than declaring success when something is missing |

The workflow pauses on review **before** coverage/financial. Review items are regenerated from the documents, and corrections are written back with `source: reviewed`, `confidence: 1.0`.

## Document pipeline

1. Validate extension, MIME and size; reject unknown types.
2. SHA-256 duplicate detection within the household.
3. Extract text:
   - TXT → transcript
   - PDF with ≥80 characters per page → embedded text (`pdf_text`)
   - scanned PDF → rasterise up to 4 pages at 200 dpi and OCR
   - image → OCR with `auto-layout`, `block`, `binarised` preprocessing, scored and retried
4. Classify from filename + keyword evidence; return confidence and evidence. A user-selected type wins but conflicts are recorded.
5. Parse fields and service lines for that document type.
6. Resolve codes: printed code, inferred candidate (confidence) or unavailable.
7. Optional LLM enrichment (only if configured), filling low-confidence/missing fields with `source: llm` and review status.
8. Reconcile line totals against the printed total; flag mismatches.
9. Persist fields with per-field confidence/source/evidence; set `needs_review` when required fields, codes or totals are uncertain.

Confidence is never invented. OCR fields are capped at 95% and scaled by measured OCR confidence; PDF text fields use a base confidence for exact matches; derived values are capped at 80%.

## Results and simulation

`server/services/results.py` reads the stored adjudication JSON rather than recalculating money. It produces the totals, per-line plan detail, payer order, gaps, pre-auth list, accumulators, savings vs primary-only and reports list. `explain_line` walks the stored plan-line numbers.

The simulator loads the claim lines, applies overrides to the *policy terms* in memory, reruns the pure engine and records a `SimulatorRun`. It never writes claim/adjudication/accumulator rows.

## Demo isolation

A real household shares benefit-year accumulators across cases. The demo needs reproducible scenarios, so each non-main scenario gets its own policy-version snapshot (`source: demo`). This is visible on the policy page as another version and does not affect a live household.

## Extension points

- **Real insurer integration:** replace `MockInsurerService` with an adapter that keeps the same request/response contract; the agents already call it through a service boundary. Add credential storage and per-insurer mapping.
- **Queue:** move `start_run_async` to a Celery/RQ worker; the checkpoint in `Case.workflow_state` is already durable. Replace the in-process status guard with a distributed lock.
- **PostgreSQL:** set `DUCO_DATABASE_URL`; the models use standard SQLAlchemy types. Test JSON queries and Numeric rounding on the target version.
- **LLM extraction:** configure `DUCO_LLM_API_KEY`/`DUCO_LLM_MODEL`/`DUCO_LLM_BASE_URL`; the adapter is already in `server/services/llm.py`.
- **Clinical coding:** swap the curated catalogue for a licensed CPT/ICD service and add clinician sign-off states.
- **i18n:** the dictionary is in `web/src/lib/i18n.tsx`; document content remains in its source language.
