# Fortnox adapter

Status: implemented as a safe internal boundary with mocked/dry-run support. It is not a production writer.

## Safety position

Fortnox is the production bookkeeping target, but agents must not call Fortnox directly. All Fortnox access goes through `accounting_agent.adapters.fortnox.FortnoxAdapter`, which sits behind the local policy and execution-permit layer.

The adapter is read-first and local-dry-run only:

- dry-run is on by default
- reference reads are supported through the adapter transport
- voucher, invoice, and supplier-invoice reads are blocked unless sensitive reads are explicitly enabled
- supplier invoice draft payloads can be prepared locally without credentials
- voucher draft payloads can be prepared locally without credentials
- external supplier-invoice and voucher draft creation are structurally blocked
  in this phase, even if `dry_run=false`, `allow_draft_writes=true`, and a permit
  are supplied
- the raw HTTP transport is not exported from the package root and its `POST`
  method always raises before network access

Strictly blocked in the policy and adapter boundary:

- final voucher posting
- customer invoice sending
- supplier invoice approval
- payments
- deletes
- settings changes

## Configuration

Use environment variables or construct `FortnoxConfig` directly.

```text
FORTNOX_ENVIRONMENT=sandbox
FORTNOX_BASE_URL=https://api.fortnox.se/3
FORTNOX_DRY_RUN=true
FORTNOX_ALLOW_DRAFT_WRITES=false
FORTNOX_ALLOW_SENSITIVE_READS=false
FORTNOX_TIMEOUT_SECONDS=20
FORTNOX_ACCESS_TOKEN=
```

Do not commit `.env` files or real tokens. Tests inject a mock transport and do not require Fortnox credentials.

Fortnox currently documents OAuth2 bearer-token API calls with `Authorization: Bearer {Access-Token}` and JSON headers. The adapter's direct REST transport follows that shape, but the transport is replaceable so future code can use direct REST, `fortpyx`, or a restricted MCP wrapper without exposing Fortnox to agents.

## Read interface

Reference data:

- `list_accounts(params=None)`
- `get_account(account_number)`
- `list_suppliers(params=None)`
- `get_supplier(supplier_number)`
- `list_customers(params=None)`
- `get_customer(customer_number)`
- `list_financial_years(params=None)`
- `get_financial_year(year_id)`

Sensitive transactional reads, disabled by default:

- `list_vouchers(params=None)`
- `get_voucher(financial_year=..., series=..., voucher_number=...)`
- `list_invoices(params=None)`
- `get_invoice(document_number)`
- `list_supplier_invoices(params=None)`
- `get_supplier_invoice(given_number)`

If no mocked transport is supplied and no `FORTNOX_ACCESS_TOKEN` is configured, read calls fail with `MissingFortnoxCredentials`.

## Draft payloads

Supplier invoice draft payloads are prepared with:

```python
payload = adapter.prepare_supplier_invoice_draft_payload(
    supplier_number="42",
    invoice_number="INV-123",
    invoice_date="2026-05-16",
    due_date="2026-06-15",
    total="1250.00",
    vat="250.00",
    rows=[{"account": 4010, "debit": "1000.00"}],
)
```

The generated payload marks the supplier invoice as not booked, not payment pending, and disabled for payment-file handling.

Voucher draft payloads are prepared with:

```python
payload = adapter.prepare_voucher_draft_payload(
    transaction_date="2026-05-16",
    description="Supplier invoice proposal",
    voucher_series="A",
    rows=[
        {"account": 4010, "debit": "1000.00"},
        {"account": 2440, "credit": "1000.00"},
    ],
)
```

Voucher rows must balance. The current adapter can only dry-run voucher drafts.

## Draft creation flow

1. Prepare the payload locally.
2. Build a matching `PolicyContext`.
3. Call `evaluate_policy(context)`.
4. Issue an `ExecutionPermit` with the exact payload and explicit entity id.
5. Call `create_supplier_invoice_draft(...)` or `create_voucher_draft(...)`
   with that same explicit entity id.
6. The adapter validates the permit, entity, payload hash, policy version,
   expiry, and entity-bound idempotency key before any write path is reached.
7. Any non-dry configuration raises a policy violation before a network write.

Default dry-run result:

```text
dry_run_draft_not_created
```

Repeated calls with the same permit/idempotency key return:

```text
duplicate_idempotency_key
```

The `allow_draft_writes` field remains only for configuration compatibility; it
cannot enable a write. Local dry-runs still require a matching permit so payload,
case, policy, expiry, and idempotency behavior can be tested safely.

## Notes from official Fortnox docs

The implementation only relies on broad, current Fortnox API shapes:

- API requests use bearer-token authorization
- documented resources include `/3/accounts`, `/3/suppliers`, `/3/customers`, `/3/financialyears`, `/3/vouchers`, `/3/invoices`, and `/3/supplierinvoices`
- supplier invoices support list, retrieve, and create endpoints

Any future live-adapter phase requires a separate architecture/security change,
new provider/environment-bound approvals, and a fresh review of current Fortnox
semantics. It is not enabled by configuration in this version.
