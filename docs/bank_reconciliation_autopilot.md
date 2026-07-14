# Bank Reconciliation Autopilot

Status: MVP 2 local prototype. This is fixture-only and does not connect to live bank feeds, Fortnox reconciliation APIs, payment systems, Microsoft Graph, email, or real client data.

## Purpose

The Bank Reconciliation Autopilot matches sample bank transactions against open accounting items and produces explainable, policy-gated reconciliation proposals.

Supported target types:

- customer invoices
- supplier invoices
- receipts
- vouchers

The output is a local proposal packet. It is not a Fortnox reconciliation, not a voucher posting, not a supplier-invoice approval, and not a payment instruction.

## Bank Transaction Schema

Fixture transactions live in `fixtures/bank_reconciliation/bank_transactions.json`.

Each bank transaction contains:

- `transaction_id`: stable bank/source identifier
- `date`: ISO transaction date
- `amount_minor`: signed amount in minor units, for example ore for SEK
- `currency`: ISO-style currency code
- `counterparty`: payer/payee text from the bank feed export
- `reference`: OCR, invoice number, or payment message
- `bank_account`: the company bank account that received or sent the payment
- `source`: fixture/source label

Open match targets live in `fixtures/bank_reconciliation/open_items.json` and use `target_type` to distinguish customer invoice, supplier invoice, receipt, and voucher candidates.

## Fixture Scenarios

The current fixture set covers:

- exact customer invoice payment
- exact supplier invoice payment
- partial customer payment
- duplicate-looking customer payment transactions
- bank fee matched to a voucher template
- unknown large outgoing transaction

The duplicate-looking scenario intentionally uses two sample bank rows with the same amount, reference, currency, and counterparty so duplicate risk can be detected deterministically.

## Matching

Implementation:

- `accounting_agent/bank_reconciliation/models.py`
- `accounting_agent/bank_reconciliation/matching.py`
- `accounting_agent/bank_reconciliation/pipeline.py`

Candidate scoring is explainable and deterministic. It scores:

- amount match, including exact, close, and partial payment cases
- date distance from target date or due date
- OCR/reference match
- customer or supplier counterparty match
- payment direction
- currency match

Every candidate includes:

- confidence score
- score breakdown
- amount delta
- date delta
- explanations
- policy-relevant flags

Low-confidence, partial, duplicate-looking, unknown, changed-bank-detail, or unusual cases are routed to review.

## Policy Gates

The central policy engine now knows two bank reconciliation actions:

- `draft_bank_reconciliation`: local proposal generation, default `draft_only`
- `reconcile_bank_transaction`: actual reconciliation, default `forbidden`

Each proposal records three policy decisions:

- `matching_policy_decision`: local read/analysis decision, normally `auto_allowed`
- `policy_decision`: the local reconciliation proposal decision, for example `draft_only`, `approval_required`, or `escalation_required`
- `live_reconciliation_policy_decision`: actual Fortnox reconciliation decision, currently `forbidden`

This keeps exact low-risk matches easy to inspect while preserving the current adapter-phase rule: no automatic Fortnox reconciliation and no final posting.

## Approval Packets

Approval packets are generated only for cases that need review:

- partial payment
- duplicate-looking transaction
- unmatched/unknown transaction
- escalated or forbidden local proposal decision

Packets include the transaction, selected candidate, alternatives, explanations, risk flags, policy decision, blocked actions, and a dry-run reconciliation payload.

The payload always contains:

- `dry_run: true`
- `live_api_call: false`
- `reconciles_in_fortnox: false`
- `posts_bookkeeping: false`
- `starts_payment: false`

## Local CLI

Run the fixture prototype:

```bash
python3 -m accounting_agent.cli reconcile-bank-fixtures
```

Optional paths:

```bash
python3 -m accounting_agent.cli reconcile-bank-fixtures \
  --fixtures fixtures/bank_reconciliation \
  --output .local/bank_reconciliation_packets
```

The command prints one line per bank transaction with selected target, policy mode, confidence, and approval packet path when a packet is required.

## Safety Notes

The prototype deliberately does not:

- connect live bank feeds
- read or write real bank data
- auto-reconcile in Fortnox
- post vouchers
- approve supplier invoices
- initiate payments
- send invoices or emails
- update supplier bank details

Any future live adapter must preserve these boundaries with explicit configuration gates, execution permits, idempotency, audit logging, and human approval for non-low-risk cases.
