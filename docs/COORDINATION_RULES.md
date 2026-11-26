# Coordination rules and the calculation contract

This document describes the **platform** engine in `duco_agent/engines/coordination.py`. The original assessment engine and its rules remain in `duco_agent/engines/cob_engine.py` and `docs/COB_RULES.md` for the legacy CLI demo.

## 1. Inputs

For one claim: service lines (description, quantity, unit rate, billed amount, CPT, ICD list, category, excluded flag), provider, service date, in-network flag.

For each plan: insurer, plan, policy number, version, status, start/end dates, waiting period, sum insured, deductible (total and used), member co-insurance fraction, OOP maximum and used, annual limit and used, sub-limits (codes/categories, limit, used, per-year or per-claim), exclusions (code/keyword), pre-auth threshold/list/always flag/penalty rate, allowed factor, network-only flag, covers-primary-exclusions flag, and the member's role.

Per-member accumulators are loaded from `PolicyAccumulator`, not from the policy row. The policy schedule's "used" values seed only the policyholder on first use.

## 2. Payer order

The engine receives an explicit ordered list. `server/services/coverage.py` decides it:

- **policyholder:** policyholder plans first; then by earliest start date.
- **birthday:** policyholder with the earlier birthday in the year; missing DOB falls back to start date with an assumption.
- **longest_coverage:** earliest start date.
- **manual:** caller-supplied policy IDs; unknown IDs go last.

Active policies are placed before inactive ones in every rule. Ineligible policies remain in the list so the trace and UI can explain why they did not pay.

The birthday rule is a US convention. Indian indemnity policies may settle on a contribution basis instead; the platform records that as an assumption on every multi-plan case.

## 3. Per-line, per-plan order

For plan *k* in order:

1. **Eligibility.** Policy status, service date within period, waiting period, member role, network (if network-only and provider out of network) → plan skipped, nothing changes.
2. **Base.** Primary: billed. Later plan: the covered residual left by earlier plans, plus previously excluded amounts only if this plan sets `covers_primary_exclusions`.
3. **Policy exclusion.** If the line matches this plan's exclusion, the whole base becomes patient liability for this plan; plan pays zero.
4. **Sub-limit.** A matching sub-limit caps the eligible amount. The excess becomes patient liability. Usage is consumed by the allowed amount, separately per claim and across the benefit year.
5. **Contractual rate.** `allowed × allowed_factor`; the difference is a write-off, not patient liability.
6. **Deductible.** `min(remaining deductible, allowed)`.
7. **Co-insurance.** `(allowed − deductible) × member_rate`; the plan pays the rest.
8. **Pre-auth penalty.** If the plan requires pre-authorisation and the request is not approved, `plan_paid × penalty_rate` moves to the patient. Approved requests incur no penalty.
9. **OOP maximum.** If the member's covered cost share exceeds the remaining OOP, the plan absorbs the excess (up to its allowed amount).
10. **Annual limit.** If the plan payment exceeds the remaining annual limit, the excess moves to the patient and does **not** count toward the OOP maximum (the benefit is exhausted).

Then the line's covered residual becomes `allowed − plan_paid`; the next plan sees it. Excluded/sub-limit amounts remain outside the residual unless the next plan explicitly covers primary exclusions.

## 4. Totals

For each line:

```
billed = contractual_adjustment + Σ insurer_payments + patient_liability
allowed = billed − contractual_adjustment − excluded
patient_liability = deductible + co-insurance + pre-auth penalty + sub-limit excess
                    + annual-limit excess + exclusions
```

The engine builds the patient decomposition by taking the first payer's charges and reducing them with each later plan's payment (oldest buckets first: deductible → co-insurance → penalty → sub-limit → benefit limit → excluded). This is what “Explain My Bill” displays; the decomposition always sums to the line's patient amount.

For the claim and case:

```
billed = Σ line billed
insurer_paid = Σ plan payments
patient_liability = Σ line patient
```

## 5. Invariants

Every run checks:

1. `insurer_paid + patient_liability + contractual_adjustment == billed`
2. `excluded + allowed + contractual_adjustment == billed`
3. `patient_liability == Σ line patient`
4. every plan payment ≤ its allowed amount on that line
5. a secondary payment ≤ the residual base it received
6. deductible used ≤ deductible total
7. annual limit used ≤ annual limit
8. each sub-limit used ≤ its limit
9. no negative amounts
10. a pre-auth penalty is disclosed when it applies

If any invariant fails, the Financial agent recalculates once, then holds the case for review instead of publishing a number.

## 6. Accumulators

- Key: `(policy_version_id, member_id)`.
- Updated after a successful run: deductible, OOP, annual limit, sub-limit usage.
- A re-run of the same case first reverses the deltas recorded by its previous run, then recalculates. This includes sub-limit usage, so running the demo twice produces the same result.
- A later case for the same member and benefit year starts from the persisted accumulators.
- A policy edit creates a new version with its own accumulators; existing claims keep the version they used.

## 7. Worked example (seeded demo, verified)

Household: Priya and Aarav. Policies: ICICI Lombard (Priya policyholder; 5,000 deductible, 1,500 used; 20% co-insurance; 60,000 OOP; 20,000 annual therapy sub-limit; equipment excluded) and HDFC ERGO (Aarav policyholder; 5,000 deductible, 2,000 used; 10% co-insurance; 80,000 OOP; 400,000 annual limit; equipment excluded).

### Priya — physiotherapy, ₹30,000

| Line | Billed | Primary ICICI | Secondary HDFC | Patient |
| --- | ---: | ---: | ---: | ---: |
| Evaluation 97161 | 3,500 | 0 (deductible) | 0 (deductible) | 3,500 |
| Therapeutic exercise 97110 ×12 | 24,000 | 13,200 (16,500 after 7,500 sub-limit, 20% co-ins) | 1,620 | 9,180 |
| Home traction equipment | 2,500 | 0 (excluded) | 0 (excluded) | 2,500 |
| **Total** | **30,000** | **13,200** | **1,620** | **15,180** |

### Aarav — ACL reconstruction, ₹4,50,000

| Line | Billed | Primary HDFC | Secondary ICICI | Patient |
| --- | ---: | ---: | ---: | ---: |
| 29888 ACL reconstruction | 3,50,000 | 3,12,300 | 26,160 | 11,540 |
| 29881 Meniscectomy | 1,00,000 | 87,700 (annual limit reached) | 9,840 | 2,460 |
| **Total** | **4,50,000** | **4,00,000** | **36,000** | **14,000** |

### Household

| Billed | Insurers | Patient | Contractual adjustment | Excluded |
| ---: | ---: | ---: | ---: | ---: |
| ₹4,80,000 | ₹4,50,820 | ₹29,180 | ₹0 | ₹2,500 |

The split is ₹4,13,200 primary + ₹37,620 secondary + ₹29,180 patient = ₹4,80,000. Two pre-authorisation requests were approved; the letters are generated for both insurers.

## 8. Modelling assumptions to disclose

- Primary/secondary ordering is a modelling choice; a contribution clause can produce a different patient share.
- The policy's “used this year” amounts seed the policyholder only; dependants start at zero unless their own accumulators exist.
- Sub-limits are consumed by the allowed amount; an insurer may define consumption differently.
- The network discount is applied before the deductible; real contracts may apply it differently.
- Pre-authorisation pending is treated as not approved, so the policy penalty applies until approval.
- A policy's annual limit is separate from its sum insured; both are stored and the annual limit is the one enforced.
- Non-covered amounts do not count toward the OOP maximum.
