Core rules
- Treat repository files as the source of truth. Read before guessing.
- Follow the closest applicable `AGENTS.md`.
- If code, docs, and tickets disagree, call out the mismatch before changing behavior.

Accounting safety
- Do not commit or process real client documents, credentials, tokens, or bank secrets.
- Do not call live Fortnox, Microsoft Graph, email, payment, tax, or filing systems from MVP code.
- Keep Fortnox behavior dry-run only unless a task explicitly adds a guarded adapter with config gates, execution permits, and idempotency.
- Final Fortnox posting, invoice sending, supplier invoice approval, payments, deletes, and settings changes are forbidden in the current adapter phase, not merely approval-gated.
- Tax filing and client communication require a human decision and are not Fortnox adapter features.
- Changed supplier bank details, possible duplicates, unknown suppliers, and uncertain VAT must be blocked for review.

Working style
- Read the smallest relevant set of files first.
- Keep changes scoped, but include adjacent safety checks when they reduce accounting risk.
- Prefer deterministic local fixtures and tests over external services.

Verification
- Run the best relevant local checks available.
- Report what passed, what could not run, and any remaining risks.
