# feature/letter-polish

## What this adds

Layout polish on the pre-authorisation letter after reviewing a rendered copy:

- the insurer and plan now sit under the title instead of wrapping inside the title line;
- the reference block no longer prints the internal plan id (`PLAN_B`), which is meaningless to an insurer's desk.

## Evidence

Rendered `outputs/preauth_letters/CLM-2026-A-ACL_PLAN_B.pdf` and checked the header, the code table and the declaration block at 100 dpi.
