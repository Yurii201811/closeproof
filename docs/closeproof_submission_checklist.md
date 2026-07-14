# CloseProof submission checklist

## Product and eligibility

- [x] One track selected: Work & Productivity.
- [x] Built in an isolated worktree from base `aed4507d0c59eeda1ec9ccfbdeffd8fb8c550522`.
- [x] Pre-existing Accounting Agent primitives separated from new CloseProof work.
- [x] Codex plugin/skill is part of the product, not only the build process.
- [x] GPT-5.6 has one material, structured, citation-bound interpretive role.
- [x] Deterministic controls own arithmetic, dates, hashes, and dependencies.
- [x] Synthetic-only and no-write boundaries appear in UI, README, skill, and export.
- [x] Default review path works with no model, network, API key, or OpenAI account.
- [x] Existing Codex sign-in is the primary GPT-5.6 route; manual ChatGPT import
  is the fallback and the Responses API is optional.

## Repository

- [x] Product and design contracts.
- [x] Synthetic fixture and generated PDF path.
- [x] One-command deterministic case generation.
- [x] Loopback-only reviewer server.
- [x] Responsive React workbench.
- [x] Human decision event chain and workpaper export.
- [x] Python and frontend tests plus production build.
- [x] Checked-in local judge bundle and Python-only no-rebuild launcher.
- [x] Add an MIT public repository license under Yurii Bakurov's 2026 copyright.
- [x] After explicit human approval, create a sanitized tip-only archive and a
  new public repository with a new root commit. Do **not** push this working
  repository's existing history because its ancestry contained private
  workspace metadata.
- [x] Scan that exact public export for secrets, local user paths, private
  workspace names, and authenticated task/provider identifiers.
- [x] Verify a functional git archive and a no-local branch clone with fresh
  `npm ci` installs and the full verifier (2026-07-14). Privacy verification of
  the final sanitized export remains pending.

## GPT-5.6 routes

- [x] Provider-specific identifiers are explicit: Codex requests
  `gpt-5.6-sol`; Responses API uses the `gpt-5.6` alias; no silent substitution.
- [x] `closeproof-advisory status` reports the current provider/provenance
  envelope without requesting advice.
- [x] `closeproof-advisory prepare` writes the bounded prompt, synthetic evidence
  packet, and strict response schema.
- [x] `closeproof-advisory codex --confirm-use-codex-allowance` uses the
  existing Codex sign-in and eligible ChatGPT plan allowance without a separate
  API credential or API billing.
- [x] `closeproof-advisory import` validates manual ChatGPT structured output.
- [x] `closeproof-advisory api --enable-network-advisory` remains disabled until
  explicit opt-in and an approved `OPENAI_API_KEY`; the key is neither printed
  nor persisted.
- [x] Optional Responses API request shape uses `store: false`, strict JSON
  Schema, source allowlist, and amount invariants.
- [x] Confirm documentation never treats a direct ChatGPT subscription as an API
  credential or calls subscription use universally free.
- [x] Run the real Codex route requesting `gpt-5.6-sol` and retain request
  provenance, validated structured output, and advisory hash. Codex CLI
  `0.144.0` did not report the returned model identity; do not claim it did.
- [x] Confirm the default case starts `not_requested`, contains no fixture
  advisory, and never presents simulated content as live or validated output.
- [x] Add malformed event/output, unknown-citation, and changed-amount fail-closed
  eval evidence to the release tests.

### Verified local model proof — 2026-07-14

- Codex CLI `0.144.0`, authenticated with ChatGPT; no API key used.
- Requested model: `gpt-5.6-sol`; transport: `codex_cli_chatgpt`;
  attestation: `codex_requested`; schema validation: passed; returned model
  identity: not reported by Codex CLI `0.144.0`.
- Raw authenticated Codex run identifier: retained privately and deliberately
  excluded from public documentation.
- Advisory payload SHA-256:
  `73e139d091f9007556d72543a3cb0f526484953e6745d24d27a3bc0921db259e`.
- Evidence snapshot SHA-256:
  `fda76d0752396535f0e5eb2f7f7b8a3e374db2ea44ee5431ba7ea4a18e10243b`.
- Human decision event 1 verified against review context
  `3262062bd831f15828a7371c300143dcd1ad6b7ba561aac43c40de6c9f76042a`;
  export reported zero accounting actions and zero ERP writes.

## Quality gates

- [x] Python unit and frontend component tests pass on the release candidate.
- [x] Production frontend build passes on the release candidate.
- [x] Repository browser verification covers the local source, calculation,
  no-advisory, and human-decision flow after provider-state integration.
- [x] Repository browser verification covers the real Codex-requested,
  structured-output-validated advisory flow, bound human decision, and exported
  workpaper.
- [x] Capture the final 1440×900 visual state.
- [x] Capture a completed Codex-advisory and locked human-decision state.
- [x] Re-run the 320 CSS px narrow-layout and full-screen proof-sheet browser pass.
- [x] Axe: zero violations in primary, recoverable-error, and decided/export states.
- [x] Native Safari keyboard and maximum 300% browser-zoom pass, including
  focus traversal, mobile proof opening, modal focus wrap, Escape close, and
  focus restoration (2026-07-14).
- [ ] VoiceOver speech-output pass.
- [x] 320 CSS px pass with no horizontal overflow, covering the WCAG
  400%-equivalent reflow width for a 1280 CSS px viewport.
- [x] Firefox and WebKit desktop-drawer smoke passes, plus three consecutive
  320×800 reduced-motion modal passes covering initial focus, focus wrapping,
  Escape close, focus restoration, scroll locking, console errors, failed
  requests, and horizontal overflow (2026-07-14).
- [x] Full repository regression, secret scan, and dependency audit on release candidate.
- [x] In-app Browser-plugin pass completed at 320×800, 768×900, and 1440×900,
  including manual ChatGPT import, human evidence request, validated workpaper
  download, reload persistence, focus containment, and overflow checks
  (2026-07-14).

## Competition submission

- [ ] Request/confirm Build Week credits before the announced cutoff.
- [ ] Run `/feedback` in the primary Codex task and preserve the exact session ID.
- [ ] Show the real Codex run requesting `gpt-5.6-sol` and the validated
  structured output in the recorded demo; disclose that returned model identity
  was not reported, and never use a fixture, unverified paste, or API-shaped
  mock as competition proof.
- [ ] Record 165–175 second real-product demo with audio and captions.
- [ ] Upload public YouTube video and verify playback while signed out.
- [ ] Explain Codex acceleration and key technical/product decisions.
- [ ] Add repository and product URLs to Devpost.
- [ ] Verify every link in a logged-out context.
- [ ] Submit by July 21 at 18:00 Europe/Stockholm target time.
- [ ] Re-open the submitted entry and capture confirmation.
