# BalanceDocket demo and voice-over script

Target: **2 minutes 52 seconds (172 seconds)**. Record the real product at
1440×900, edit in a 1920×1080 Rec. 709 timeline, use audible narration and
captions, and keep the final export below 2:55.

- Final Cut library: `BalanceDocket Build Week 2026`
- Final Cut delivery event: `BalanceDocket V3.1 Delivery`
- Final Cut delivery project:
  `BalanceDocket — OpenAI Build Week 2026 V3.1 Narration Ready`
- Final Cut picture lock: one clean V3 ProRes master. The validated V3.1 FCPXML
  defines eight narration markers, and the final 41-cue English SRT is imported
  as relative English SRT captions. The 172.005-second timeline displays as
  `02:51:20`. V3 opens with
  a four-second competition and product card, then hard-cuts to the working
  product. It also uses cleaner Codex command and provenance crops while
  preserving the V2 advisory, human-decision, workpaper, and closing sequence.
- iMovie fallback library: `~/Movies/BalanceDocket Build Week 2026.imovielibrary`
- iMovie fallback project: `BalanceDocket — OpenAI Build Week 2026`
- iMovie fallback scaffold: the final 1920×1080 end card is imported as a
  static, full-frame 9.98-second clip. It is retained only as a fallback; the
  Final Cut picture lock is the current production source of truth.
- Export: `BalanceDocket_OpenAI_Build_Week_2026_172s.mp4`
- V3 ProRes picture master (no captions or audio):
  `~/Movies/BalanceDocket Build Week 2026 Media/Polished/BalanceDocket_picture_lock_v3_PRORES_NO_AUDIO_NO_CAPTIONS.mov`
- Captioned picture-lock QA export (not submission-ready):
  `~/Movies/BalanceDocket Build Week 2026 Media/Polished/BalanceDocket_picture_lock_v3_captioned_NO_AUDIO.mov`
  This 1920×1080 Rec. 709 H.264 export has 4,124 frames, runs 172.005167
  seconds, contains no audio stream, and burns in the final 41 English SRT
  cues. A strict full decode, black-frame scan, and nine-frame visual review
  passed on 2026-07-15. SHA-256:
  `215206a4c7911877ab9b89c44f6610000a33454adc1bbc4c4611eb848efe47fe`.
- YouTube title: `BalanceDocket — Evidence-Bound Month-End Review | OpenAI Build Week 2026`
- Paste-ready YouTube description, chapters, tags, upload settings, and
  signed-out verification gates: `docs/balancedocket_youtube_package.md`
- Teleprompter narration: `docs/balancedocket_voiceover.txt`
- Voice-over recording guide: `docs/balancedocket_voiceover_recording_guide.md`
- Recording handoff folder:
  `~/Movies/BalanceDocket Build Week 2026 Media/Voiceover`
- Importable captions: `docs/balancedocket_demo_captions.srt`
- YouTube thumbnail: `docs/media/balancedocket-build-week-thumbnail.png`
- Caption-safe 1080p end card: `docs/media/balancedocket-build-week-end-card.png`
- Editable end-card source: `docs/media/balancedocket-end-card.html`

The picture lock contains real product recordings and truthful sanitized proof
cards; it contains no generated product mockups or narration. The opening card
is a deterministic layout built from a real product screenshot, not a product
mockup. The V3 picture lock deliberately has no audio stream. Import Yurii's
recorded takes, align the captions to the actual reading, and complete a full
audio/video playback before creating the final submission export.

## Voice-over capture spec

- Record in English at roughly 130 words per minute, one timed section per
  take, with 250–500 ms of room tone before and after each take.
- Preferred delivery: calm controller walkthrough, conversational rather than
  promotional; emphasize “rules calculate,” “GPT-5.6 interprets,” and “human
  decides.”
- Preferred file format: mono 48 kHz WAV (24-bit when available). Keep peaks
  between -12 and -6 dBFS and avoid noise reduction that clips word endings.
- Name the takes `01_problem.wav`, `02_baseline.wav`, `03_controls.wav`,
  `04_codex.wav`, `05_advisory.wav`, `06_decision.wav`, `07_workpaper.wav`, and
  `08_close.wav`. Keep the raw takes; edit copies in the chosen final editor
  and normalize the narration consistently.
- Before importing, run
  `python3 scripts/verify_balancedocket_voiceover.py "/path/to/Voiceover"`.
  Fix every error and review pacing/level warnings; the preflight rejects
  missing, malformed, silent, stereo, non-48 kHz, or clipped recordings. Then
  build one non-destructive, marker-aligned Final Cut track with
  `python3 scripts/build_balancedocket_voiceover_track.py "/path/to/Voiceover" "/path/to/Voiceover/BalanceDocket_voiceover_track.wav"`.
  The builder accepts verified 16/24-bit PCM, rejects takes that exceed their
  picture windows, and uses two-pass loudness normalization before writing the
  exact 172.005167-second 48 kHz mono track.
- Import `docs/balancedocket_demo_captions.srt` after the narration timing is
  locked, then nudge caption boundaries to the actual reading rather than
  time-stretching the voice.
- Mix the final narration to approximately -16 LUFS integrated, keep true peak
  at or below -1 dBTP, and export 48 kHz AAC audio. Run
  `python3 scripts/verify_balancedocket_video.py "/path/to/final.mp4"` and fix
  every release-gate error before upload.
- Use no copyrighted music. Silence under the narration is acceptable and
  keeps the accounting evidence legible.

## 0:00–0:15 — Problem and product

**Shot:** Show the real reviewer with the persistent safety strip and all nine
stages visible. Move from verified stages 1–3 to Adjustments and the waiting
downstream stages.

**Voice-over:**

> Month-end review often splits one decision across a ledger, invoice, policy,
> spreadsheet, and sign-off. BalanceDocket gives controllers one evidence-bound
> path through the exception, keeping calculation, model advice, and human
> authority separate.

## 0:15–0:34 — Codex workflow and local baseline

**Shot:** After the display-name candidate is approved and published, briefly
show the final public repository's BalanceDocket skill or a clean `$closeproof`
invocation. Show the synthetic-case command and only the snapshot SHA,
`external_calls: 0`, and `erp_writes: 0`, then return to the reviewer.

**Voice-over:**

> This is a bundled synthetic June close. Through the BalanceDocket skill,
> Codex generates the fixture, runs the local case, checks status, and prepares
> the bounded advisory. The baseline needs no model, network, OpenAI account,
> or API key.

## 0:34–1:02 — Source and deterministic controls

**Shot:** Open **Adjustments**. Hold on `INV-4821:p1:L8`, then show duplicate
identity and posting cutoff as verified. Keep `Calculated by controls`,
`16 / 365`, `SEK 5,260.27`, and `SEK 114,739.73` readable for at least three
seconds.

**Voice-over:**

> Inside Adjustments, the invoice period runs from June fifteenth, twenty
> twenty-six, through June fourteenth, twenty twenty-seven. Controls—not the
> model—verify its identity and cutoff, then allocate sixteen of three hundred
> sixty-five days to June: five thousand two hundred sixty kronor and
> twenty-seven öre expense; one hundred fourteen thousand seven hundred
> thirty-nine kronor and seventy-three öre prepaid.

## 1:02–1:36 — Real Codex and GPT-5.6 route

**Shot:** Show the exact retained route as a caption, not as a newly executed
command:

```bash
python3 -m accounting_agent.cli closeproof-advisory codex \
  --case .local/closeproof-browser-qa/case.json \
  --confirm-use-codex-allowance
```

Show only a sanitized projection of the retained status from the disposable
recording copy prepared below:

```bash
python3 -m accounting_agent.cli closeproof-advisory status \
  --case "$recording_state/case.json" |
jq '{
  status,
  provider,
  output: {
    citation_ids: .output.citation_ids,
    uncertainty: .output.uncertainty,
    cannot_approve: .output.cannot_approve
  },
  provenance: {
    transport: .provenance.transport,
    requested_model: .provenance.requested_model,
    reported_model: .provenance.reported_model,
    schema_validated: .provenance.schema_validated,
    model_attestation: .provenance.model_attestation
  }
}'
```

The visible truth must be `codex_cli`, requested model `gpt-5.6-sol`, reported
model `null`, schema validated `true`, and attestation `codex_requested`.

**Voice-over:**

> This retained Codex run requested GPT-5.6 Sol through my eligible ChatGPT
> plan, without an API key. BalanceDocket sent bounded synthetic excerpts,
> exact amounts, and a strict schema. The result passed schema, citation,
> amount, no-authority, and snapshot checks. Codex CLI did not report the
> returned model, so I disclose the request without claiming independent
> confirmation.

## 1:36–2:00 — Validated advisory boundary

**Shot:** Show `Codex requested · Validated output`,
`Advisory — cannot approve`, medium uncertainty, the three citation chips, the
missing-evidence notice, and
`Controlled display generated locally; provider prose is not stored`. Do not
expose the private run ID.

**Voice-over:**

> The result is labeled “Codex requested, validated output.” It selected three
> source-linked citations, reported medium uncertainty, and flagged missing
> evidence. Provider prose was discarded. BalanceDocket builds the conclusion
> locally from validated selections and fixed amounts. The advisory cannot
> change calculations, approve, post, lock, pay, file, send, or alter source
> data.

## 2:00–2:25 — Human decision

**Shot:** Enter this exact rationale:

> The cited inclusive service period and deterministic integer-öre allocation
> support the prepaid treatment; missing invoice-total evidence is recorded for
> human follow-up.

Pause with all three actions visible, choose **Request evidence**, then show
`Evidence requested`, the current event, a consistent local hash chain, and no
ERP write.

**Voice-over:**

> Authority stays with the reviewer. I record that the cited service period and
> exact integer-öre allocation support prepaid treatment, while missing evidence
> needs follow-up. I choose Request evidence—the safe, repeatable disposition.
> The decision stays bound to this snapshot in an append-only local hash chain;
> no ERP write occurs.

## 2:25–2:42 — Workpaper proof

**Shot:** Download the validated workpaper. Show the success message and a
prepared readable view of:

- `snapshot_sha256`
- `advisory.provenance.payload_sha256`
- `human_decision.action`
- `human_decision.accounting_action_performed: false`
- `human_decision.erp_write_performed: false`
- `event_chain.valid: true`
- `event_chain.semantic_validation_scope: "current_decision"`
- `external_actions_performed: []`

**Voice-over:**

> The workpaper binds source hashes, deterministic calculation, advisory hash,
> human rationale, action, snapshot, chain head, and validation scope. It
> reports zero accounting actions and zero ERP writes, so another reviewer can
> audit the decision.

## 2:42–2:52 — Build proof and close

**Shot:** End on `docs/media/balancedocket-build-week-end-card.png`. Its footer
ends at y=830, leaving the lower 220 pixels clear for the final closed captions:

```text
BalanceDocket
Work & Productivity
github.com/Yurii201811/closeproof
Rules calculate · GPT-5.6 interprets · Humans decide
```

**Voice-over:**

> Codex accelerated the Python and React build, tests, accessibility, and release
> checks. I made every product decision and final judgment.

## Recording guardrails

- Use `.local/closeproof-browser-qa/case.json` as the source; it contains the
  retained real `codex_cli` result. The port-4193 manual ChatGPT-import state is
  not valid competition model proof.
- Prepare an isolated recording state that carries the retained case, invoice,
  and manifest but deliberately starts with no human-decision log:

  ```bash
  retained_state=.local/closeproof-browser-qa
  recording_state=$(mktemp -d "${TMPDIR:-/tmp}/closeproof-recording.XXXXXX")
  cp "$retained_state/case.json" \
    "$retained_state/invoice_INV-4821.pdf" \
    "$retained_state/manifest.json" \
    "$recording_state/"
  chmod 600 "$recording_state"/*

  python3 -m accounting_agent.cli closeproof-serve \
    --case "$recording_state/case.json" \
    --events "$recording_state/decision-events.jsonl" \
    --web plugins/closeproof/assets/web \
    --port 4195
  ```

  Do **not** copy `decision-events.jsonl`, its head, or its lock from the retained
  QA directory. Those files already contain three verification events; copying
  them would make the current context already decided. The recorded click must
  create event 1 in the disposable log. Never regenerate the retained validated
  case with `closeproof-demo`.
- Never show raw status output or expanded provenance; the retained case contains
  a private authenticated run ID.
- Do not describe Codex-plan access as universally free. Plan eligibility,
  allowance, rate limits, and terms apply.
- If a new Codex run is rate-limited, stop. Do not relabel a fixture, manual
  import, or API-shaped mock as the competition result.
- Do not show the `/feedback` session ID in the video; place it only in Devpost.
- Use simple hard cuts, legible captions, no copyrighted music, and no
  third-party trademarks beyond what is necessary to explain the tools used.
