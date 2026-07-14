# CloseProof Devpost submission draft

Copy from this file only after replacing every **[PENDING]** value and
rechecking the [Build Week page](https://openai.devpost.com/) and
[Official Rules](https://openai.devpost.com/rules). The official deadline is
July 21, 2026 at 17:00 PT.

## Submission fields

- **Project name:** CloseProof
- **Category:** Work & Productivity
- **Tagline:** Source-linked month-end decisions, with rules doing the math and
  humans retaining authority.
- **Repository:** <https://github.com/Yurii201811/closeproof>
- **License:** MIT
- **Public YouTube demo:** [PENDING — under three minutes, publicly visible,
  with audio covering Codex and GPT-5.6]
- **Product or judge-access URL:** Local loopback reviewer launched from the
  public repository; no hosted product URL is required for the judge path.
- **Prebuilt test bundle or sandbox:** `./scripts/run_closeproof_prebuilt.sh`
  serves the checked-in bundle with Python 3.11+; no Node.js, account, model,
  network connection, or rebuild is required.
- **Primary Codex `/feedback` session ID:** [PENDING — do not use the advisory
  run ID]
- **Entrant/team:** Yurii Bakurov

## Short description

CloseProof is a local, source-linked month-end close reviewer for controllers
and senior accountants. It combines deterministic controls, an optional
citation-bound GPT-5.6 advisory, an explicit human disposition, and a
hash-chained workpaper without posting to an ERP or performing an accounting
action.

## Full project description

Month-end review often splits one decision across a ledger export, invoice,
policy note, spreadsheet calculation, chat thread, and sign-off record. That
makes it difficult for a reviewer to answer four basic questions: What source
supports this? Who did the calculation? What did the model contribute? Who made
the accountable decision?

CloseProof turns that fragmented review into one evidence-bound path. The
bundled synthetic case follows Nordix Services AB's June 2026 close. A text PDF
invoice covers service from June 15, 2026 through June 14, 2027. Deterministic
controls establish that 16 of 365 inclusive service days belong to June,
producing exactly SEK 5,260.27 expense and SEK 114,739.73 prepaid asset. The
Adjustments stage remains blocked for human review, and downstream close stages
wait visibly on that decision.

The reviewer opens a proof sheet that keeps source excerpts, hashes, dates,
calculation, optional model interpretation, uncertainty, and human authority in
separate layers. GPT-5.6 may draft a cited interpretation, but it cannot change
the calculation or claim to approve, post, lock, pay, file, send, or execute.
The reviewer must enter a rationale and choose Approve treatment, Request
evidence, or Reject. CloseProof then records a snapshot-bound, append-only
hash-chained event and exports a JSON workpaper. The export reports zero
accounting actions and zero ERP writes.

The complete baseline flow is model-free, network-off, API-free, and does not
require an OpenAI account. The primary judged advisory route uses the operator's
existing Codex sign-in when their plan is eligible. The optional Responses API
route is a separate integration with explicit opt-in, an `OPENAI_API_KEY`, and
separate billing and limits. A ChatGPT subscription is an interactive product
entitlement, not an API credential.

## Why Work & Productivity

CloseProof addresses a specific back-office workflow: a controller resolving a
month-end close exception. It is designed to make the review more effective by
putting the source, deterministic control, bounded model interpretation, human
decision, and audit trail in one coherent workflow. It does not claim measured
production time savings yet; current evidence is a tested end-to-end synthetic
workflow and its reproducible artifacts.

## How the product works

1. Generate the bundled synthetic GL, policy, and text-based invoice pack.
2. Run exact duplicate, cutoff, and prepaid controls locally.
3. Bind source citations and SHA-256 hashes into a stable evidence snapshot.
4. Show the existing nine-stage close dependency model, with one Adjustments
   exception blocking the dependent stages.
5. Optionally request a strict, citation-bound advisory through Codex. Manual
   ChatGPT import and a separately opted-in Responses API route are fallbacks.
6. Reject malformed output, unknown citations, changed amounts, stale
   snapshots, or claims of accounting authority.
7. Require a human rationale and disposition.
8. Append a hash-chained decision event and export the evidence-bound
   workpaper, without making an external accounting change.

## How Codex and GPT-5.6 were used

Codex accelerated rules research, repository inspection, architecture,
implementation, UI iteration, test generation, browser verification, safety
hardening, and submission preparation. The human entrant selected the problem,
persona, track, risk boundary, product shape, and release tradeoffs, then
reviewed the resulting behavior against repository evidence and competition
requirements.

GPT-5.6 has one material but bounded product role: interpret the synthetic
invoice wording and policy in the context of the exact deterministic result,
select supporting citations, expose uncertainty, and flag missing evidence.
Provider prose is discarded; CloseProof renders a local controlled-language
summary for the human reviewer. GPT-5.6 does not own arithmetic or decision
authority.

For the retained real run, **Codex requested `gpt-5.6-sol` and structured output
was validated, but Codex CLI `0.144.0` did not report returned model identity.**
The raw authenticated advisory-run identifier is retained privately and
deliberately excluded from public documentation. It is advisory provenance,
not the submission's required `/feedback` session ID.

## Pre-existing project disclosure

CloseProof extends the pre-existing Accounting Agent repository. The baseline
before Build Week is commit
`aed4507d0c59eeda1ec9ccfbdeffd8fb8c550522`, dated July 11, 2026. It already
contained synthetic accounting proposal workflows, evidence primitives,
dependency-aware close readiness, provider-neutral model-routing foundations,
guarded read contracts, a local operations cockpit, and the no-live-write
boundary.

Work added after the July 13 competition start includes the dedicated
CloseProof golden case, invoice parser/generator, exact close controls,
snapshot and citation contract, bounded advisory evaluator, human decision
chain, loopback service, React reviewer, JSON workpaper, Codex plugin skill,
tests, visual design, demo flow, and competition documentation. The detailed
file-level boundary and retained hashes are documented in
[`docs/build_week_provenance.md`](build_week_provenance.md).

## Human decisions that shaped the result

- Target controllers and senior accountants, not a broad consumer audience.
- Solve one ambiguous close exception end to end rather than simulate a full
  accounting platform.
- Lead with evidence and calculation, not chat.
- Keep arithmetic, dates, hashes, and dependencies deterministic.
- Make model advice optional, cited, structurally validated, and incapable of
  approval or execution. Discard provider prose before persistence and render
  only locally generated controlled language around its validated selections.
- Require human rationale and disposition.
- Use only bundled synthetic evidence and keep the default path local.
- Perform no ERP write, accounting action, payment, filing, or communication.
- Keep ChatGPT/Codex entitlement and API credentials/billing separate.

## Equally weighted judging criteria

| Criterion | Submission evidence | Demo moment |
|---|---|---|
| Technological Implementation | Non-trivial Python and React implementation; deterministic controls; exact integer-ore allocation; strict advisory schema and invariants; evidence snapshots; append-only decision chain; loopback service; dedicated tests and verifier | Generate the case, show a real bounded Codex result, record a human action, and export the workpaper |
| Design | Responsive evidence-ledger UI; visible stage dependencies; proof layers that distinguish source, controls, advisory, and human authority; rationale gating; keyboard, VoiceOver/Safari, and automated accessibility coverage | Open Adjustments on desktop/mobile and move from source excerpt to one clear human action |
| Potential Impact | A concrete controller workflow that consolidates scattered review evidence and makes the final disposition reproducible; impact is presented as a credible workflow hypothesis, not fabricated production metrics | Show one exception from GL and invoice through a traceable workpaper |
| Quality of the Idea | A deliberate alternative to an autonomous accountant: rules calculate, GPT-5.6 interprets within a citation boundary, and the accountable human decides | Point to `Calculated by controls`, `Advisory — cannot approve`, and the required human rationale |

## Judge quick test

No-rebuild path from the repository root:

```bash
./scripts/run_closeproof_prebuilt.sh
```

Then open <http://127.0.0.1:4173> and:

1. Confirm the strip says `Synthetic demo`, `Local controls`, `No ERP writes`,
   and `Advisory optional`.
2. Confirm stages 1-3 are verified, Adjustments requires review, and the later
   stages wait on Adjustments.
3. Open Adjustments and inspect invoice source, the 16/365 calculation, and
   the exact expense/prepaid amounts.
4. Enter a rationale of at least 12 characters and choose Request evidence.
5. Confirm the decision hash chain is internally consistent, the exported
   semantic-validation scope is `current_decision`, and download the JSON
   workpaper.
6. Confirm the export is bound to the same snapshot and reports no external
   actions.

Run the repository verifier separately:

```bash
./scripts/verify_closeproof.sh
```

The checked-in bundle is generated from the same tested React source. The full
verifier rebuilds it and compares the output byte-for-byte with the judge bundle
to prevent source/package drift.

## Limitations and safety boundary

- CloseProof currently accepts only its bundled synthetic golden case; it is
  not approved for real client documents or identifiers.
- It is a focused local reviewer, not production accounting software and not a
  compliance opinion.
- It does not call live Fortnox, Microsoft Graph, email, bank, payment, tax, or
  filing systems and cannot post, approve, lock, pay, send, delete, or file.
- It does not provide OCR for arbitrary PDFs, authentication, billing,
  multi-tenancy, or production hosting.
- The default review works without a model. Codex availability depends on the
  operator's eligible plan, allowance, rate limits, and terms; it is not
  universally free.
- A ChatGPT subscription cannot authenticate the Responses API. The optional
  API route requires separate explicit opt-in, an API key, and separate billing
  and usage limits.
- Structured-output validation establishes schema, citations, amounts,
  authority boundaries, and snapshot binding. The retained Codex CLI did not
  independently report the returned model identity.
- Current impact evidence is technical and workflow validation on synthetic
  data, not a production deployment or measured customer outcome.

## Final submission blockers

- [x] Add the MIT repository license.
- [x] Publish the sanitized repository at
  <https://github.com/Yurii201811/closeproof> from a new root commit.
- [x] Provide a free no-rebuild judge path in the repository.
- [x] Re-verify the no-rebuild path from the final clean archive (2026-07-14).
- [ ] Run `/feedback` in the primary Codex task and paste that session ID into
  the Devpost field.
- [ ] Record and publish a public YouTube demo under three minutes with audio
  covering the working project, Codex, and GPT-5.6.
- [x] Verify the repository and no-rebuild judge-access path without GitHub
  authentication (2026-07-14).
- [ ] Verify public YouTube playback while signed out.
- [ ] Submit before July 21, 2026 at 17:00 PT.
