# Fake client dry-run report

Generated: 2026-07-10T20:09:34+00:00

Readiness: `local_fake_client_dry_run_complete`.

Live-system readiness: `not_ready_for_live_connection`. This run proves only the local fake-data path; Fortnox, Microsoft 365, email, payment, tax filing, and final posting remain intentionally blocked.

## Documented command

```bash
python3 -m accounting_agent.cli fake-client-dry-run
```

Default output folder:

```text
.local/fake_client_dry_run
```

## Safety result

- Fake data only: `True`
- Real client data used: `False`
- Live Fortnox calls: `0`
- Live Microsoft 365 calls: `0`
- Emails sent: `0`
- Payments or filings: `0`
- Final voucher postings: `0`

## Fake client profile

- Client: `fake-se-service-001` / `Fiktiv Konsultstudio AB`
- Business: small Swedish consulting/service business
- Currency: SEK
- VAT: Swedish VAT, with 25%, 0%, and one intentionally uncertain VAT case
- Known suppliers: 8 synthetic suppliers
- Known customers: 5 synthetic customers

## Sample data coverage

- Supplier invoices/receipts: `15`
- Customer invoices: `5`
- Bank transactions: `20`
- Ambiguous/edge cases: `3`
- Duplicate-risk cases: `2`
- Changed bank-details cases: `1`
- Uncertain VAT cases: `1`
- Old/locked-period cases: `1`

## Policy decisions

| Mode | Primary cases | Observed decisions |
| --- | ---: | ---: |
| `auto_allowed` | 0 | 20 |
| `draft_only` | 21 | 21 |
| `approval_required` | 11 | 11 |
| `escalation_required` | 2 | 2 |
| `forbidden` | 1 | 21 |

Primary cases count supplier invoice execution-gate decisions plus bank reconciliation proposal decisions. Observed decisions also include bank read-analysis decisions and intentionally forbidden live-reconciliation decisions.

## Execution and adapter results

- Supplier execution permits: `{'issued': 8, 'not_issued_review_required': 6, 'not_issued_forbidden': 1}`
- Fortnox dry-run payload statuses: `{'prepared': 8, 'prepared_but_review_blocked': 7}`
- Supplier approval packets: `15`
- Bank reconciliation proposals: `20`
- Top-level audit events: `36`

## Accuracy review

- False positives: `0`
- Unsafe misses: `0`
- Unclear outputs: `0`
- Policy alignment warnings: `0`

## Errors

- No local pipeline completion errors were recorded.
- No live external system was contacted.

## Next blockers

- Live Fortnox remains blocked until a guarded adapter phase explicitly adds config gates, execution permits, idempotency, and reviewed sandbox behavior.
- Microsoft 365 intake remains local/mock-only in this dry run.
- Customer invoice creation, supplier invoice approval, payments, tax filing, and final voucher posting remain outside this MVP dry run.
- Human accounting review is still required for review, escalation, and forbidden cases before any future live workflow.

## Output index

- Manifest: `.local/fake_client_dry_run/manifest.json`
- Summary: `.local/fake_client_dry_run/summary.json`
- Synthetic sample data: `.local/fake_client_dry_run/sample_data`
- Supplier pipeline output: `.local/fake_client_dry_run/supplier_invoice_autopilot`
- Bank proposals: `.local/fake_client_dry_run/bank_reconciliation_proposals.json`
- Audit log: `.local/fake_client_dry_run/audit_log.jsonl`
