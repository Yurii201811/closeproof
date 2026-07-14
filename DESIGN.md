# CloseProof design contract

Status: accepted for implementation on July 13, 2026 after two ChatGPT image
iterations: one desktop refinement and one responsive companion.

## Direction

**Evidence ledger**: a contemporary audit room, not AI fintech.

- Warm paper surface, black-brown ink, thin rules.
- Coral marks exceptions; dark green marks verified controls.
- Grotesk interface type, tabular figures, tiny monospace provenance.
- Calm, dense, serious, and implementation-ready.
- No gradients, glass, glowing AI element, chat transcript, KPI card grid,
  marketing hero, decorative illustration, or device frame.

## Persistent safety boundary

A slim dark strip is always visible and reads exactly:

`Synthetic demo · Local controls · No ERP writes · Advisory optional`

The same boundary appears in the exported workpaper. The strip is not
dismissible. Route and provider state appear in the advisory panel, not in the
safety strip. The interface must never imply that a subscription is an API
credential or that subscription-backed use is universally free.

## Desktop composition

- 15% left context rail.
- 50% central close ledger.
- 35% contextual proof drawer.
- Minimum useful desktop width: 1280 CSS px.
- The app occupies the viewport; no presentation frame.

Left rail contains only current entity/period context and primary navigation:
Close workflow, Review queue, Evidence library, Audit log, Settings.

The center always shows all nine stages in this exact order:

1. Evidence completeness
2. Bank reconciliation
3. Subledgers
4. Adjustments
5. Balanced trial balance
6. VAT control
7. Preparer review
8. Independent sign-off
9. Lock readiness

Each stage shows its number, dependency point, icon plus status text, owner,
evidence count, blocker, and next action. A vertical proof line makes downstream
waiting visible. Selecting a row opens the proof drawer without losing stage
context.

## Proof drawer hierarchy

1. **Source evidence** — document identity, page/line citation, highlighted
   evidence excerpt, evidence hash.
2. **Deterministic allocation** — exact inputs and formulas, stamped
   `Calculated by controls`.
3. **GPT-5.6 advisory** — route, provenance, cited interpretation, uncertainty,
   missing evidence, and persistent `Advisory — cannot approve` label. Before a
   validated result exists, the workbench offers the server-built manual prompt
   and import fallback. Status, Codex, and explicitly opted-in API execution stay
   in the documented CLI; the reviewer server never invokes a model.
4. **Human rationale** — required free text.
5. **Reviewer actions** — Approve treatment, Request evidence, Reject.
6. **Provenance** — snapshot SHA, decision state, event-chain verification.

The action order is deliberate: approval is primary but never automatic;
requesting evidence is outlined in coral; rejection remains available without
visual alarmism.

## Mobile composition

At widths below 1280 CSS px:

- Hide the persistent rail in favor of a compact context header.
- Keep the safety strip visible.
- Render the nine stages as a single-column dependency ledger.
- Open proof detail as a full-screen sheet in the real app, with a visible close
  control and focus return. The accepted concept shows the expanded sheet inline
  to document content order.
- Keep the three reviewer actions in a sticky bottom bar.
- Never hide critical actions behind a hamburger menu.
- Use 44 by 44 CSS px minimum interactive targets.

At 320 CSS px and 400% zoom, evidence may wrap vertically but must not clip or
require horizontal scrolling.

## Tokens

| Token | Value | Use |
|---|---:|---|
| `--paper` | `#f7f2e8` | App background |
| `--paper-raised` | `#fffdf8` | Proof and selected surfaces |
| `--ink` | `#201b17` | Primary text and safety strip |
| `--ink-muted` | `#6c6259` | Secondary metadata |
| `--rule` | `#d8cfc1` | Dividers and fields |
| `--verified` | `#2f6848` | Verified state and primary action |
| `--verified-soft` | `#e8f0ea` | Verified tint |
| `--rule-strong` | `#918374` | Strong field and structural boundaries |
| `--exception` | `#a94034` | Review-required and reject emphasis |
| `--exception-soft` | `#faece8` | Selected exception surface |
| `--waiting` | `#6d6359` | Waiting state |
| `--focus` | `#225cc5` | Keyboard focus ring |

Typography uses system UI sans for reliability and `ui-monospace` for hashes,
source IDs, formulas, and model request IDs. Body copy is at least 14 CSS px on
desktop and 15 CSS px on narrow screens.

## Component inventory

- SafetyStrip
- ContextRail and MobileContextHeader
- CloseHeader
- StageLedger and StageRow
- StatusMark
- DependencySpine
- ProofDrawer / MobileProofSheet
- SourceCitation
- DeterministicCalculation
- AdvisoryPanel
- AdvisoryRouteStatus and AdvisoryRouteActions
- RationaleField
- ReviewerActionBar
- ProvenanceFooter
- StateNotice
- ExportWorkpaperButton

## Required states

- Loading case and skeleton ledger.
- Ready with review required.
- Empty period.
- Invalid or unsupported fixture.
- Evidence missing or hash mismatch.
- Stale snapshot.
- Downstream waiting.
- Advisory `not_requested`: deterministic review remains fully usable; no
  fixture or simulated advisory is rendered.
- Advisory `running`: show the selected route and keep calculations immutable.
- Advisory `completed`: show provider-specific provenance and validation label.
  Codex reads `Codex requested · Validated output`; disclose requested model,
  reported model, model attestation, run ID, response ID, schema validation,
  payload SHA, and evidence SHA when the backend supplies them. A manual
  ChatGPT import reads `Unverified model identity` unless its model identity can
  be independently established. A Responses API result that passes response
  and model checks reads `Verified`.
- Model identifiers are provider-specific and visible: Codex requests the
  concrete `gpt-5.6-sol` catalog entry, while the Responses API uses its
  `gpt-5.6` alias. Never present one as a silent fallback for the other.
- Advisory `unavailable`: distinguish Codex sign-in/plan/rate-limit failure,
  manual response not supplied, API disabled or missing key, and transport
  failure.
- Advisory `invalid`: distinguish malformed output, wrong model where identity
  is available, stale snapshot, unknown citation, changed amount, and authority
  invariant/provenance failure. Provider prose is never an advisory state: it is
  discarded before persistence and replaced by a stance-neutral local display.
- Prompt prepared for Codex or manual ChatGPT use.
- Responses API opt-in awaiting a key; a ChatGPT subscription is not accepted
  as an API credential.
- Human approval, evidence requested, and rejection.
- Export ready and export blocked.
- Offline / loopback server unavailable.

No state may rely on color alone. Every status has an icon, visible text, and an
accessible name. Never show fixture data as a completed or live advisory. Only
a result that passes the applicable route's citation, amount, authority,
snapshot, schema, and available model-identity checks may use a validated label.

## Interaction and accessibility

- WCAG 2.2 AA target.
- Skip link, landmarks, semantic buttons, labels, headings, and status regions.
- Visible 3 px focus ring with 2 px offset.
- Focus returns to the selected stage after closing a mobile proof sheet.
- `Escape` closes the proof sheet; it does not discard typed rationale.
- Live regions announce load failure, advisory state, decision outcome, and
  export result without moving focus.
- Route controls disclose when an action will leave the local machine. `Codex`
  identifies use of the existing Codex/ChatGPT plan allowance; `Responses API`
  requires a separate explicit opt-in and API key.
- Reduced motion removes nonessential transitions.
- Forced-colors mode preserves boundaries and status text.
- VoiceOver/Safari and Chromium keyboard smoke tests are release gates.

## Fidelity rule

The accepted images define layout, hierarchy, density, and tone—not accounting
truth. Source dates, arithmetic, status logic, exact strings, and accessibility
are governed by repository code and tests. Where generated pixels disagree with
deterministic controls, the controls win and the fidelity ledger records the
intentional difference.
