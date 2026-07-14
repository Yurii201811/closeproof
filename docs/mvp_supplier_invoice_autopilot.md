# MVP Supplier Invoice Autopilot

Status: implemented as a local fixture-driven MVP. No real client documents,
live Fortnox calls, emails, approvals, postings, payments, or tax filings are
performed.

## Goal

Turn a local supplier invoice fixture into a validated accounting proposal and
human approval packet:

1. Create an intake case.
2. Compute a file hash.
3. Accept OCR text plus mocked extraction JSON.
4. Normalize structured invoice fields.
5. Match the supplier against a placeholder local registry.
6. Check for possible duplicates.
7. Propose BAS account, input VAT account, and supplier payable entries.
8. Score risk and decide policy mode.
9. Generate a JSON approval packet.
10. Mirror the proposal into the optional gnubok shadow ledger stub.
11. Store queue/audit records in SQLite.

## Complete Local Demo

```bash
python3 -m accounting_agent.cli demo-supplier-invoice-autopilot
```

This runs intake normalization, extraction, duplicate/risk checks, accounting
proposal, policy decision, execution permit where allowed, approval packets,
Fortnox dry-run payloads, gnubok shadow output, and the local audit log. See
`docs/local_demo_supplier_invoice_autopilot.md`.

## Lower-Level Pipeline Command

```bash
python3 -m accounting_agent.cli process-fixtures
```

Defaults:

- fixtures: `fixtures/supplier_invoices`
- approval packets: `.local/approval_packets`
- SQLite queue: `.local/accounting_agent.sqlite`

The command processes five synthetic Swedish supplier invoice scenarios:

- normal Swedish 25 percent VAT invoice
- possible duplicate invoice
- unknown supplier
- changed bank details
- uncertain VAT/extraction

## Packet Contents

Each packet is JSON and includes:

- document summary
- file hash and intake case metadata
- extracted invoice fields
- supplier match result
- duplicate check result
- BAS/VAT proposal
- proposed accounting entries
- confidence and risk flags
- policy mode and blocked actions
- required human decision
- exact proposed external action
- dry-run Fortnox draft payload
- gnubok/shadow-ledger comparison output
- audit events

## Policy Modes

`draft_only` means the MVP may store local records and prepare a dry-run
payload. It still does not call Fortnox.

`approval_required` means a human must review the packet before any future
external draft action. The MVP still stores the packet locally.

Always blocked in MVP:

- post to Fortnox
- approve supplier invoices
- start or approve payments
- send supplier or client email
- file tax or VAT returns
- update supplier bank details without review

## Accounting Proposal

The proposal uses Swedish BAS-style draft entries:

- expense debit to a supplier/category account, for example `6110` or `6540`
- input VAT debit to `2641`
- supplier payable credit to `2440`

The proposal is draft-only and must be reviewed before external use.

## Shadow Ledger

Each supplier-invoice packet now includes `shadow_ledger_comparison`. This mirrors
the accounting proposal into the local gnubok-shaped stub, validates debit/credit
balance and simple VAT mapping, and compares the shadow draft to the Fortnox
dry-run accounting rows.

The shadow ledger is advisory and fail-soft. If gnubok is unavailable, the packet
still contains the Fortnox dry-run payload and reports `shadow_unavailable`
instead of blocking the pipeline.

## Storage

SQLite tables are created automatically by `accounting_agent.db.LocalQueue`:

- `intake_cases`
- `documents`
- `extracted_fields`
- `accounting_proposals`
- `policy_decisions`
- `approval_packets`
- `audit_events`

Schema version 3 stores exact `client_id`, `entity_id`, and row-scope version on
each table. Case identity, document hashes, invoice signatures, and duplicate
lookups are scoped by both IDs. Version 1/2 rows remain unassigned and force a
non-identifying legacy review stop until an operator explicitly maps both IDs.
This keeps the pipeline output queue/database-ready without requiring a live
Fortnox or Microsoft integration.

## Verification

Run:

```bash
python -m unittest
```

Fixture CLI runs bind both identities explicitly, for example:

```bash
python -m accounting_agent.cli process-fixtures \
  --client-id fixture_client --entity-id fixture_entity
```

The test suite verifies all five fixtures, packet generation, duplicate
detection, risk flags, policy decisions, dry-run Fortnox payload safety, gnubok
shadow-ledger comparison, fail-soft shadow unavailability, and SQLite
persistence.

## Future Integration Boundary

The Fortnox payload currently has:

- `dry_run: true`
- `live_api_call: false`
- `blocked_from_live_use: true`

A future Fortnox adapter must sit behind human approval, scoped execution
permits, idempotency keys, and a separate policy gate.
