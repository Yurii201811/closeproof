# Post-implementation audit

Generated: 2026-05-16

Verdict: **READY_FOR_FAKE_CLIENT_DRY_RUN**

This means ready for a synthetic/local fake-client dry run only. It does not
mean ready for real client data, live Microsoft 365, live Fortnox, email
sending, payments, tax filing, supplier-invoice approval, final posting,
deletes, or settings changes.

## Scope audited

- Required docs: architecture, policy/permits, supplier invoice autopilot,
  Fortnox adapter, restricted Fortnox MCP, gnubok shadow ledger, Microsoft 365
  intake, Hermes approval inbox, Openclaw risk review, local demo, production
  readiness audit, and bank reconciliation autopilot.
- Implementation: `accounting_agent/`, `tests/`, `fixtures/`, `config/`, CLI
  commands, and generated local dry-run paths.
- Constraints honored: no live Fortnox, no live Microsoft 365, no real client
  data, no email sending, no payment/tax/filing actions.

Historical note: the workspace was not a Git repository when this May audit was
performed, so Git diff/status was not then available as an audit source. The
current v1 worktree is a Git repository and release verification does use both.

## Critical/high fixes made

1. External-write policy evidence now fails closed.
   `PolicyContext.risk_evidence_complete` defaults to `False`; external writes
   without complete risk evidence become `approval_required`. External writes
   for `client_id="unmapped"` also become `approval_required`.

2. Permit issuance now re-checks policy.
   `PermitIssuer.issue(...)` recomputes the policy decision from the supplied
   context and rejects hand-built or stale `PolicyDecision` objects that lower
   the required mode or reviews.

3. Permit validation now rejects forged/weak permits.
   `PermitValidator` rejects missing ids, missing client/case ids, empty or
   non-matching idempotency keys, non-external-write actions, `auto_allowed` or
   `forbidden` write permits, expired permits, changed payload hashes, and
   reviewed modes without required review types.

4. Reviewed permit issuance now requires the immutable approval store.
   Caller-supplied review labels are rejected. The exact approval request is
   reloaded through the trusted approval interface and bound to client, entity,
   case, action, payload, policy, evidence, provider, and environment before a
   receipt is embedded in the permit.

5. Fortnox raw HTTP POST is structurally disabled.
   `HttpFortnoxTransport.post(...)` raises before network access; configuration,
   credentials, caller labels, and execution permits cannot enable it. The raw
   HTTP transport is not exported from the package root.

5. Restricted MCP draft tools now require explicit risk evidence.
   Omitted risk fields fail closed before the adapter boundary.

6. Local demo cleanup is guarded.
   The demo writes a marker file and refuses to clear pre-existing generated
   output folders unless the output is empty, marked, or recognizable as a
   previous Accounting Agent demo output.

7. Docs were updated for current MVP-0 state.
   The architecture doc no longer claims the workspace is docs-only, and policy,
   Fortnox, restricted MCP, local demo, and production-readiness docs now note
   the new fail-closed behavior.

## Bypass audit

| Surface | Result | Evidence |
| --- | --- | --- |
| Fortnox adapter without permit | Pass | `create_supplier_invoice_draft` and legacy `FortnoxWriteAdapter` reject missing permits. |
| Fortnox adapter with changed payload | Pass | Payload hash mismatch rejects execution. |
| Fortnox live draft with any permit | Pass | Non-dry-run supplier-invoice draft creation and HTTP POST remain structurally disabled. |
| Fortnox payload attempts to book/pay/send/delete | Pass | Protected payload markers such as booked/payment/sent/deleted are blocked. |
| Direct Fortnox HTTP POST | Pass for MVP-0 | Raw HTTP POST raises before network access; no permit or configuration can enable it. |
| Restricted MCP hidden tools | Pass | Supplier approval, deletion, payment, invoice send, tax filing, and voucher posting tools are hidden/forbidden and denied even if called by name. |
| Restricted MCP omitted risk evidence | Pass | Draft tools fail closed when risk evidence fields are omitted. |
| Microsoft 365 intake | Pass for fake/local | Local file scan only; no Graph client, no send, no source move/delete. Unmapped client ids cannot proceed to low-risk external-write policy. |
| Hermes drafts | Pass for fake/local | Missing-info messages are draft-only with `send_status="draft_only_not_sent"`; no sender exists. |
| gnubok shadow ledger | Pass for fake/local | Local stub only, advisory/fail-soft, no production ledger or external write path. |
| Bank reconciliation | Pass for fake/local | Live `reconcile_bank_transaction` remains `forbidden`; payloads state no Fortnox reconciliation, posting, approval, or payment. |
| File deletion/move | Pass after fix | Source files are copied only; demo cleanup only clears marked/recognized generated output. |

## Unsafe direct-call inventory

- Fortnox write endpoints: `HttpFortnoxTransport.post` is structurally disabled
  before network access and is not exported from the package root. Its GET
  transport remains credential-gated and outside this synthetic audit.
- Email sending: no SMTP/Graph send path; `EmailWriteAdapter` returns
  `permit_validated_no_email_sent`.
- File deletion/move: no source move/delete path; only guarded demo output
  cleanup uses unlink/rmdir.
- Supplier approval / supplier invoice approval / invoice sending / voucher
  final posting / payments / tax filing: policy and restricted MCP forbid them;
  no live adapter exists for them.

## Verification

- `python3 -m unittest`: **PASS**, 85 tests.
- `python3 -m accounting_agent.cli demo-supplier-invoice-autopilot --output /private/tmp/accounting-agent-post-audit-final-demo`: **PASS**.
  Output: 5 normalized synthetic intake cases, 5 approval packets, 1 dry-run
  execution permit, 0 live Fortnox calls, 0 live Microsoft 365 calls, 0
  emails/payments/filings.
- `python3 -m accounting_agent.cli reconcile-bank-fixtures --output /private/tmp/accounting-agent-post-audit-final-bank`: **PASS**.
  Output: 7 synthetic bank transactions, 4 approval packets; live
  reconciliation remains forbidden.
- `python3 -m accounting_agent.cli scan-intake-folder --db /private/tmp/accounting-agent-post-audit-final-intake.sqlite --storage /private/tmp/accounting-agent-post-audit-final-intake-docs`: **PASS**.
  Output: 4 local fixture files, 4 extraction tasks, hash and invoice-metadata
  duplicate detection.
- `python -m unittest`: **not runnable in this shell** because `python` is not
  installed; `python3` is the working interpreter.

## Remaining blockers for anything beyond fake-client dry run

- The local approval authority now enforces reviewer identity, role,
  no-self-approval, independence, and immutable exact-scope linkage, but it is
  not an independently protected production service and receipts are not
  signed or reloaded adapter-side.
- No production-grade persistent idempotency reservation/completion store for
  live writes.
- Hash-chained events exist, but their head and storage remain local rather than
  independently anchored and production-protected.
- Client isolation, encryption, retention, deletion, legal hold, and controlled
  document access are not implemented.
- Real Microsoft Graph intake does not exist and must stay disabled.
- Current Fortnox API create semantics were not re-verified here because live
  Fortnox is out of scope.
- Raw Python imports are not a capability security boundary; any agent/runtime
  exposed to this code must only expose the restricted facade and CLI paths.
- Approval packets and local artifacts contain extracted fixture details and
  are safe only for synthetic/fake data.

## Final decision

**READY_FOR_FAKE_CLIENT_DRY_RUN**

Allowed now:

- Synthetic fake-client supplier invoice fixtures.
- Synthetic fake-client bank reconciliation fixtures.
- Local Microsoft 365-style fixture intake.
- Local approval packet review.
- Dry-run Fortnox payload inspection.
- Local gnubok shadow-ledger comparison.

Still forbidden:

- Real client documents or bank statements.
- Live Microsoft 365/Graph.
- Live Fortnox credentials or writes.
- Email sending.
- Payments, filings, final posting, supplier invoice approval, invoice sending,
  deletes, settings changes, or supplier bank-detail updates.
