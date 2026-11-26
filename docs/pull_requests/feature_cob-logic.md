# feature/cob-logic

## What this adds

The money: coordination-of-benefits arithmetic and the agents that decide who pays first.

- `duco_agent/engines/cob_engine.py` — deterministic adjudication with deducted-then-coinsured allowed amounts, year-to-date deductible rollover, per-member out-of-pocket maxima, pre-authorisation penalties and excluded benefits. The secondary plan only ever sees the residual the primary left on covered services.
- `duco_agent/mock_api/` — eligibility, benefits/accumulators, pre-auth submission and claim adjudication for both plans, behind one service module and two transports (in-process and a stdlib HTTP server).
- `duco_agent/agents/coverage.py` — verifies eligibility and the primary/dependent role per plan and pulls the accumulators from the insurer before any maths; role mismatches become warnings, not silent assumptions.
- `duco_agent/agents/cob.py` — resolves the order per claim, runs a preliminary adjudication with no pre-authorisation to measure the penalty, then the final one, and validates conservation, allowed-amount and secondary-residual invariants.

## Evidence

- `pytest tests/test_cob_engine.py` — deductible and coinsurance, OOP maximum, pre-auth penalty, exclusions, secondary-only-residual, conservation of every claim.
- Worked examples in `docs/COB_RULES.md` reproduce the engine's numbers by hand.

## Notes for review

`ClaimOutcome.member_out_of_pocket` is `primary.member_paid − secondary.plan_paid`: the secondary payment comes out of the residual, so adding the two member shares would double-count. A test pins the invariant `plan_paid + member_out_of_pocket = billed`.
