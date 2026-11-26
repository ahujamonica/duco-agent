# Build progress

## 2026-11-26 — original assessment (preserved)

The offline CLI assessment is intact: generated fixtures, OCR retry loop, extraction with confidence, the original COB engine, in-process/HTTP mock insurer APIs, specialist agents, a supervisor with a critic, a printable cost flow, two pre-auth letters, a briefing and 16 tests. See `run_demo.py` and `docs/ARCHITECTURE.md`.

## 2026-11-26 — dynamic platform

### Phase 0/1 — inspect and preserve
- Read the existing repository and kept the working engine, extraction, mock APIs, agents and tests.
- Committed the caller-supplied-plan refactor before layering the platform on top.

### Phase 2 — dynamic data and APIs
- Added users, families, members, policies, policy versions, policy-member links, per-member accumulators, documents, cases, claims/lines, reviews, agent events, eligibility checks, adjudications, pre-authorisations, mock claims/logs, reports and simulator runs.
- Added JWT auth with PBKDF2 hashing and owner-scoped access.
- Built family, member and versioned policy APIs; policy numbers are unique; edits create versions.

### Phase 3 — document intelligence
- Validation, SHA-256 dedupe, PDF text/OCR retries with three preprocessing variants, classification with evidence, per-type parsing, curated CPT/ICD matching, field-level confidence from real OCR/PDF signals, reconciliation and review flags.
- Optional LLM enrichment is isolated and off by default; it never overwrites confident values.

### Phase 4 — agents
- Persisted supervisor graph with eight goals and dependencies; nodes call real tools and the mock insurer API.
- Human review pauses before money; corrections write back and resume. Trace records every decision.
- Payer order is configurable; assumptions and evidence are exposed.

### Phase 5 — financial engine
- New generic Decimal engine supporting N plans, deductibles, co-insurance, OOP, annual limits, sub-limits, exclusions, waiting periods, network rules, pre-auth penalties, contractual adjustments and per-member accumulators.
- Ten invariant checks; recalculation then human hold on failure.
- Re-runs reverse prior accumulator deltas (including sub-limits) so results are idempotent.

### Phase 6/7 — frontend
- React 18 + Vite + TypeScript + Tailwind; 14 screens; EN/HI labels; dashboard graph, cost flow, donut, line tables, explain drawer, what-if simulator, gap detector, letters, settings.
- Connected entirely to the API; no static placeholder numbers in live mode.

### Phase 8 — reports
- JSON breakdown, printable HTML, execution trace, PDF pre-auth letters, audio briefing with script fallback.
- Downloads are owner-checked and no-store.

### Phase 9 — QA
- 39 tests pass, including end-to-end review → adjudication → reports and dynamic mock outcomes.
- Full stack exercised in the browser: landing, demo, run, results, lines, simulator, letters, dashboard, family, policies, documents.

### Phase 10 — documentation
- README, platform architecture, coordination rules with a worked example, security posture, QA evidence, Makefile, env example and demo seed script.

### Known open items
- Real insurer/TPA integration (mock only, clearly labelled).
- Production security gaps documented in `docs/SECURITY.md`.
- No Redis/worker queue; a single in-process background thread runs a case.
- Contribution-basis settlement is disclosed as an assumption, not implemented as an alternative engine.
