# Restricted Fortnox MCP Layer

Status: local mocked prototype. It does not connect to live Fortnox and does not expose raw Fortnox write tools.

## Current Repository State

This workspace already has a deterministic policy engine, execution permits, an append-only audit helper, Hermes approval packet helpers, and a dry Fortnox write adapter stub.

It does not currently have an MCP server, MCP client, MCP dependency, live Fortnox OAuth setup, or Fortnox API connector.

## Safest Integration Approach

Use a restricted policy proxy as the agent-facing boundary.

The safest sequence is:

1. Keep the current minimal internal restricted facade as the source of truth for tool names, tool metadata, policy checks, permits, and logging.
2. If an open-source Fortnox MCP server is useful later, place it behind this proxy as an implementation detail. Do not register its raw tools with Openclaw, Hermes, Codex, or other LLM agents.
3. Fork an open-source server only if proxying cannot safely hide raw tools. Even then, the fork must still be subordinate to this registry and permit validator.
4. Add a real MCP transport only after the mocked facade is proven. The MCP server must export only `RestrictedFortnoxMCP.available_tools()`.

Do not expose unrestricted Fortnox write actions directly to any LLM agent.

## Tool Registry

The registry lives in `accounting_agent.restricted_fortnox_mcp.RESTRICTED_FORTNOX_TOOL_REGISTRY`.

| Tool | External system | Action type | Permission mode | Required permit | Agent visible |
| --- | --- | --- | --- | --- | --- |
| `fortnox_get_supplier` | Fortnox | `read_analysis` | `read_safe` | none | yes |
| `fortnox_list_accounts` | Fortnox | `read_analysis` | `read_safe` | none | yes |
| `fortnox_prepare_supplier_invoice_draft` | Fortnox | `draft_supplier_invoice` | `draft_only` | execution permit | yes |
| `fortnox_prepare_voucher_draft` | Fortnox | `draft_voucher` | `draft_only` | execution permit | yes |
| `fortnox_update_supplier` | Fortnox | `update_supplier` | `approval_required` | execution permit with accountant review | no |
| `fortnox_update_supplier_bank_details` | Fortnox | `update_supplier_bank_details` | `escalation_required` | execution permit with senior/security review | no |
| `fortnox_approve_supplier_invoice` | Fortnox | `approve_supplier_invoice` | `forbidden` | not issuable | no |
| `fortnox_delete_supplier` | Fortnox | `delete_record` | `forbidden` | not issuable | no |
| `fortnox_start_payment` | Fortnox | `start_payment` | `forbidden` | not issuable | no |
| `fortnox_send_invoice` | Fortnox | `send_invoice` | `forbidden` | not issuable | no |
| `fortnox_file_tax_return` | Fortnox | `file_tax_return` | `forbidden` | not issuable | no |
| `fortnox_post_voucher` | Fortnox | `post_voucher` | `forbidden` | not issuable | no |

The restricted MCP layer and the generic policy engine both forbid supplier-invoice approval, payment starts, invoice sending, deletion, and final voucher posting for the current Fortnox integration phase.

## Runtime Rules

- Read-safe tools do not require execution permits, but they still require a client id and are logged.
- Draft tools always require an execution permit, even when the policy decision is `draft_only`.
- Every write-like payload requires an explicit entity id separate from the
  client id; the restricted facade rejects cross-entity permit reuse.
- Draft tools require explicit risk evidence fields in the payload: amount,
  supplier/customer known state, bank-detail change state, duplicate risk,
  VAT/OCR confidence, period lock state, new-supplier state, destructive-action
  state, communication state, and tax/payment state. Omitted evidence fails
  closed before the adapter boundary.
- If a draft payload becomes higher risk, the policy decision can become
  `approval_required` or `escalation_required`; the permit must carry the exact
  trusted approval receipt rather than caller-supplied review labels.
- Locked periods, destructive flags, final posting, invoice sending, supplier-invoice approval, payments, tax filing, and deletion fail closed.
- Unknown tools fail closed and are logged as denied.
- Tool calls log metadata and payload hashes, not secrets or raw credentials.

## Agent Flow

Openclaw, Hermes, Codex, or any future agent should use this sequence:

1. Discover tools from `RestrictedFortnoxMCP.available_tools()`, not from a raw Fortnox MCP server.
2. Use read-safe tools only for lookup and analysis.
3. For draft work, prepare the exact payload locally first.
4. Evaluate the payload with `evaluate_policy(...)`.
5. If review is required, create an approval packet and wait for the required human review outside the agent.
6. Issue an `ExecutionPermit` for the exact payload.
7. Call the restricted tool with `case_id`, explicit `entity_id` in the payload,
   and permit.
8. Store or forward the audit entry and draft result for reviewer visibility.

Agents must not self-approve, mint permits without the required reviews, call hidden registry entries, or register raw Fortnox write tools.

## Role Guidance

Openclaw should use this layer for research, anomaly review, supplier history analysis, duplicate checks, BAS/VAT review, and risk flags. It may suggest a draft payload, but it must not approve, post, pay, delete, send, or file anything.

Hermes should use this layer for reviewer summaries and missing-information drafts. It should never send client messages or use Fortnox finalization tools through MCP.

Codex should use this layer to implement and test policy behavior, mocks, local fixtures, registry metadata, and future MCP transport code. It must not add secrets to MCP config or connect this prototype to live Fortnox without an explicit live-integration task.

## MCP Config Safety

Do not put Fortnox OAuth tokens, client secrets, refresh tokens, API keys, tenant ids with credentials, or raw client document paths in MCP config.

The future MCP config should contain only a local command or endpoint for the restricted wrapper and non-secret labels. Live Fortnox credentials, when explicitly approved later, must be supplied through a secret manager or local operator-controlled environment outside tracked files.

## Verification

The focused test file is `tests/test_restricted_fortnox_mcp.py`.

It proves:

- the registry contains `read_safe`, `draft_only`, `approval_required`, `escalation_required`, and `forbidden` classifications
- agents only see read and draft tools
- read-safe tools work without permits and are logged
- draft tools fail without permits
- valid draft permits allow mocked draft creation with no live Fortnox write
- high-risk draft payloads require reviewed permits
- supplier-invoice approval, supplier deletion, and unknown raw tools fail closed and are logged
