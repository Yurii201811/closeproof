# BalanceDocket Devpost submission draft

Copy from this file only after replacing every **[PENDING]** value and
rechecking the [Build Week page](https://openai.devpost.com/) and
[Official Rules](https://openai.devpost.com/rules). The official deadline is
July 21, 2026 at 17:00 PT.

## Submission fields

- **Project name:** BalanceDocket
- **Category:** Work & Productivity
- **Tagline:** Evidence-bound month-end review: rules calculate, GPT-5.6
  interprets, humans decide.
- **Repository:** <https://github.com/Yurii201811/closeproof> **[current public
  remote is the older verified baseline; publish and verify the approved
  sanitized candidate before final submission]**
- **License:** MIT
- **Built with:** Codex, GPT-5.6 Sol, Python, TypeScript, React, Vite, Vitest,
  Playwright
- **Public YouTube demo:** [PENDING — under three minutes, publicly visible,
  with audio covering Codex and GPT-5.6]
- **Product or judge-access URL:**
  <https://github.com/Yurii201811/closeproof#judge-quick-start>. The local
  loopback reviewer launches from the public repository; no hosted account is
  required for the judge path. Re-run this path against the exact final public
  commit before submission.
- **Prebuilt test bundle or sandbox:** `./scripts/run_closeproof_prebuilt.sh`
  serves the checked-in bundle with Python 3.11+; no Node.js, account, model,
  network connection, or rebuild is required.
- **Primary Codex `/feedback` session ID:** [PENDING — do not use the advisory
  run ID]
- **Entrant/team:** Yurii Bakurov

## Devpost media package

- **Project Gallery thumbnail:**
  `docs/media/balancedocket-devpost-thumbnail.png` (1200×800, recommended 3:2)
- **Square project icon:** `docs/media/balancedocket-project-icon.png`
  (1024×1024)
- **YouTube thumbnail:**
  `docs/media/balancedocket-build-week-thumbnail.png` (1280×720)
- **Desktop gallery image:**
  `plugins/closeproof/assets/closeproof-desktop.png` — “One exception, nine
  close stages, and an evidence-ledger view that keeps calculation, model
  advice, and human authority separate.”
- **Completed-decision gallery image:**
  `plugins/closeproof/assets/closeproof-completed.png` — “A human Request
  evidence disposition is bound to the same snapshot in an append-only hash
  chain; no ERP write or accounting action is performed.”
- **Mobile gallery image:**
  `plugins/closeproof/assets/closeproof-mobile.png` — “The responsive proof
  sheet preserves the same source, control, advisory, and decision boundaries
  at 390×844.”

## Inspiration

Month-end close exceptions rarely live in one place. The calculation may be in
a spreadsheet, the source wording in an invoice, the policy in a separate
document, the model discussion in chat, and the final sign-off somewhere else.
Controllers do not need another autonomous-accountant claim; they need a
defensible chain showing what the source said, what the rules calculated, what
the model contributed, and which human made the accountable decision.

BalanceDocket was inspired by that missing chain. Its design starts from the
reviewer's evidence and authority boundaries, then gives GPT-5.6 one useful,
inspectable interpretive role inside them.

## Short description

BalanceDocket is a local, evidence-bound month-end close reviewer for controllers
and senior accountants. Deterministic controls calculate the treatment,
GPT-5.6 performs a citation-bound interpretation, and a human records the
accountable disposition in a hash-chained workpaper—without an ERP write or
external accounting action.

## What it does

Month-end review often splits one decision across a ledger export, invoice,
policy note, spreadsheet calculation, chat thread, and sign-off record. That
makes it difficult for a reviewer to answer four basic questions: What source
supports this? Who did the calculation? What did the model contribute? Who made
the accountable decision?

BalanceDocket turns that fragmented review into one evidence-bound path. The
bundled synthetic case follows Nordix Services AB's June 2026 close. A text PDF
invoice covers service from June 15, 2026 through June 14, 2027. Deterministic
controls establish that 16 of 365 inclusive service days belong to June,
producing exactly SEK 5,260.27 expense and SEK 114,739.73 prepaid asset. The
Adjustments stage remains blocked for human review, and downstream close stages
wait visibly on that decision.

The reviewer opens a proof sheet that keeps source excerpts, hashes, dates,
calculation, model interpretation, uncertainty, and human authority in
separate layers. In the judged flow, GPT-5.6 performs the bounded interpretive
step: it connects the ambiguous invoice wording and policy to the exact control
result, selects supporting citations, exposes uncertainty, and flags missing
evidence. It cannot change the calculation or claim to approve, post, lock,
pay, file, send, or execute. The reviewer must enter a rationale and choose
Approve treatment, Request evidence, or Reject. BalanceDocket then records a
snapshot-bound, append-only hash-chained event and exports a JSON workpaper.
The export reports zero accounting actions and zero ERP writes.

The deterministic baseline remains model-free, network-off, API-free, and does
not require an OpenAI account. That fail-safe path does not replace GPT-5.6's
material role in the competition flow. The judged advisory route uses the
operator's existing Codex sign-in when their plan is eligible. The optional
Responses API route is a separate integration with explicit opt-in, an
`OPENAI_API_KEY`, and separate billing and limits. A ChatGPT subscription is an
interactive product entitlement, not an API credential.

## Why Work & Productivity

BalanceDocket addresses a specific back-office workflow: a controller resolving a
month-end close exception. It is designed to make the review more effective by
putting the source, deterministic control, bounded model interpretation, human
decision, and audit trail in one coherent workflow. It does not claim measured
production time savings yet; current evidence is a tested end-to-end synthetic
workflow and its reproducible artifacts.

## How we built it

The product combines a Python evidence, controls, advisory-validation, and
decision-chain layer with a React and TypeScript reviewer built with Vite. The
browser UI is served from a loopback-only Python service, while the same tested
frontend is checked into the repository as a judge bundle so the core workflow
can run without rebuilding or installing Node.js.

The end-to-end workflow is:

1. Generate the bundled synthetic GL, policy, and text-based invoice pack.
2. Run exact duplicate, cutoff, and prepaid controls locally.
3. Bind source citations and SHA-256 hashes into a stable evidence snapshot.
4. Show the existing nine-stage close dependency model, with one Adjustments
   exception blocking the dependent stages.
5. In the judged flow, request a strict, citation-bound GPT-5.6 advisory through
   Codex. Manual ChatGPT import and a separately opted-in Responses API route
   are fallback transports; deterministic review remains the fail-safe when no
   model route is available.
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
Provider prose is discarded; BalanceDocket renders a local controlled-language
summary for the human reviewer. GPT-5.6 does not own arithmetic or decision
authority.

For the retained real run, **Codex requested `gpt-5.6-sol` and structured output
was validated, but Codex CLI `0.144.0` did not report returned model identity.**
The raw authenticated advisory-run identifier is retained privately and
deliberately excluded from public documentation. It is advisory provenance,
not the submission's required `/feedback` session ID.

## Pre-existing project disclosure

BalanceDocket extends the pre-existing Accounting Agent repository. The baseline
before Build Week is commit
`aed4507d0c59eeda1ec9ccfbdeffd8fb8c550522`, dated July 11, 2026. It already
contained synthetic accounting proposal workflows, evidence primitives,
dependency-aware close readiness, provider-neutral model-routing foundations,
guarded read contracts, a local operations cockpit, and the no-live-write
boundary.

Work added after the July 13 competition start includes the dedicated
BalanceDocket golden case, invoice parser/generator, exact close controls,
snapshot and citation contract, bounded advisory evaluator, human decision
chain, loopback service, React reviewer, JSON workpaper, Codex plugin skill,
tests, visual design, demo flow, and competition documentation. The detailed
file-level boundary and retained hashes are documented in
[`docs/build_week_provenance.md`](https://github.com/Yurii201811/closeproof/blob/main/docs/build_week_provenance.md).

## Human decisions that shaped the result

- Target controllers and senior accountants, not a broad consumer audience.
- Solve one ambiguous close exception end to end rather than simulate a full
  accounting platform.
- Lead with evidence and calculation, not chat.
- Keep arithmetic, dates, hashes, and dependencies deterministic.
- Bound model advice to cited interpretation, structurally validate it, and
  make it incapable of approval or execution. Fail safely to deterministic
  human review if the model route is unavailable. Discard provider prose before
  persistence and render only locally generated controlled language around its
  validated selections.
- Require human rationale and disposition.
- Use only bundled synthetic evidence and keep the default path local.
- Perform no ERP write, accounting action, payment, filing, or communication.
- Keep ChatGPT/Codex entitlement and API credentials/billing separate.

## Challenges we ran into

The hardest product challenge was giving GPT-5.6 a material role without
allowing model prose to become accounting truth. We separated deterministic
amounts and dates from interpretation, required a strict citation-bound schema,
rejected changed amounts or unsupported authority claims, and rendered only a
locally controlled summary of validated selections.

Provenance required the same discipline. Codex requested `gpt-5.6-sol`, but the
CLI version used for the retained run did not report the returned model
identity, so the product and submission say exactly that instead of overstating
the evidence. The original repository history also contained private workspace
metadata, which required a sanitized public root and a documented pre-existing
work boundary rather than publishing the development ancestry.

## Accomplishments that we are proud of

- One coherent synthetic workflow now runs from invoice and policy evidence to
  exact integer-öre allocation, bounded GPT-5.6 interpretation, a human
  disposition, and a hash-chained workpaper with zero ERP writes.
- The checked-in judge bundle runs with Python 3.11+ and no rebuild, account,
  API key, model, or network connection.
- The release verifier passes 17 focused BalanceDocket tests, 32 frontend tests,
  the production build and bundle-parity check, and 344 full repository tests.
- The reviewer has responsive, keyboard, VoiceOver, Safari, Firefox, WebKit,
  reduced-motion, zoom/reflow, and automated accessibility coverage.

## What we learned

Trustworthy AI in accounting is primarily a boundary and provenance problem,
not a prompt-writing problem. A model becomes more useful when its job is
narrow enough to validate: interpret cited wording, expose uncertainty, and
flag missing evidence, while deterministic controls and the accountable human
retain their own clearly labeled authority.

We also learned that a free, local, no-rebuild judge path improves both product
resilience and evaluation clarity. The same fail-safe path that helps a judge
inspect the workflow without credentials is the path a controller can still
use when a model route is unavailable.

## What's next for BalanceDocket

The next validation step is five structured walkthroughs with controllers or
accounting managers using the synthetic case. Those sessions should test
whether the evidence layering, rationale gate, and exported workpaper reduce
review ambiguity before any claim about production time savings is made.

After that evidence, narrowly scoped import adapters and additional close
exceptions can be added behind the same synthetic-first, no-write, explicit
permission, and idempotency boundaries. Live posting, payment, filing, and
client communication remain outside the current product.

## Equally weighted judging criteria

| Criterion | Submission evidence | Demo moment |
|---|---|---|
| Technological Implementation | Non-trivial Python and React implementation; deterministic controls; exact integer-ore allocation; strict advisory schema and invariants; evidence snapshots; append-only decision chain; loopback service; dedicated tests and verifier | Generate the case, show a real bounded Codex result, record a human action, and export the workpaper |
| Design | Responsive evidence-ledger UI; visible stage dependencies; proof layers that distinguish source, controls, advisory, and human authority; rationale gating; keyboard, VoiceOver/Safari, and automated accessibility coverage | Open Adjustments on desktop/mobile and move from source excerpt to one clear human action |
| Potential Impact | A concrete controller workflow that consolidates scattered review evidence and makes the final disposition reproducible; impact is presented as a credible workflow hypothesis, not fabricated production metrics | Show one exception from GL and invoice through a traceable workpaper |
| Quality of the Idea | A deliberate alternative to an autonomous accountant: rules calculate, GPT-5.6 interprets within a citation boundary, and the accountable human decides | Point to `Calculated by controls`, `Codex requested · Validated output`, `Advisory — cannot approve`, and the required human rationale |

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

- BalanceDocket currently accepts only its bundled synthetic golden case; it is
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

- [x] Register for OpenAI Build Week on Devpost (2026-07-14).
- [x] Prepare `BalanceDocket` as the proposed public display brand. On
  2026-07-14, preliminary exact-name checks found no match in PRV's Swedish
  trademark database, GitHub repository names, npm, PyPI, or general web
  results. EUIPO eSearch returned 0 exact verbal-element results, and TMview
  returned 0 exact `Is` results; nonzero `Apple` control searches confirmed
  both queries were working. An exact mark-field search in WIPO Madrid Monitor
  (`MARK:"BalanceDocket"`) returned no documents and 0 active, pending, or
  inactive Madrid System registrations. These are limited preliminary screens,
  not national, regional, or legal clearance. Confusingly similar marks,
  company names, and legal clearance remain unverified. A preliminary WIPO
  Nice review identifies Classes 9 and 42 as the primary software/SaaS
  candidates; Class 35 is conditional on providing accounting services rather
  than software alone, and final goods-and-services wording remains unverified.
- [x] Confirm BalanceDocket as the public display name. Yurii instructed Codex
  on 2026-07-20 to finish and submit the existing BalanceDocket entry.
- [x] Close the optional-credit gate without submission. The July 17 request
  deadline has passed, the official update says the available credits were
  distributed, and credits are not an eligibility requirement.
- [x] Add the MIT repository license.
- [ ] Publish the already-committed root third-party notices and pre-existing/
  open-source disclosure through a sanitized tip-only update, then re-verify
  the final public commit.
- [x] Publish the sanitized repository at
  <https://github.com/Yurii201811/closeproof> from a new root commit.
- [x] Provide a free no-rebuild judge path in the repository.
- [x] Re-verify the no-rebuild path from the pre-rebrand public baseline's clean
  archive (2026-07-14).
- [x] Run the complete verifier and Browser flow against the local
  BalanceDocket candidate (2026-07-14).
- [ ] After name approval and publication, repeat secret scanning, clean-clone,
  no-rebuild, signed-out, and public-link verification against the exact final
  public commit.
- [ ] Run `/feedback` in the primary Codex task and paste that session ID into
  the Devpost field.
- [x] Produce and strictly verify the narrated public-demo master locally. The
  172.005167-second H.264/AAC export has 4,124 frames, measures -16.4 LUFS with
  a -1.3 dBTP true peak, and has SHA-256
  `9726acc1af18278a8c63a8e0ac6f7b0dde9f8c69ef8b84c58030f25a29ba97f3`.
- [ ] Publish that master on YouTube as **Public** and upload the duration-aligned
  41-cue English SRT from the final media delivery package.
- [x] Verify the repository and no-rebuild judge-access path without GitHub
  authentication (2026-07-14).
- [ ] Verify public YouTube playback while signed out.
- [x] Create and populate the authenticated Devpost project draft (2026-07-15)
  with the final tagline, eight technology tags, saved project story,
  pre-existing-work disclosure, and judge-access repository link. The draft is
  attached to OpenAI Build Week as submission `1085175-balancedocket` (`2/5`
  steps complete). An authenticated save-and-reload check confirmed
  `Individual`, `Sweden`, `Work & Productivity`, the repository URL, the
  no-rebuild judge instructions, and plugin testing instructions. The required
  primary-thread `/feedback` field remains intentionally blank. Project images
  require separate upload confirmation; the final public YouTube URL and
  signed-out URL checks also remain pending.
- [ ] In the authenticated entry, confirm the entrant is of the age of majority,
  resides in an eligible location, has no excluded employment or conflict,
  owns or is authorized to submit the work, and has accurately listed the team.
- [ ] Obtain Yurii's explicit final approval and submit before July 21, 2026 at
  17:00 PT (July 22 at 02:00 in Stockholm).
- [ ] Re-open the submitted entry, confirm its status is `Submitted`, and keep
  the repository, video, and judge path public, free, and unrestricted through
  at least August 7, 2026 to cover both official-rule and event-page judging
  windows.
