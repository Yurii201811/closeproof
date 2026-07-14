# Hermes approval inbox

Hermes now uses a Markdown approval packet as the first approval inbox surface. This is intentionally simple: it gives an accountant one readable packet per case without adding a server, dashboard, email sender, or live Fortnox connection.

## What the packet shows

Each approval packet includes:

- case id
- client id
- source document reference
- extracted invoice fields
- proposed accounting entries
- confidence scores
- risk flags
- policy decision and required reviews
- exact proposed Fortnox action
- review choices: `approve`, `reject`, `escalate`, or `missing_info`

The packet is a review artifact only. Approval recorded in the packet flow does not send an email, approve a supplier invoice, post a voucher, start a payment, or make a final Fortnox write.

## Python interface

Use `ApprovalPacket` and `render_approval_packet` to build the accountant-facing packet:

```python
from accounting_agent import ApprovalPacket, render_approval_packet

markdown = render_approval_packet(packet)
```

Use `write_approval_packet(packet, folder)` to write `case_id.md` into a local approval-packet folder.

## Missing-information drafts

Hermes can draft short client-facing messages for:

- missing receipt
- unclear business purpose
- unknown supplier
- changed bank details confirmation
- VAT uncertainty

Use `draft_missing_info_email(...)` to generate the draft. The returned object always has `send_status="draft_only_not_sent"`. There is no send path in this workflow.

## Audit decisions

Use `record_approval_decision(...)` with `JsonlAuditLog` to append review decisions:

- `approve`
- `reject`
- `escalate`
- `missing_info`

The audit event stores the case, client, actor, selected decision, policy mode, required reviews, risk flags, source document reference, proposed Fortnox action, and a short note. Sensitive detail keys such as bank details, raw OCR text, emails, tokens, and secrets are redacted before writing the JSONL event.

## Sample supplier invoice flow

1. Extract invoice fields from the source document.
2. Build proposed accounting entries and confidence scores.
3. Evaluate the proposed Fortnox draft action with the policy gate.
4. Render the approval packet.
5. Accountant selects `approve`, `reject`, `escalate`, or `missing_info`.
6. Record the decision in the audit log.
7. If information is missing, draft an email with `draft_missing_info_email(...)`.

No email is sent and no final Fortnox write is approved automatically.
