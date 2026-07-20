# BalanceDocket submission checklist

## Product and eligibility

- [x] One track selected: Work & Productivity.
- [x] Built in an isolated worktree from base `aed4507d0c59eeda1ec9ccfbdeffd8fb8c550522`.
- [x] Pre-existing Accounting Agent primitives separated from new BalanceDocket work.
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
  `npm ci` installs and the full verifier (2026-07-14).
- [x] Scan the pre-rebrand sanitized export and public history for secrets, private
  paths, private workspace names, authenticated identifiers, and tracked
  symlinks; inspect the public repository, raw README/LICENSE, credential-free
  clone, and no-rebuild judge path without GitHub authentication (2026-07-14).

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
- Current retained Codex proof uses review context
  `ecafb2cd52a3bb3443f1e805caaada5bd86cfbcf39f75597562d266ac23aeef8`.
  Its QA decision event 3 verified the corresponding export with zero accounting
  actions and zero ERP writes. For recording, copy only the retained
  `case.json`, invoice, and manifest into an isolated directory and start a new
  decision log; the filmed Request evidence action must become event 1 in that
  disposable log. Do not copy the three-event QA log into the recording state.

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
- [x] Native VoiceOver/Safari semantics and focus pass with speech enabled and
  unmuted, covering the page title, headings, navigation, stage/state labels,
  provider provenance, recorded rationale, decision status, and export control;
  VoiceOver was returned to off after the pass (2026-07-14).
- [x] 320 CSS px pass with no horizontal overflow, covering the WCAG
  400%-equivalent reflow width for a 1280 CSS px viewport.
- [x] Firefox and WebKit desktop-drawer smoke passes, plus three consecutive
  320×800 reduced-motion modal passes covering initial focus, focus wrapping,
  Escape close, focus restoration, scroll locking, console errors, failed
  requests, and horizontal overflow (2026-07-14).
- [x] Full repository regression and dependency audit on the release candidate;
  current-tree and sanitized public-history secret scans passed. The inherited
  private source ancestry was deliberately excluded from the public repository.
- [x] In-app Browser-plugin pass completed at 320×800, 768×900, and 1440×900,
  including manual ChatGPT import, human evidence request, validated workpaper
  download, reload persistence, focus containment, and overflow checks
  (2026-07-14).

## Competition submission

- [x] Register as an individual entrant for OpenAI Build Week (2026-07-14).
- [x] Prepare `BalanceDocket` as the proposed public display brand after a
  preliminary PRV and general web/GitHub/npm/PyPI exact-name screen; retain
  `closeproof` as the stable technical namespace and public repository URL.
- [x] Run an independent exact mark-field search in WIPO Madrid Monitor. On
  2026-07-14, `MARK:"BalanceDocket"` returned no documents and 0 active,
  pending, or inactive Madrid System registrations. This does not cover every
  national or regional register and is not legal clearance.
- [x] Run independent exact-name searches in EUIPO eSearch and TMview. On
  2026-07-14, EUIPO's exact verbal-element condition returned 0 results and
  TMview's exact `Is` condition returned 0 results; nonzero `Apple` control
  searches confirmed both official search flows were returning records.
- [x] Record a preliminary WIPO Nice shortlist: Classes 9 and 42 are the
  primary candidates for downloadable software and SaaS; Class 35 is
  conditional on providing accounting services rather than software alone.
  Exact goods-and-services wording remains subject to a professional review.
- [ ] Before any trademark filing or higher-stakes commercial launch, review
  confusingly similar marks, company names, and overlapping goods/services in
  the intended territories. The current exact-name screens are preliminary,
  not legal advice or legal clearance.
- [x] Confirm BalanceDocket as the public display name. Yurii instructed Codex
  on 2026-07-20 to finish and submit the existing BalanceDocket entry.
- [x] Close the optional-credit gate without submission. The July 17 request
  deadline passed and the official event update says the available credits were
  distributed; credits are not required for eligibility.
- [x] Publish the third-party notices and final branding/docs in the sanitized
  public code release, then repeat the credential-free public-clone and
  no-rebuild verification against
  `c2778b9ffb294fae0383e41a04ae06114244e458` on July 20, 2026.
- [x] Retrieve the primary Codex task identifier and preserve it only in the
  private Devpost `/feedback` field. Never place it in the repository,
  screenshots, demo, issue, commit message, or public submission copy.
- [x] Show the real Codex run requesting `gpt-5.6-sol` and the validated
  structured output in the recorded demo; disclose that returned model identity
  was not reported, and never use a fixture, unverified paste, or API-shaped
  mock as competition proof.
- [x] Prepare the 172-second shot plan, 332-word eight-take teleprompter script,
  recording guide, word-for-word captions, 1280×720 thumbnail, caption-safe
  1920×1080 end card, and Final Cut timeline. A regression test enforces 2:52
  caption duration, continuity, verbatim copy, two-line cues, a 42-character
  line limit, and at most 17 caption characters per second.
- [x] Complete the 23.98p Final Cut V2 picture lock with one ProRes master,
  six section markers, the enlarged-URL end card, and all 41 captions
  (2026-07-14). The delivery project is
  `BalanceDocket — OpenAI Build Week 2026 V2 Picture Lock` in the
  `BalanceDocket V2 Delivery` event. Its duration is exactly `02:51:20`.
  The 1920×1080 H.264 review export has 4,124 frames and runs 172.005 seconds
  with burned-in English captions; a full strict decode and a nine-keyframe
  visual review passed. It is deliberately named
  `BalanceDocket_picture_lock_v2_captioned_NO_AUDIO.mov` because it has no
  audio stream and is not submission-ready. The V2 ProRes master SHA-256 is
  `921cbfb2d4bebebbe7ed1e9102f37b0dbb97eb1a69566cf4996899830e764bbe`;
  the captioned review SHA-256 is
  `3296cfeb4fee9b454355f6a03bbee914cbe41b22870195e0519c6640e02ed6fc`.
- [x] Complete the silent V3 picture lock with the deterministic four-second
  competition/product opener and cleaned Codex command and provenance crops
  (2026-07-14). The ProRes and H.264 masters are both 1920×1080 Rec. 709,
  24000/1001 fps, exactly 4,124 frames, and 172.005167 seconds. Both strict
  full decodes passed with no stderr output; black-frame detection returned no
  intervals; a 19-frame and major-cut visual inspection passed. The ProRes
  SHA-256 is
  `8adb8d682b370feb19d8b7148824c8a1e5ccab55099a33442636fa57b7ae77a9`;
  the silent H.264 review SHA-256 is
  `f330b251f6678aaff96c4d009b4bb0830a94591b1bb34e697720b824ae1194cc`.
- [x] Import the final 41-cue SRT into the preserved
  `BalanceDocket — OpenAI Build Week 2026 V3.1 Narration Ready` Final Cut
  project, verify all eight narration markers and `02:51:20` duration, and
  export the captioned silent QA master for full visual review (2026-07-15).
  The 1920×1080 Rec. 709 H.264 export has 4,124 frames, runs 172.005167
  seconds, contains no audio stream, and burns in all 41 final English SRT
  cues. A strict full decode, black-frame scan, and nine-frame visual review
  passed. SHA-256:
  `215206a4c7911877ab9b89c44f6610000a33454adc1bbc4c4611eb848efe47fe`.
- [x] Preserve and process Yurii's eight narration takes, correct the spoken
  allocation from 335 to 365 days using Yurii's own recorded `sixty`, align the
  41 exact-text cues to the measured takes, and export
  `BalanceDocket_OpenAI_Build_Week_2026_172s.mp4`. The strict verifier passed:
  172.005167 seconds, 4,124 frames, 1920×1080 H.264 at 24000/1001 fps, Rec.709,
  48 kHz mono AAC, -16.4 LUFS, -1.3 dBTP, and complete decode. Final SHA-256:
  `9726acc1af18278a8c63a8e0ac6f7b0dde9f8c69ef8b84c58030f25a29ba97f3`.
- [ ] Perform one uninterrupted human headphone playback of the final master,
  checking spoken amounts, edit joins, and caption boundaries.
- [x] Add and live-test the non-destructive eight-take narration builder
  (2026-07-15). It accepts standard and extensible 16/24-bit PCM WAV, rejects
  slot overruns, aligns the eight files to the locked markers, performs
  two-pass normalization, and writes one 172.005167-second 48 kHz mono 24-bit
  Final Cut track. A real FFmpeg run using eight synthetic extensible 24-bit
  takes produced exactly 172.005167 seconds at -16.0 LUFS with -7.3 dBFS true
  peak; the original takes were not modified.
- [x] Upload the public YouTube video and separate English SRT. Unauthenticated
  metadata verifies Public availability, 172 seconds, 1920×1080, one English
  subtitle track, and eight chapters; the public watch page renders the exact
  first uploaded cue and Studio reports the English track as Published.
- [ ] Perform uninterrupted human headphone playback on desktop and mobile and
  check narration, edit joins, selectable-caption synchronization, and thumbnail
  crop. Do not enable duplicate burned and selectable captions during review.
- [x] Prepare the exact YouTube title, truthful description, eight chapters,
  tags, thumbnail/caption paths, pre-upload verifier gate, and signed-out
  desktop/mobile playback checklist in
  `docs/balancedocket_youtube_package.md` (2026-07-15).
- [x] Explain Codex acceleration and key technical/product decisions in the
  video, YouTube description, README, and Devpost story.
- [x] Add repository and product URLs to the Devpost draft and verify them after
  reload (2026-07-15). Final signed-out verification still follows publication.
- [x] Complete Devpost's user-only image CAPTCHA (2026-07-15). The checkbox is
  verified, and the private `BalanceDocket` project draft is created and saved
  with the final tagline, eight technology tags, saved project story,
  pre-existing-work disclosure, and judge-access repository link. The project
  is also attached to OpenAI Build Week as draft submission
  `1085175-balancedocket` (`4/5` steps complete). Authenticated save-and-reload
  checks through 2026-07-20 confirmed `Individual`, `Sweden`,
  `Work & Productivity`, the repository URL, no-rebuild judge instructions,
  plugin testing instructions, the private primary-task `/feedback` field, the
  public YouTube URL, the project thumbnail, and all four captioned gallery
  images. The public preview embeds the video and renders the saved story,
  technology tags, repository link, and gallery.
- [x] Verify the pre-rebrand public repository, raw README/LICENSE,
  credential-free clone, and no-rebuild judge path without GitHub
  authentication (2026-07-14).
- [x] Repeat the public-clone checks against code release
  `c2778b9ffb294fae0383e41a04ae06114244e458`: 215 npm packages with 0
  vulnerabilities, 17 focused tests, 32 frontend tests, production build and
  bundle parity, 344 full repository tests, HTTP 200 from the Python-only judge
  path, and a complete synthetic Request evidence flow with a valid one-event
  hash chain and zero external actions.
- [ ] Confirm personal eligibility in the authenticated Devpost entry: age of
  majority, eligible residence, no excluded employment or conflict,
  ownership/authorization, and accurate team composition.
- [ ] Verify every link in a logged-out context.
- [ ] Submit by the internal safety target of July 21 at 18:00
  Europe/Stockholm—eight hours before the official July 22 at 02:00 deadline.
- [ ] Re-open the submitted entry, confirm `Submitted`, and capture confirmation.
- [ ] Keep the repository, public video, and judge path free, public, and
  unrestricted through at least August 7, 2026 to cover both published judging
  windows.
