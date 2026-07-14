# Production Readiness and Safety Audit

Generated: 2026-05-16

Superseded note: `docs/post_implementation_audit.md` is the newer MVP-0
post-implementation audit. This document remains useful as the production
readiness baseline, but some findings listed here were partially fixed during
the post-implementation audit: external-write policy evidence now fails closed
when omitted, the permit issuer re-checks policy decisions, the permit
validator enforces idempotency binding, the raw HTTP Fortnox transport is no
longer exported from the package root and always rejects POST before network access,
restricted MCP draft tools require explicit risk evidence, and demo output
cleanup now refuses unmarked existing folders. A later v1 hardening pass also
added immutable reviewer identities/decisions and an exact approval-to-permit
receipt bridge for local, test, preview, and dry-run environments. The
production recommendation below remains NO-GO.

Scope: repository code, configs, tests, docs, synthetic fixtures, local CLI demos, Fortnox adapter boundary, Microsoft 365 intake prototype, gnubok shadow ledger, Hermes approval helpers, restricted Fortnox MCP facade, and the current bank-reconciliation prototype.

## Recommendation

**NO-GO for connecting real Microsoft 365, Fortnox production/sandbox write access, or real client data.**

The system is suitable for **synthetic local fixtures and dry-run-only development**. It is not yet suitable for production accounting, real mailbox/file intake, Fortnox credentials, real supplier invoices, real bank statements, or any client data.

The most important reason is not one missing feature. The safety model remains
an in-process prototype: reviewed permit issuance now uses a local immutable
approval-store trust anchor, but permit receipts are not signed, adapters do not
reload them from an independently protected service, idempotency is process-local
by default, local storage is plaintext, and production client
isolation/retention are not implemented.

## What Changed During This Audit

Small urgent fail-closed fixes were implemented:

- Added `.gitignore` coverage for local databases, JSONL logs, `.env` files, token/credential folders, runtime artifacts, and client/private accounting material (`.gitignore:1`).
- Added a repository safety test that asserts those ignore patterns remain present (`tests/test_repository_safety.py:10`).
- Hardened `FortnoxAdapter` so every non-dry-run supplier-invoice draft and raw
  HTTP POST is structurally disabled before network access; configuration and
  permits cannot enable either path.
- Added/updated Fortnox tests proving both live draft surfaces remain disabled
  with credentials, configuration, and otherwise valid permits.
- Added a policy test proving live bank reconciliation remains forbidden (`tests/test_policy_and_permits.py:130`).

Verification after fixes:

- `python -m unittest` could not run because `python` is not installed in this shell.
- `python3 -m unittest` passed: 78 tests.
- Local supplier invoice fixture smoke passed with 5 synthetic approval packets, 0 live Fortnox calls.
- Local Microsoft 365 intake fixture smoke passed with 4 synthetic/local files, duplicate detection, 0 live Microsoft calls.
- Local Supplier Invoice Autopilot demo passed, wrote temporary artifacts under `/private/tmp/accounting-agent-audit/demo`, and reported 0 live Fortnox calls, 0 live Microsoft 365 calls, 0 emails/payments/filings.
- Local bank reconciliation fixture smoke passed with 7 synthetic bank transactions and 4 review packets; live reconciliation remains forbidden.

## Go/No-Go Matrix

| Area | Current evidence | Classification | Decision |
| --- | --- | --- | --- |
| Synthetic supplier-invoice fixtures | Local fixture pipeline, tests, dry-run payloads, approval packets | Safe now for local synthetic data | Go for fixtures only |
| Local Microsoft 365 intake prototype | Local folder scan only, no Graph client, duplicate detection | Safe only in dry-run/local sample mode | No real mailbox or OneDrive |
| Fortnox reference reads | Adapter exists, credentials required for real transport, sensitive reads disabled by default | Requires fix before real use | No real credentials yet |
| Fortnox supplier-invoice draft write | Local dry-run only; non-dry-run draft and raw HTTP POST raise before network access | Safe only in dry-run | No live Fortnox write |
| Fortnox voucher/posting/finalization | Policy and adapter forbid posting/payment/sending/final actions | Forbidden | Keep forbidden |
| Email send | `EmailWriteAdapter` validates permits but never sends; Hermes only drafts | Safe only as draft text | No send path |
| Microsoft Graph tokens/data | No real adapter or token store implemented | Requires fix | No real Graph connection |
| gnubok shadow ledger | Local stub, advisory/fail-soft, Fortnox remains source of truth | Safe only with synthetic/local dry-run data | No real client data |
| Bank reconciliation | Prototype code exists; live reconciliation is forbidden by policy | Requires fix | No Fortnox reconciliation |
| Client separation | Supplier queue is explicit client + entity scope; other local stores still lack a complete production tenant boundary | Requires fix | No real-client use |
| Audit trail | Hash-chained local events and immutable approval records exist; no independent anchoring, signing, or protected service | Requires fix | Not production-grade |
| Data retention/deletion | No retention, deletion, legal hold, export, or purge workflow | Requires fix | No real data |
| Test coverage | Dual-runtime unit/integration suites cover current local controls and bypass cases; no provider sandbox or production acceptance evidence | Requires fix | Not enough for production |

## Critical Blockers

### P0-1: Production policy evidence still needs an independently trusted source

External-write callers must now set `risk_evidence_complete=True`; omission fails
closed to review. A malicious in-process caller can still falsely assert that
the evidence is complete, so production must derive this signal from persisted,
independently protected case facts rather than trust caller input.

Production fix:

- Replace optional safe defaults with an explicit evidence object.
- Unknown supplier, unknown duplicate state, unknown VAT confidence, unknown bank-detail state, unknown client mapping, or missing source document must fail to `approval_required` or `escalation_required`.
- Add tests where each missing risk signal fails closed.

### P0-2: Local approval-to-permit binding added; production trust boundary remains

Current v1 code rejects caller-supplied `approved_reviews`. Reviewed permits
require an exact immutable `ApprovalRequest` reloaded through a configured
`TrustedApprovalAuthority`; the receipt is bound to client, entity, case,
action, payload, policy decision, evidence hashes, provider, environment, and
the recorded decision ids. `SQLiteApprovalStore` enforces verified active
reviewer identities, client scope, required roles, no self-approval, independent
reviewers, immutability, rejection, and expiry.

Remaining production work:

- Require every future production adapter instance to use the trusted-store and
  approval-authority validator configuration; the local default can validate
  low-risk synthetic permits without those external trust services.
- Move approval and permit records behind an independently protected service and
  authenticated operator boundary.
- Sign or MAC-protect permit receipts before they cross process boundaries.

### P0-3: Raw adapter and transport classes are importable bypass surfaces

The restricted MCP facade fails unknown and hidden tools closed. After the
post-implementation audit, `HttpFortnoxTransport` is no longer exported from the
package root and its `POST` method raises before network access, but raw Python
module imports are still not a production capability boundary. A production
agent runtime must not expose raw adapter or transport classes/tools to LLM
agents.

Production fix:

- Agent-facing tooling must expose only the restricted facade.
- Do not register raw Fortnox MCP tools or raw adapter methods.
- Add integration tests that enumerate available tools and prove no raw write/transport path is reachable.

### P0-4: Idempotency is not durable by default

The default adapter idempotency store is in-memory, so the local dry-run
duplicate simulation disappears on process restart. There is no live write in
this phase; any future production writer would need a persistent, atomic
reservation before an external call and durable completion after the response.

Production fix:

- Implement a SQLite-backed idempotency store with unique constraints for adapter/action/client/case/payload hash.
- Reserve the idempotency key transactionally before the outbound write.
- Persist request hash, response reference, status, and retry state.
- Add crash/retry tests.

### P0-5: Hash-chained events remain locally anchored

The v1 evidence layer adds a concurrency-safe hash-chained event log, tail
deletion detection against a separate local head, and redaction metadata.
Because both chain and head remain local, an operator with filesystem authority
can still replace them together. There is no signature, independent anchor,
actor authentication service, immutable storage mode, or deletion prevention.

Production fix:

- Anchor or sign event heads outside the application storage boundary.
- Record authenticated actor identity, role, source system, before/after policy
  mode, adapter result, and approval/permit ids across every workflow.
- Use a central redaction layer before any JSON/SQLite/Markdown output.
- Add protected-storage replacement and restore tests.

### P0-6: Sensitive data is stored in plaintext local artifacts

The intake store persists original paths, stored paths, filenames, source metadata, invoice metadata, and hashes (`accounting_agent/intake/store.py:103`, `accounting_agent/intake/store.py:249`). The local intake processor copies files into a hash/original-filename path (`accounting_agent/intake/local.py:261`). Approval packets include full extracted fields and document summaries (`accounting_agent/supplier_invoice/pipeline.py:208`). This is acceptable for synthetic fixtures, not client data.

Production fix:

- Per-client encrypted storage roots.
- No raw OCR/full document text in packets or audit logs by default.
- Redacted reviewer packets with references to controlled document storage.
- Data classification, retention periods, deletion/purge, export, and legal hold behavior.

### P0-7: Supplier-queue identity is explicit; remaining stores need production isolation

The supplier queue now binds every row, duplicate signature, and case id to an
explicit client and legal entity, and legacy rows remain unassigned until an
audited mapping. General intake/evidence storage, credentials, retention, and
operator authorization are not yet a complete production tenant boundary.

Production fix:

- Per-client config, storage, database namespace, Fortnox tenant/company binding, and M365 source allowlist.
- Hard fail for unmapped sources before extraction or proposal work on real data.
- Cross-client duplicate and metadata leak tests.

### P0-8: Fortnox live writes remain absent by design

Non-dry-run supplier-invoice draft creation and `HttpFortnoxTransport.post`
raise before network access. The GET transport is credential-gated and sensitive
reads are disabled by default, but it has not passed a real provider sandbox,
telemetry, privacy, or accounting acceptance exercise.

Production fix:

- Keep all Fortnox behavior dry-run until a separate live-integration task.
- Treat any future sandbox write adapter as a separate implementation requiring
  explicit environment gates, persistent permit/idempotency stores, and a test
  token outside the repository.
- Production write enablement should remain separate from sandbox enablement.
- Final posting, supplier invoice approval, payment, deletion, invoice sending, and settings changes remain forbidden.

### P0-9: Microsoft 365 real intake does not exist safely yet

The M365 slice is local/mock only. This is good. There is no Graph token storage, no tenant/client allowlist enforcement, no mailbox/folder allowlist, no dry-run listing stage, no download staging boundary, and no keychain/secret manager integration.

Production fix:

- Add Graph adapter only behind `M365_GRAPH_ENABLED=true`.
- Use least-privilege read scopes only; no `Mail.Send`.
- Store secrets in OS keychain or a real secret manager, not SQLite or files.
- Implement dry-run source listing before download.
- Hard fail for unmapped client/source rules.

### P0-10: Duplicate, VAT, bank-detail, and unauthorized-write protections are split across helpers

The supplier pipeline detects duplicate invoices (`accounting_agent/supplier_invoice/pipeline.py:155`), changed bank details (`accounting_agent/supplier_invoice/rules.py`), and VAT uncertainty, but the adapter only sees a payload and permit. A caller that bypasses the pipeline can omit risk facts from `PolicyContext`.

Production fix:

- Make adapters require a persisted case/proposal id and load the canonical risk decision from the database.
- The permit should bind source document ids, duplicate status, VAT status, supplier match status, and bank-detail status.
- Add tests proving duplicates, uncertain VAT, changed bank details, unknown suppliers, and locked periods cannot reach a live adapter even if a caller hand-builds a payload.

## Bypass Paths To Close

- In-process caller falsely asserts `risk_evidence_complete=True`; production
  must derive it from protected persisted facts.
- Agent supplies fake review labels (now blocked by `PermitIssuer` and
  `PermitValidator`; keep as a regression test).
- Agent constructs an `ExecutionPermit` dataclass directly.
- Agent imports raw `HttpFortnoxTransport` or `FortnoxAdapter` instead of using `RestrictedFortnoxMCP`.
- Agent calls a future raw Fortnox MCP server if it is ever registered beside the restricted facade.
- Agent uses a new source path/client mapping rule to put real documents under `unmapped` or the wrong client.
- Agent relies on gnubok shadow output as if it were a blocking safety control even though it is explicitly fail-soft.
- Agent writes or shares `.local` artifacts containing extracted fields, paths, bank details, or raw source text.

## Microsoft 365 Safety

Current state: no live Graph connection. This is the correct state for now.

No-go reasons:

- No token storage design.
- No tenant/mailbox/drive/folder allowlist.
- No dry-run source listing.
- No secret manager or keychain integration.
- No retention/deletion handling for downloaded attachments.
- No client isolation.

## Fortnox Safety

Current state: local dry-run payloads only for writes. Non-dry-run draft creation
and raw HTTP POST are structurally disabled. Credential-gated GET code exists
but is not configured, exercised, or production-approved in this preview.

No-go reasons:

- Raw adapter/transport import surface remains.
- The local trusted approval authority is not a production-isolated service,
  and receipts are not signed or reloaded adapter-side.
- Persistent idempotency is missing.
- Current Fortnox create semantics are not verified in this audit.
- Error and response handling can still carry client data.
- Production/sandbox separation is not strong enough.

## Email Safety

Current state: safe for draft text only. `draft_missing_info_email(...)` returns `send_status="draft_only_not_sent"` and `EmailWriteAdapter` does not send.

No-go reasons:

- No send adapter should be added until approval identity, recipient allowlists, message redaction, and audit are production-grade.

## gnubok Shadow-Ledger Safety

Current state: useful as local advisory validation. It is not a source of truth.

No-go reasons:

- Shadow validation is fail-soft by design.
- BAS/VAT coverage is deliberately incomplete.
- No real gnubok runtime, client isolation, import/export safety, or legal-accounting guarantees.

## Prioritized Fix List

1. Keep live Microsoft 365, Fortnox writes, email sending, client documents, payments, filings, deletes, settings changes, and supplier bank updates disabled.
2. Implement fail-closed policy evidence: missing/unknown duplicate, VAT, OCR, supplier, bank-detail, client mapping, source document, or period state must not default to safe.
3. Promote the local trusted approval and permit stores into an independently
   protected service with authenticated actors, immutable event linkage,
   signed receipts, and adapter-side permit lookup.
4. Add persistent idempotency and adapter event storage before any live Fortnox sandbox attempt.
5. Lock down agent-facing tool exposure to the restricted facade only; add tool-inventory tests.
6. Add encrypted per-client storage/database boundaries and hard fail for `unmapped` real sources.
7. Centralize redaction and stop storing raw extracted fields/full source text in audit and reviewer artifacts.
8. Add tamper-evident audit logs with hash chaining and actor identity.
9. Add Microsoft Graph only as a separate read-only, explicitly enabled adapter with keychain/secret-manager token handling.
10. Re-check current Fortnox API semantics before any sandbox write; prove supplier-invoice draft creation cannot book, approve, send, pay, or alter supplier settings.
11. Add bypass tests for direct permit construction, omitted risk facts, duplicate invoices, changed bank details, uncertain VAT, unknown suppliers, and locked periods.
12. Keep bank reconciliation fixture-only; before any real bank feed or Fortnox reconciliation adapter, add persistent idempotency, trusted approvals, client isolation, and adapter/gateway tests.
13. Keep architecture docs current as the implementation changes. The
    post-implementation audit refreshed the old docs-only wording, but future
    implementation slices should update the architecture and safety docs in the
    same change.

## Final Decision

**NO-GO for real Microsoft 365, Fortnox, or client data.**

Allowed now:

- Synthetic fixtures.
- Local dry-run demos.
- Local approval-packet experiments.
- Mock/restricted Fortnox facade tests.
- gnubok local shadow comparisons on synthetic data.

Forbidden now:

- Real Microsoft 365 tenant/mailbox/OneDrive/Teams data.
- Real Fortnox credentials or live Fortnox writes.
- Real client supplier invoices, receipts, bank statements, or bookkeeping data.
- Email sending.
- Payments, filings, final posting, supplier invoice approval, deletes, settings changes, or supplier bank-detail updates.
