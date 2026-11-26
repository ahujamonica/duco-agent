> **Legacy note:** these are the benefit rules for the original offline CLI scenario. The platform's generic engine is documented in [`COORDINATION_RULES.md`](COORDINATION_RULES.md).

# Coordination-of-benefits rules used by the engine

> The plan terms in `duco_agent/config.py` are **simulated for this assessment**. They are typical of Indian group health policies (per-member deductible, coinsurance, annual out-of-pocket maximum, pre-authorisation above a threshold) but they are not anyone's actual policy wording, and the letters the system drafts are drafts.

## 1. Which plan pays first

The **primary** plan is the one where the patient is the policyholder — their own employer plan:

| Patient | Primary | Secondary |
| --- | --- | --- |
| Aarav Sen | PLAN_B — Insurer2, HealthGuard Plus | PLAN_A — Insurer1, SecureShield Corporate Health |
| Priya Sen | PLAN_A — Insurer1, SecureShield Corporate Health | PLAN_B — Insurer2, HealthGuard Plus |

(The "birthday rule" and the "longer coverage" rule exist for children and for two policies covering the same person as a dependent; neither applies here, where each adult is primary on their own employer plan.)

## 2. Plan terms

| | PLAN_A (Insurer1) | PLAN_B (Insurer2) |
| --- | --- | --- |
| Deductible per member per year | ₹5,000 | ₹5,000 |
| Coinsurance (member share after deductible) | 20% | 10% |
| Out-of-pocket maximum per member per year | ₹60,000 | ₹80,000 |
| Pre-authorisation threshold | ₹50,000 or any surgical code | ₹50,000 or any surgical code |
| Penalty if pre-auth is skipped | 20% of the plan payment | 25% of the plan payment |
| Physiotherapy session limit | 20 per year | 15 per year |
| Home traction equipment | excluded | excluded |

Year-to-date accumulators used in the demo:

| Plan | Member | Deductible used | OOP used |
| --- | --- | ---: | ---: |
| PLAN_A | Priya | ₹1,500 | ₹1,500 |
| PLAN_A | Aarav | ₹0 | ₹0 |
| PLAN_B | Priya | ₹0 | ₹0 |
| PLAN_B | Aarav | ₹2,000 | ₹2,000 |

## 3. Primary adjudication

For each line:

1. **Allowed amount** = billed amount for covered services. Excluded items (the traction equipment) are allowed at zero and stay the member's cost. Therapy lines are capped at the plan's annual session limit.
2. **Deductible** = `min(remaining deductible, allowed)`.
3. **Post-deductible** = `allowed − deductible`.
4. **Plan pays** = `post-deductible × (1 − coinsurance)`; **member coinsurance** is the rest.
5. **Pre-auth penalty** — if the plan required pre-authorisation and it was not obtained, the plan payment is reduced by the penalty rate and that amount moves to the member.
6. **Out-of-pocket maximum** — if the member's share (deductible + coinsurance + penalty) would exceed the remaining OOP room, the plan absorbs the excess.

## 4. Secondary adjudication

The secondary plan only looks at what the primary left unpaid **on covered services**:

1. **Eligible for the secondary** = `min(what the secondary would allow, what the primary left unpaid on that line)`.
2. The secondary's own deductible, coinsurance and pre-auth penalty apply to that residual.
3. The secondary never pays more than the residual, and never more than it would have paid as primary.

The household's final cost is `primary member share − secondary plan payment`. Non-covered items remain the household's cost and are never counted twice.

## 5. Worked example — Aarav's surgery

Billed ₹4,50,000 (CPT 29888 ₹3,50,000 + CPT 29881 ₹1,00,000). Insurer2 is primary.

**PLAN_B, primary**

| Step | Calculation | Amount |
| --- | --- | ---: |
| Allowed | both lines covered | ₹4,50,000 |
| Deductible | ₹5,000 − ₹2,000 already used | ₹3,000 |
| Post-deductible | ₹4,50,000 − ₹3,000 | ₹4,47,000 |
| Coinsurance 10% | ₹4,47,000 × 10% | ₹44,700 |
| Plan pays | 90% of ₹4,47,000 | ₹4,02,300 |
| Member after primary | ₹3,000 + ₹44,700 | ₹47,700 |

**PLAN_A, secondary**

| Step | Calculation | Amount |
| --- | --- | ---: |
| Eligible | min(₹4,50,000 allowed, ₹47,700 left unpaid) | ₹47,700 |
| Deductible | full ₹5,000 (Aarav has used none on PLAN_A) | ₹5,000 |
| Post-deductible | ₹42,700 | |
| Coinsurance 20% | ₹8,540 | |
| Plan A pays | ₹34,160 | |
| Member pays | ₹13,540 | |

**Result:** insurers pay ₹4,36,460; Aarav pays ₹13,540. Without coordination the same bill would leave ₹47,700 with the household — coordination is worth ₹34,160 here.

## 6. Worked example — Priya's physiotherapy

Billed ₹30,000: evaluation ₹3,500, twelve sessions of therapeutic exercise ₹24,000, traction equipment ₹2,500 (excluded, and not claimed).

**PLAN_A, primary:** deductible ₹3,500 (of ₹5,000, ₹1,500 already used) → ₹24,000 at 20% coinsurance → plan pays ₹19,200, member pays ₹8,300 (plus ₹2,500 equipment = ₹10,800).

**PLAN_B, secondary:** eligible = ₹8,300 → deductible ₹5,000 → ₹3,300 at 10% → plan pays ₹2,970, member pays ₹5,330.

**Result:** insurers pay ₹22,170; Priya pays ₹7,830 instead of ₹10,800.

## 7. Pre-authorisation

A claim needs pre-authorisation when it contains a surgical code (29888, 29881, 29870) or when its covered total exceeds the plan's threshold (₹50,000). If it is skipped, the penalty applies to the plan payment and the household absorbs the difference; the engine quantifies that before the compliance agent files anything. In this scenario filing both letters is worth **₹17,740**.

The letters carry: member and relationship, policy and plan, provider and registration, planned date, diagnosis codes with descriptions, CPT lines with amounts, the clinical justification, and the coordination position of that insurer.

## 8. Known simplifications

* Charges are treated as allowed amounts (no network discount or tariff negotiation).
* Pre-existing waiting periods, sub-limits and room-rent caps are out of scope for this scenario.
* Claims are pre-service estimates; nothing here reconciles against an actual remittance advice.
