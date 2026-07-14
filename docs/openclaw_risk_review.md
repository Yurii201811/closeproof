# Openclaw Risk Review

Status: implemented local prototype. No external actions are executed by this layer.

Openclaw is the accounting-agent review layer for research, anomaly detection, risk review, monitoring, and improvement suggestions. It produces structured, machine-readable findings before policy decisions and Hermes approval packets are finalized.

## Contract

Main interface:

```python
from accounting_agent import AccountingCase, review_accounting_case

findings = review_accounting_case(AccountingCase(...))
```

End-to-end supplier-invoice helper:

```python
from accounting_agent import review_supplier_invoice_case

result = review_supplier_invoice_case(accounting_case, audit_log=audit_log)
```

`result` contains:

- `risk_findings`
- `policy_decision`
- `approval_packet`
- optional `audit_event`

## Structured Findings

Each finding is a `RiskFinding` with:

- `signal`
- `severity`
- `message`
- `evidence`
- `policy_impact`
- `deterministic`
- optional `explanation`
- `review_version`

The current signals are:

- `duplicate_risk`
- `unusual_amount`
- `unknown_supplier`
- `changed_bank_details`
- `unclear_vat`
- `low_ocr_confidence`
- `locked_old_period`
- `missing_source_document`
- `possible_personal_private_expense`
- `missing_business_purpose`

## Deterministic First

Deterministic checks live in `accounting_agent/risk_review.py`.

The checks use only structured case fields, supplier history, invoice history, document metadata, confidence scores, period state, and explicit flags. They do not depend on LLM judgement.

Optional explanation providers may add text only after deterministic findings exist. Explanation text cannot create a finding, remove a finding, downgrade severity, or override policy.

## Policy Flow

Risk findings are passed into `PolicyContext.risk_findings`.

The policy engine applies each finding's `policy_impact.minimum_permission_mode` and required reviews. For example:

- changed bank details require escalation plus accountant, senior accountant, and security review.
- unclear VAT requires accountant and tax review.
- locked periods can make an external write forbidden.

Fortnox finalization actions remain forbidden in policy:

- post voucher
- send invoice
- approve supplier invoice
- start payment
- delete record
- change settings

Tax filing remains escalation-gated, but no filing adapter exists in this prototype.

## Hermes Approval Packets

Hermes approval packets include both legacy `risk_flags` and structured `risk_findings`.

`render_approval_packet(...)` shows a dedicated "Structured risk findings" section with signal, severity, policy impact, evidence, and optional explanation.

The fixture supplier-invoice pipeline also writes structured `risk_findings` into the JSON approval packet.

## Audit Log

`review_supplier_invoice_case(...)` writes an `openclaw_risk_review_completed` event when an audit log is supplied.

The fixture supplier-invoice pipeline also includes structured findings in the `approval_packet_generated` audit event payload.

Audit redaction still applies to sensitive keys such as bank account details, raw OCR text, tokens, credentials, email, phone, and secrets.

## Reports

`build_risk_report(...)` is the short daily/weekly report stub. It returns:

- period
- report date
- reviewed case count
- cases with findings
- findings by signal
- findings by severity
- blocked case count

The report is machine-readable through `RiskReport.to_dict()`.

## Boundaries

Openclaw must not:

- execute Fortnox writes
- approve its own findings
- send email
- post vouchers
- approve supplier invoices
- start payments
- file tax/VAT returns
- process real client data in tests

The implemented tests use synthetic fixture data only.
