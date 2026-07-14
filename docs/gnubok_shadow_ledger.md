# gnubok shadow ledger

Status: local optional validation stub. Fortnox remains the production ledger.

## Purpose

gnubok from erp-mafia is treated here as a new, actively developed open-source ERP/bookkeeping system built specifically for Sweden. In this repository, the gnubok integration is still only a shadow-ledger interface for checking supplier-invoice accounting proposals before any future Fortnox draft/write path.

The integration is meant to expose differences, BAS/VAT warnings, debit/credit balance problems, and future SIE/export compatibility issues. It must not be used as the production source of truth and must not be used for final tax or legal decisions.

## Current implementation

The current environment has no configured gnubok runtime, so `accounting_agent.adapters.gnubok` uses `LocalGnubokShadowLedgerAdapter`.

The adapter supports:

- create or get a company context
- BAS account-plan lookup using a small local account subset
- supplier-invoice draft transaction creation
- debit/credit balance validation
- VAT account/rate validation
- Fortnox dry-run payload versus shadow draft comparison
- fail-soft reporting when a shadow ledger is unavailable

The supplier-invoice fixture pipeline now attaches `shadow_ledger_comparison` to every approval packet. The high-level entry point is:

```python
from accounting_agent import (
    LocalGnubokShadowLedgerAdapter,
    mirror_supplier_invoice_proposal_to_shadow,
)

comparison = mirror_supplier_invoice_proposal_to_shadow(
    proposal,
    adapter=LocalGnubokShadowLedgerAdapter(),
)
```

The comparison output contains:

- `fortnox_payload`: the Fortnox-facing dry-run payload/accounting rows
- `accounting_proposal`: the source supplier-invoice proposal
- `shadow_proposal`: the local gnubok-shaped draft transaction
- `differences`: structural differences between Fortnox rows and shadow rows
- `warnings`: experimental, VAT, BAS, and balance warnings
- `validations`: machine-readable validation results

## Trust boundary

Useful and reasonably safe:

- catching unbalanced draft entries
- catching missing local BAS accounts from the current stub subset
- catching simple Swedish input-VAT account mismatches
- comparing the Fortnox-facing payload to the shadow draft for drift
- testing local supplier-invoice proposal plumbing without real client data

Experimental or not trusted:

- final BAS classification
- final VAT treatment
- tax/legal decisions
- annual BAS plan completeness
- reverse-charge, EU, import, mixed VAT, representation, periodization, or edge-case bookkeeping
- SIE output as a legal accounting artifact
- real gnubok import/export until a configured adapter is explicitly added and tested

## Fail-soft behavior

If gnubok or any future shadow ledger is unavailable, the main supplier-invoice proposal pipeline should still return the Fortnox dry-run payload and a `shadow_unavailable` comparison with warnings. Shadow validation is advisory; it must not block local proposal generation unless a caller explicitly chooses to enforce it.

## Client data rule

Do not connect real client data to gnubok unless explicitly configured for that client and environment. Fixture data should remain synthetic. Production Fortnox, payments, filings, client messages, and final posting decisions stay behind the existing policy and execution-permit gates.
