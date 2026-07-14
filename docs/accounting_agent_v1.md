# Accounting Agent v1 contract

Status: verified synthetic preview and local control-plane foundation. It is not
a production ledger, compliant archive, tax engine, filing service, or live ERP
writer.

## Product outcome

Accounting Agent v1 removes preparation work before an accountable accounting
decision: collecting evidence, extracting structured fields, detecting obvious
exceptions, proposing entries, reconciling candidates, assembling close
evidence, and explaining why a case stopped. It does not remove professional
judgment or let a model approve its own output.

The interface serves small-firm accountants, accountants, seniors, controllers,
auditors, and agent operators from the same underlying state:

- Guided view shows status, reason, required evidence, and the next human step.
- Expert view adds policy, identity, provider, agent-stage, and raw local-artifact
  detail.
- Swedish and English presentation share identical safety and priority rules.
- Changing the guidance perspective never changes policy or permissions.

## Implemented local capabilities

- typed money with registered currency precision and evidence-bound FX dates;
- explicit client and legal-entity identity through proposals, journals, dry-run
  payloads, and every supplier-queue row;
- balanced journal validation against an explicit versioned chart subset;
- client-scoped content-addressed evidence with mutation detection, provenance,
  redaction metadata, and a concurrency-safe hash-chained event log;
- identity-, action-, role-, expiry-, and payload-bound human approvals with
  segregation of duties;
- supplier-invoice and bank-reconciliation proposals using synthetic fixtures;
- dependency-aware close readiness with evidence, current-policy, independent
  signoff, and exact bundle-hash checks;
- a resumable preparation ladder with leases, heartbeats, cancellation, stale
  worker rejection, checkpoints, and a final human-review packet;
- provider-neutral model routing with loopback Ollama invocation and declaration
  contracts for local OpenAI-compatible, OpenAI, Anthropic, Gemini, and Codex
  workspace routes;
- a guarded read contract for Fortnox and declaration-only contracts for
  NetSuite, Oracle Fusion, SAP S/4HANA, Odoo, SIE, and CSV;
- an offline, bilingual, accessible operations cockpit and a separate
  synthetic-only deploy bundle.

### Supplier queue identity and migration

`LocalQueue` schema version 3 scopes cases, documents, extracted fields,
accounting proposals, policy decisions, approval packets, and audit events by
both exact client and legal entity. Case IDs, stored document hashes, invoice
signatures, and duplicate lookups use the same pair, so two entities managed by
one accounting firm do not collide or see one another's history.

Opening a version 1 or 2 queue only adds the new columns and advances the
container schema. Existing rows keep a null entity and their older row-scope
version; matching them produces a non-identifying `legacy_unscoped_review`
stop. Client-only migration is forbidden. An operator who has independently
verified provenance may call
`LocalQueue.map_legacy_rows_to_entity(client_id=..., entity_id=...)`; conflicting
partial mappings fail without modifying the transaction.

## Non-negotiable authority boundary

Models and specialist agents are advisory. Deterministic code checks the exact
hash of their output before it can enter human review. A successful check does
not approve or execute anything.

The following remain structurally forbidden in this phase:

- final posting or journal booking;
- sending invoices or client communications;
- supplier-invoice approval;
- payment initiation or payment-file release;
- tax or statutory filing;
- deletion or ERP settings changes;
- all live ERP writes and all Microsoft Graph, email, banking, tax, or filing
  calls. The Fortnox transport contains a credential-gated GET implementation,
  but no credentials are configured, no live read is exercised by the preview,
  and it is not production-ready;
- credentials, bank secrets, or real client documents in fixtures, tests, model
  prompts, or deployed previews.

Computer use is an observation and evidence-capture fallback only. It must stop
at credentials, unexpected navigation, prompt-injection indicators, autosave,
submit, post, approve, send, pay, delete, settings, or filing surfaces.

## Sweden-first accounting position

The Sweden pack records effective-dated jurisdiction, currency, locale, chart,
e-invoice, and retention metadata. The fixture runtime proposes a deliberately
narrow BAS subset and sends uncertain VAT, unknown suppliers, changed bank
details, possible duplicates, and locked periods to review.

This architecture follows the official requirements that business events be
recorded continuously, every accounting entry have supporting evidence, and
accounting information remain ordered and protected. Responsibility remains
with the business even when work is delegated. Current rules and guidance must
be refreshed from [Skatteverket](https://www.skatteverket.se/foretagochorganisationer/startaochdrivaforetag/bokforingochbokslut/bokforingvadkraverlagen.4.18e1b10334ebe8bc80005195.html)
and [Bokföringsnämnden](https://www.bfn.se/redovisningsregler/vagledningar/)
before a real-client pilot.

Privately supplied Bokföring 1–3 course files can inform topic-coverage checks
under `.local/course_reference/`. They are never copied into source control,
model-provider requests, generated reports, or the public preview, and never
override current official material.

## International position

International support is a foundation, not a blanket compliance claim. The
common schema handles ISO country and currency identifiers, zero- and
three-decimal currencies, functional versus transaction currency, evidence-
bound FX, locale, dimensions, source provenance, and provider capability
metadata.

A country may be called supported only after a versioned jurisdiction pack has
validated chart, tax, filing, e-invoice, retention, close, materiality, and
review rules for that country. Until then, the platform may import, normalize,
validate, and prepare evidence without claiming compliant classification or
filing.

## Agent and model execution

The fixed preparation ladder is:

1. collect evidence;
2. extract;
3. validate;
4. match;
5. request missing evidence;
6. draft;
7. explain;
8. assemble the human-review packet.

Independent inspection can run in parallel, while judgment-dependent stages
remain sequential. A specialist inherits the exact client, legal entity,
jurisdiction, evidence envelope, capability ceiling, deadline, and stop
conditions. `TrustedPreparationProcessor` is an explicit trust declaration,
not an OS sandbox; OpenClaw, Hermes, Codex, or other untrusted workers require a
separate process/container sandbox before real data is considered.

Provider manifests are routing declarations. Only the deterministic runtime and
explicitly opted-in loopback Ollama path are callable here. Hosted providers and
Codex remain disabled by default and have no runtime invoker. Official provider
contracts support structured tool or output schemas, but semantic accounting
validation stays application-owned: [OpenAI tools](https://developers.openai.com/api/docs/guides/tools),
[Anthropic tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview),
[Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling),
and [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).

## ERP interoperability

Provider names never imply authority. Every read request binds provider,
tenant, company/legal entity, environment, capability, page limit, cursor,
schema version, and mapping version. The final read gateway validates those
fields before and after the adapter call. `ConnectorBinding` requires and
serializes a normalized `local`, `sandbox`, or `production` environment inside
the same frozen tenant/company/auth scope. An environment mismatch fails before
the adapter is called; adapter or returned-page environment drift fails after
the single read. No environment selection can enable a write capability.

- Fortnox: guarded read-only preview contract plus existing mocked local
  dry-run payload preparation.
- NetSuite, Oracle Fusion, SAP S/4HANA, and Odoo: declaration only.
- SIE and CSV: local import/export declarations, not trust boundaries.
- All external write capabilities: forbidden.

Production integrations require provider sandboxes, least-privilege service
identities, observed-call telemetry, independent penetration and accounting
acceptance testing, and provider-specific reconciliation of source and imported
records.

## Operator commands

```bash
python3 -m accounting_agent.cli platform-status --json
python3 -m accounting_agent.cli v1-system-check --json
python3 -m accounting_agent.cli process-fixtures --client-id fixture_client --entity-id fixture_entity
python3 -m accounting_agent.cli fake-client-dry-run
python3 -m accounting_agent.cli build-operations-cockpit
python3 -m accounting_agent.cli build-public-preview --output .local/accounting-agent-v1-preview
python3 -m unittest
```

`build-operations-cockpit` reads local generated artifacts. `build-public-preview`
does not: it uses built-in synthetic cases, emits a manifest with hashes and
explicitly disabled network/model/write capability flags, and refuses a target
directory containing unexpected files.

## Production gates still open

Before any real-client or live-provider use, v1 still needs authenticated and
revocable workforce identities, encrypted evidence storage, independently
anchored audit logs, retention/disposal automation, backup/restore exercises,
tenant and multi-entity isolation for stores outside the supplier queue,
approved jurisdiction packs,
provider sandboxes, measured call telemetry, legal/privacy review, security
testing, and accountant/controller/auditor acceptance testing.
