# Policy and execution permits

This repository uses a deterministic policy gate before any agent can perform an external write. Agents may inspect, extract, reason, and propose actions, but Fortnox writes, email sending, supplier changes, filing, and other external mutations must pass through this layer first. Voucher posting, invoice sending, supplier-invoice approval, payments, deleting, and settings changes are forbidden.

The email adapter is a local stub. The Fortnox adapter supports mocked/dry-run reads and draft payload creation, but it still defaults to no live writes and does not allow unrestricted Fortnox mutation.

## Permission modes

The policy engine returns one of five modes:

- `auto_allowed`: low-risk reads and analysis only.
- `draft_only`: a low-risk draft action may be prepared, such as a draft supplier invoice, after a matching execution permit is issued.
- `approval_required`: an accountant review is required before an execution permit can be issued.
- `escalation_required`: higher-risk review is required, such as senior accountant, client responsible, tax, or security review.
- `forbidden`: the action must not execute.

## Policy inputs

Every proposed action is evaluated with `PolicyContext` from `accounting_agent.policy`.

Required inputs:

- `action_type`
- `client_id`
- `currency_code` as an uppercase ISO-style three-letter code

Risk inputs:

- `amount_minor`
- `supplier_known`
- `customer_known`
- `bank_details_changed`
- `duplicate_risk`
- `vat_confidence`
- `ocr_confidence`
- `period_locked`
- `new_supplier`
- `destructive_action`
- `external_communication`
- `tax_filing_payment`
- `risk_evidence_complete`

For external-write actions, `risk_evidence_complete=False` fails closed to
`approval_required`. A low-risk `draft_only` decision is only possible when the
caller explicitly supplies the known risk facts and marks the evidence complete.
External writes for `client_id="unmapped"` also fail closed to
`approval_required`.

Amounts use the minor units of the explicitly bound currency, for example ore
for SEK. The Sweden policy pack supplies these SEK defaults:

- draft without review up to `10_000_00`
- escalation from `100_000_00`

SEK client-specific thresholds can be supplied through
`PolicyConfig.client_amount_thresholds`. Other currencies must be configured
explicitly through `currency_amount_thresholds` or the more specific
`client_currency_amount_thresholds`. An external write in an unconfigured
currency fails closed to `escalation_required`; the engine never compares a
foreign-currency amount with SEK thresholds.

## Deterministic checks

The policy version is `accounting-policy-v1`. Decisions are deterministic for the same context and config.

The default rules are:

- Reads and analysis are `auto_allowed`.
- Low-risk draft supplier invoices, draft vouchers, and draft attachments are `draft_only`.
- Supplier creation, supplier updates, sending email, and filing documents require approval.
- Tax returns require escalation.
- Voucher posting, invoice sending, supplier-invoice approval, payments, deletes, settings changes, explicit destructive actions, and writes into a locked period are forbidden.
- Changed bank details require escalation.
- Unknown or new suppliers require approval.
- Amounts above the draft threshold require approval; amounts above the escalation threshold require escalation.
- VAT confidence below `0.90`, OCR confidence below `0.85`, or duplicate risk at or above `0.50` requires approval.
- External communication requires approval.
- Structured Openclaw risk findings in `PolicyContext.risk_findings` can raise the mode to approval, escalation, or forbidden according to each finding's `policy_impact`.

## Execution permits

Adapters do not accept policy decisions directly. They require an `ExecutionPermit` from `accounting_agent.permits`.

A permit contains:

- `permit_id`
- `case_id`
- `client_id`
- `allowed_action`
- `payload_hash`
- `policy_version`
- `policy_decision_hash`
- `required_reviews`
- `permission_mode`
- `expires_at`
- `idempotency_key`
- `issued_at`
- explicit `entity_id` for every permit
- `approval_receipt` for reviewed permits; it contains the immutable approval
  request id, binding digest, request digest, decision ids, and verification time

The payload hash is a canonical SHA-256 hash of the exact payload. If the payload
changes after permit issuance, the adapter rejects the write. Entity identity is
never inferred from `client_id`: issuance requires a separate nonblank
`entity_id`, and validation rejects use against a different entity.

For `approval_required` and `escalation_required` decisions, the permit issuer
does not accept review names or booleans from its caller. The caller must provide
the exact immutable `ApprovalRequest`, and the issuer reloads and verifies it
through a configured `TrustedApprovalAuthority` (the local implementation is
`SQLiteApprovalStore`). The request and resulting receipt are bound to the exact
client, entity, case, action, payload hash, full policy-decision hash, evidence
hash set, provider, and safe environment. Rejected, expired, missing, altered,
self-approved, wrong-client, or wrong-role approvals fail closed. `forbidden`
decisions never receive permits.

At execution, reviewed permits are accepted only when the exact permit object
matches the configured trusted permit store and the approval authority reloads
the receipt's request by id and re-verifies its scope, roles, decisions, and
current validity. Saving a caller-constructed permit or receipt into a
caller-writable permit database is therefore insufficient without the separately
configured approval authority.

Policy review purposes map one-to-one to stored roles: accountant to reviewer,
senior accountant to controller, client-responsible to client-responsible, tax
to tax reviewer, and security to security reviewer. Distinct required purposes
must be satisfied by distinct verified people; they are not collapsed into one
generic reviewer label.

Permits can be stored in memory for tests or in the SQLite-compatible `SQLitePermitStore`.
When an older permit database is opened, the entity and receipt columns are
added without inventing identity. Legacy rows with no entity remain invalid and
must be replaced through an explicit, audited migration; they are never mapped
to the client id automatically.

An exact approval scope may be retried only after its earlier request has
expired or received a rejection. Requests remain immutable: a retry uses a new
request id and validity window. `BEGIN IMMEDIATE` serialization allows only one
active request for a binding, including under concurrent creation attempts.

The permit issuer recomputes the current policy decision from the supplied
context before issuing a permit. A caller cannot lower the decision mode by
passing a hand-built `PolicyDecision`.

The permit validator rejects caller-supplied `approved_reviews`, missing permit
ids, missing client/entity/case ids,
missing or non-matching idempotency keys, non-external-write actions,
`auto_allowed`/`forbidden` permit modes, expired permits, changed payloads, and
reviewed modes that do not carry a trusted receipt, canonical entity id, exact
trusted permit-store record, and freshly revalidated approval-authority record. The
idempotency key must match the permit's client, entity, case, action, payload
hash, and policy version.

## Agent flow

1. Build the proposed payload, but do not write externally.
2. Build a `PolicyContext` with all known risk signals.
3. Call `evaluate_policy(context)`.
4. If the mode is `forbidden`, stop and report the reason.
5. If reviews are required, create the exact request with
   `build_permit_approval_request(...)`, persist it in the trusted approval
   store, and collect independent human decisions there.
6. Configure `PermitIssuer(permit_store, approval_authority=approval_store)` and
   issue using the same request, entity id, case, policy context, and exact
   payload.
7. Call the adapter with `action_type`, `case_id`, `payload`, and `permit`.
8. The adapter's validator uses both configured stores to validate the case,
   entity, action, payload hash, full policy hash, expiry, exact stored permit,
   and freshly revalidated human decisions before reaching its write
   implementation.

Example:

```python
from accounting_agent import (
    ActionType,
    FortnoxWriteAdapter,
    PermitIssuer,
    PolicyContext,
    evaluate_policy,
)

payload = {"supplier_id": "supplier_1", "amount_minor": 150000}
context = PolicyContext(
    action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
    client_id="client_123",
    currency_code="SEK",
    amount_minor=150000,
    supplier_known=True,
    customer_known=True,
    bank_details_changed=False,
    duplicate_risk=0.0,
    vat_confidence=0.99,
    ocr_confidence=0.98,
    period_locked=False,
    new_supplier=False,
    destructive_action=False,
    external_communication=False,
    tax_filing_payment=False,
    risk_evidence_complete=True,
)

decision = evaluate_policy(context)
permit = PermitIssuer().issue(
    decision=decision,
    context=context,
    case_id="case_123",
    entity_id="entity_se_123",
    payload=payload,
)

result = FortnoxWriteAdapter().execute(
    action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
    case_id="case_123",
    entity_id="entity_se_123",
    payload=payload,
    permit=permit,
)
```

The legacy `FortnoxWriteAdapter` returns `permit_validated_no_live_write`. The
newer `FortnoxAdapter` supports safe reference reads, local draft payload
generation, dry-run creation simulation, and idempotency checks. Its HTTP POST
and every non-dry draft path are structurally disabled; configuration and
caller-supplied approvals cannot enable them in this phase.

The local receipt is an in-process safety control, not a production credential.
It is not signed, and adapters do not yet reload permits and approvals from an
independently protected service. Live writes therefore remain forbidden. Before
any production adapter is enabled, use an isolated approval/permit service,
authenticated reviewer identities, signed or MAC-protected receipts, and
adapter-side trusted-store lookup.
