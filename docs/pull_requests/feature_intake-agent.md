# feature/intake-agent

## What this adds

The document layer and the first agent: everything between "four files a household would hand you" and "two claims with codes".

- `fixtures/generate_fixtures.py` produces the four mock inputs: a rotated, shaded phone scan of a physiotherapy invoice with handwritten notes and **no billing codes**, an MRI report PDF, a photographed surgical estimate, and a voice-to-text transcript.
- `duco_agent/tools/ocr.py` runs Tesseract with three named preprocessing variants and reports mean word confidence.
- `duco_agent/extraction.py` parses each document into fields that carry a confidence and a source (`ocr`, `derived`, `inferred`, `cross-checked`); the invoice total is reconciled against the sum of its lines, and an unreadable quantity is derived from `amount ÷ rate`.
- `duco_agent/codes.py` is a small CPT/ICD catalogue with fuzzy matching, used to recover the codes the invoice omits (97161, 97110, M54.5).
- `duco_agent/agents/intake.py` treats each OCR pass as a hypothesis: it scores the pass on evidence and retries with another variant when a check fails, then infers codes, maps the MRI findings to S83.511A / S83.241A, and builds the two claims.
- `duco_agent/models.py`, `config.py` and `tools/pdf.py` provide the shared domain types and plan terms the later branches build on.

## Evidence

- `pytest tests/test_extraction.py` — noisy-text parsing, reconciliation failure detection, MRI findings, transcript goals, code inference.
- The intake trace records the pass used, its checks and the decision, e.g. `"settled on the 'clean' pass (mean OCR confidence 87.6)"`.

## Notes for review

The invoice is deliberately brutal: two of the three quantity cells are illegible after the scan effect. The parser never guesses a quantity it cannot derive; it derives it from the amounts and flags the line when even that fails.
