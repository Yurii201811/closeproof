# BalanceDocket

BalanceDocket is a source-linked month-end close reviewer for controllers and senior
accountants. It turns a synthetic general ledger and text-based invoice PDFs into
deterministic control results, an optional bounded GPT-5.6 advisory, an explicit
human decision, and a validated workpaper. The complete local review path works
without a model, network access, an OpenAI account, or an API key.

## Build Week decision

- Track: **Work & Productivity**.
- Product form: **Codex plugin/skill plus a localhost reviewer workbench**.
- Primary persona: controller or senior accountant reviewing the June close.
- Core promise: every conclusion is traceable through source evidence,
  deterministic calculation, any optional model advisory, and human
  disposition.
- Deadline: July 21, 2026 at 17:00 PT (July 22 at 02:00 Europe/Stockholm).

Official sources:

- [OpenAI Build Week announcement](https://x.com/openaidevs/status/2076715478878474575)
- [Competition rules](https://openai.devpost.com/rules)
- [Competition FAQ](https://openai.devpost.com/details/faqs)

The submission must show a working product built meaningfully with Codex and
GPT-5.6, select one track, include a public repository and reproducible README,
provide an audio demo under three minutes, explain Codex acceleration and key
decisions, and include the primary Codex `/feedback` session ID. The competition
recording must show a real Codex run requesting `gpt-5.6-sol` whose structured
output passes BalanceDocket validation; the deterministic preview is not evidence
of a model call. Codex CLI `0.144.0` did not report the returned model identity
in the retained run, and BalanceDocket does not claim otherwise.

## Job to be done

When I review a month-end close, help me resolve exceptions without losing the
link between the source document, the exact control calculation, the policy
interpretation, and the accountable human decision.

## Golden demo

1. Run `$closeproof` on the bundled Nordix Services AB June 2026 fixture.
2. Ingest one synthetic GL CSV and a generated, text-based invoice PDF.
3. Run duplicate, cutoff, and prepaid controls deterministically.
4. Show stages 1-3 verified, Adjustments requiring review, and stages 5-9
   waiting on Adjustments.
5. Open the prepaid proof sheet and highlight the cited service period.
6. Show the exact day-based allocation stamped `Calculated by controls`.
7. Use the existing Codex sign-in to ask GPT-5.6 for a structured,
   citation-bound advisory. The model may explain and draft; it cannot approve,
   post, lock, or change calculations.
8. Require a human rationale and approve, request evidence, or reject.
9. Export the evidence-bound workpaper and verify the decision event chain.

## Scope

### Required

- Synthetic data only.
- CSV ingestion with schema and period validation.
- Deterministically generated and parsed text PDF fixture.
- Exact duplicate, cutoff, and prepaid controls.
- Existing nine-stage close dependency engine.
- Source IDs, citations, SHA-256 evidence hashes, and snapshot digest.
- Structured GPT-5.6 advisory with citations and explicit uncertainty.
- Fail-closed advisory validation and a complete local no-advisory path.
- Human review actions with a rationale and append-only hash-chained audit event.
- Responsive evidence-ledger workbench and JSON workpaper export.
- One-command demo generation and loopback-only serving.

### Explicit non-goals

- Real client documents or identifiers.
- Live Fortnox, Microsoft Graph, email, bank, tax, payment, or filing calls.
- ERP writes, final posting, close locking, supplier approval, or communication.
- OCR, arbitrary third-party PDFs, authentication, billing, or multi-tenant SaaS.
- Autonomous accounting conclusions or compliance claims.
- A chatbot-first interface, KPI dashboard, or generic AI-accountant positioning.

## Subscription-first advisory architecture

The advisory layer is optional. Local evidence, calculations, dependency status,
human review, event-chain verification, and export do not depend on it.

| Route | Purpose | Credential and cost boundary | Competition role |
|---|---|---|---|
| Local only | Deterministic review with advisory not requested | None; no model, network, or API | Reproducible baseline |
| Codex | Run the prepared advisory through the operator's existing Codex sign-in with the concrete `gpt-5.6-sol` catalog model | Eligible ChatGPT plan allowance; no separate API key or API billing account | Primary judged path |
| Manual ChatGPT import | Copy the prepared prompt into ChatGPT and import the structured JSON | Interactive ChatGPT subscription; it is not an API credential | Fallback, not a substitute for validated Codex competition proof |
| Responses API | Programmatic advisory call | Explicit opt-in plus `OPENAI_API_KEY`; API billing and limits are separate from ChatGPT subscriptions | Optional integration |

Plan eligibility, access, and rate limits can vary. BalanceDocket must not describe
subscription-backed use as universally free. A direct ChatGPT subscription does
not authenticate the Responses API and must never be treated as an API key.
Provider identifiers remain explicit: Codex requests `gpt-5.6-sol`; the optional
Responses API request uses the `gpt-5.6` alias that OpenAI maps to GPT-5.6 Sol.

The command family is:

```bash
python3 -m accounting_agent.cli closeproof-advisory status
python3 -m accounting_agent.cli closeproof-advisory prepare
python3 -m accounting_agent.cli closeproof-advisory import
python3 -m accounting_agent.cli closeproof-advisory codex \
  --confirm-use-codex-allowance
python3 -m accounting_agent.cli closeproof-advisory api \
  --enable-network-advisory
```

`prepare` creates the bounded prompt and schema. `codex` and `api` require their
shown explicit safety flags; neither may run because a credential happens to be
present. `codex`, `import`, and `api` must all pass citation, amount, authority,
schema, and snapshot checks. Model and provider attestation checks apply when
the route supplies that provenance; a manual ChatGPT import otherwise remains
`Unverified model identity`. A fixture or simulated advisory must never be
labeled live or validated model output.

## Decision authority

| Layer | Owns | Cannot own |
|---|---|---|
| Source evidence | Exact synthetic invoice and GL facts | Interpretation or approval |
| Deterministic controls | Dates, hashes, duplicate identity, cutoff, day allocation, close dependencies | Policy judgment or human authority |
| GPT-5.6 advisory | Optional citation selection, uncertainty, and evidence-gap flag | Display prose, calculations, approval, posting, lock, or source mutation |
| Local controlled display | Stance-neutral wording around validated advisory selections | Provider prose or human decision authority |
| Human reviewer | Approve treatment, request evidence, reject, and rationale | Rewriting the immutable source snapshot |

The export fails closed if the evidence snapshot changed, a citation is unknown,
an amount or the no-authority invariant changed, completed output is not the
locally generated controlled form, provenance is unsafe, the event chain is
invalid, or a required rationale is missing. Provider prose is discarded before
persistence rather than classified as trusted display text.

## Golden case truth

- Entity: Nordix Services AB.
- Period: June 2026.
- Invoice: INV-4821 from CloudWorks AB.
- Amount: SEK 120,000.00.
- Service period: June 15, 2026 through June 14, 2027, inclusive (365 days).
- June service days: 16.
- June expense: SEK 5,260.27.
- Prepaid asset: SEK 114,739.73.

The image-generation concept showed an illustrative rounded amount. The product
uses the exact daily allocation above; deterministic accounting truth always
overrides generated UI text.

## Competition fit

| Criterion | BalanceDocket evidence |
|---|---|
| Technological implementation | Deterministic controls, subscription-first Codex GPT-5.6 workflow, optional Responses API integration, evidence hashes, dependency evaluation, event-chain verification, responsive app |
| Design | Accepted desktop and mobile evidence-ledger direction with proof layers and accessible human actions |
| Potential impact | Replaces scattered spreadsheet/PDF review with one reproducible exception workflow for a concrete finance persona |
| Quality of idea | Evidence-first reviewer with a visible boundary between rules, model advice, and human authority—not another autonomous accountant |

## Acceptance criteria

- A fresh clone can generate and serve the golden case from README commands.
- Local generation, review, human disposition, and export work without a model,
  network access, or API credential.
- No network request occurs unless the operator explicitly selects `codex` or
  `api`, or manually uses the prepared prompt in ChatGPT.
- Every model route contains only bundled synthetic evidence.
- The competition demo contains a real Codex run requesting `gpt-5.6-sol`, shows
  the validated structured advisory and its provenance limitations, and the
  submission records the primary Codex `/feedback` session ID.
- The deterministic result is stable across runs and wall-clock time.
- All nine canonical stages appear in order with icon plus status text.
- The primary workflow completes with keyboard only at 320 CSS px and desktop.
- Every review action requires rationale and preserves the snapshot digest.
- Unit, integration, frontend, accessibility, build, and full-repo regression
  checks pass before the release candidate.
