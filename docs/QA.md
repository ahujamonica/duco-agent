# QA evidence

Run everything:

```bash
python -m pytest -q
```

Latest run in this workspace: **40 passed** (engine, extraction, API, workflow, reports). Tests use a temporary SQLite database and data directory via `tests/conftest.py`; the demo database is untouched.

## Inventory

| Area | Tests |
| --- | --- |
| Decimal engine | `tests/test_coordination_engine.py` — deductible/co-insurance, secondary residual, no double payment, OOP cap, annual limit, sub-limit, exclusions, policy covering primary exclusions, pre-auth penalty, inactive policy, waiting period, three plans, contractual adjustment, accumulators, explain decomposition |
| Original assessment engine | `tests/test_cob_engine.py` — legacy CLI scenario |
| Extraction | `tests/test_extraction.py` — invoice parsing, MRI narrative, estimate, transcript |
| Pipeline | `tests/test_pipeline.py` — original end-to-end CLI run |
| Auth and ownership | `tests/test_platform.py` — register/login/401, cross-household 404 |
| Dynamic household | members, roles, many-to-many policy links, unique policy number, active/inactive |
| Policy import | policy PDF extraction (insurer, number, sum insured, deductible, co-insurance), confidence, editing creates a version |
| Documents | upload, classification, OCR confidence, field values, dedupe |
| Human review | case pauses, review items accepted, resume, complete |
| Results | reconciliation, excluded amount, invariants, traces, tasks, explain, what-if |
| Reports | JSON/HTML/trace/audio registered; JSON download; PDF letter includes request-not-approval |
| Mock insurers | eligibility/ineligible, benefits, claims, claim lookup, rejected pre-auth |
| Edge cases | inactive policy kept but unpaid, duplicate upload, missing diagnosis, unknown codes |
| Code resolution | CPT/ICD candidates with confidence |

## Manual acceptance scenario

1. `make demo` and open <http://127.0.0.1:8000>.
2. **Explore demo** → the Sen household is seeded; the ACL case opens.
3. **Start the analysis** → eight goals complete; trace shows every agent.
4. **Open results** → totals, cost flow, per-line table, payer order, gaps, letters, explain and simulator.
5. **Letters** → two PDFs with request-not-approval language.
6. **Cases** → open the poor-quality scan → run → it pauses; open **Review**, accept/correct fields, submit → the run resumes and completes.
7. **Family / Policies / Documents** → add a member, add a policy, upload a document; create a second household and confirm its cases are separate.
8. **Settings** → switch Hindi/English; export data; check the security notes.

## What is deliberately not tested

- Real insurer/TPA APIs (none exist in this build).
- Browser visual regression and screen-reader certification.
- Load/performance testing beyond single-request manual checks.
- LLM enrichment with a live API key (the disabled path is exercised; the adapter is optional and isolated).
- TTS when the network is unavailable (the fallback path writes a script and is handled, but CI runs with network).
- Production deployment hardening (see `docs/SECURITY.md`).
