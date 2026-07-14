# Local demo: Supplier Invoice Autopilot

Status: implemented as a local, fixture-only end-to-end demo.

This demo shows the future autonomous accounting workflow without touching real
client documents, live Microsoft 365, live Fortnox, email, payments, filings, or
final bookkeeping.

## One command

From the repository root:

```bash
python3 -m accounting_agent.cli demo-supplier-invoice-autopilot
```

Default output folder:

```text
.local/demo_supplier_invoice_autopilot
```

The command uses only synthetic fixtures from:

```text
fixtures/supplier_invoices
```

## What it does

The demo runs this local workflow:

```text
intake -> extraction -> duplicate/risk checks -> accounting proposal -> policy decision
-> execution permit if applicable -> approval packet -> Fortnox dry-run payload
-> gnubok shadow output -> audit log
```

The low-risk fixture receives a scoped local execution permit and is passed
through the Fortnox adapter in dry-run mode. Review-required fixtures do not get
permits. Missing required Fortnox fields produce an actionable error artifact
instead of fabricating data.

## Output layout

The output folder is recreated for known demo artifacts on each run:

```text
.local/demo_supplier_invoice_autopilot/
  summary.json
  manifest.json
  demo.sqlite
  normalized_intake_cases.json
  audit_log.jsonl
  intake_source_exports/
  extracted_invoice_json/
  accounting_proposals/
  risk_findings/
  policy_decisions/
  execution_permits/
  approval_packets/
    json/
    markdown/
  fortnox_dry_run_payloads/
  gnubok_shadow_outputs/
```

The demo writes a local marker file into its output folder and refuses to clear
pre-existing generated subfolders unless the folder is empty, already marked, or
recognizable as a previous Accounting Agent demo output. This prevents a custom
`--output` path from accidentally deleting unrelated files.

Key files:

- `normalized_intake_cases.json`: local normalized intake cases generated from synthetic invoice exports.
- `extracted_invoice_json/*.json`: extracted supplier invoice fields.
- `accounting_proposals/*.json`: BAS/VAT draft proposal and accounting rows.
- `risk_findings/*.json`: duplicate, supplier, VAT, and structured risk findings.
- `policy_decisions/*.json`: pipeline decision plus execution-gate decision.
- `execution_permits/*.json`: issued dry-run permit or review-required blocker.
- `approval_packets/json/*.json`: machine-readable approval packets.
- `approval_packets/markdown/*.md`: Hermes reviewer packets.
- `fortnox_dry_run_payloads/*.json`: dry-run Fortnox adapter payload/result, never a live call.
- `gnubok_shadow_outputs/*.json`: local gnubok-shaped shadow validation output.
- `audit_log.jsonl`: one append-only-style local demo audit event per case.

## Safety guarantees

The demo does not:

- call Fortnox
- call Microsoft Graph or Microsoft 365
- send email
- approve supplier invoices
- start or approve payments
- post bookkeeping
- file tax or VAT returns
- require paid services or credentials

The Fortnox payloads are dry-run artifacts with `live_api_call=false`. The
adapter dry-run result for the low-risk fixture is `dry_run_draft_not_created`.

## Custom paths

Use another output folder:

```bash
python3 -m accounting_agent.cli demo-supplier-invoice-autopilot --output /tmp/accounting-demo
```

Use another synthetic fixture folder:

```bash
python3 -m accounting_agent.cli demo-supplier-invoice-autopilot --fixtures fixtures/supplier_invoices
```

If the fixture folder is missing, empty, invalid JSON, or missing
`mock_extraction`, the command exits with a plain actionable error.

## Verification

Run the smoke test:

```bash
python3 -m unittest tests.test_local_demo_supplier_invoice_autopilot
```

Run the full local suite:

```bash
python3 -m unittest
```
