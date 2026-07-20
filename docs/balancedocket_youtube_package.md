# BalanceDocket YouTube delivery package

Use this package only after the narrated export passes
`scripts/verify_balancedocket_video.py`. Uploading or publishing the video is an
external action and remains owner-approval gated.

## Studio fields

- **Title:** `BalanceDocket — Evidence-Bound Month-End Review | OpenAI Build Week 2026`
- **Visibility:** Public. Unlisted or private does not meet the Build Week demo
  requirement.
- **Audience:** Not made for kids.
- **Language:** English.
- **Thumbnail:** `docs/media/balancedocket-build-week-thumbnail.png`
- **Selectable captions:** `BalanceDocket_captions_FINAL_ALIGNED.srt` from the
  final media delivery package
- **Code:** <https://github.com/Yurii201811/closeproof>
- **License note:** The repository is MIT-licensed. Do not imply that the
  YouTube platform license changes the repository license.

## Verified local delivery

- Video: `BalanceDocket_OpenAI_Build_Week_2026_172s.mp4`
- SHA-256: `9726acc1af18278a8c63a8e0ac6f7b0dde9f8c69ef8b84c58030f25a29ba97f3`
- Duration and frames: 172.005167 seconds, 4,124 decoded frames
- Encoding: H.264 1920×1080 yuv420p at 24000/1001 fps, Rec.709; AAC 48 kHz mono
- Delivery audio: -16.4 LUFS integrated, -1.3 dBTP true peak
- Strict verifier: passed on 2026-07-20
- Aligned selectable-caption SHA-256:
  `2f375252d4c9af6e17d214233f55cfb94efa43d9ee53a94dc3d4d58fb5f6b4c5`

## Description

```text
BalanceDocket is an evidence-bound month-end close reviewer built for OpenAI Build Week 2026 in the Work & Productivity category.

Rules calculate. GPT-5.6 interprets. Humans decide.

This demo follows one fully synthetic June close exception from source evidence through deterministic controls, a citation-bound GPT-5.6 advisory, a human Request evidence decision, and a hash-chained workpaper. The workflow performs zero ERP writes and zero external accounting actions.

Try the free, no-rebuild judge path:
https://github.com/Yurii201811/closeproof#judge-quick-start

From the repository root:
./scripts/run_closeproof_prebuilt.sh

Then open http://127.0.0.1:4173. Python 3.11+ is the only runtime requirement; no Node.js, account, API key, model, network connection, or rebuild is required for the deterministic bundled case.

Codex accelerated the Python and React implementation, test generation, accessibility work, browser verification, release checks, and submission preparation. In the judged advisory route, Codex requested GPT-5.6 Sol through the entrant's eligible ChatGPT plan without an API key. BalanceDocket validates schema, citations, exact amounts, snapshot binding, and no-authority constraints before any advisory is shown. Codex CLI did not independently report the returned model identity, so the project discloses the requested model without claiming independent confirmation.

BalanceDocket extends a pre-existing Accounting Agent repository. The baseline and every Build Week addition are documented here:
https://github.com/Yurii201811/closeproof/blob/main/docs/build_week_provenance.md

MIT licensed. Synthetic data only. No ERP writes.

Chapters
0:00 Problem and product
0:15 Codex workflow and local baseline
0:34 Deterministic controls
1:02 Codex and GPT-5.6 route
1:36 Validated advisory boundary
2:00 Human decision
2:25 Workpaper proof
2:42 Build proof and close
```

## Tags

```text
BalanceDocket, OpenAI Build Week, Codex, GPT-5.6, month-end close, accounting automation, controller workflow, audit trail, React, Python, human in the loop, evidence-bound AI
```

## Pre-upload gate

1. Export `BalanceDocket_OpenAI_Build_Week_2026_172s.mp4` from the locked Final
   Cut timeline after importing Yurii's verified narration track at
   `00:00:00:00` and aligning the captions to the real reading.
2. Run
   `python3 scripts/verify_balancedocket_video.py "/path/to/BalanceDocket_OpenAI_Build_Week_2026_172s.mp4"`.
3. Require H.264 1920×1080 Rec. 709 at 24000/1001 fps, exactly 4,124 decoded
   frames, an audible 48 kHz AAC stream, integrated loudness from -18 to -14
   LUFS, true peak no higher than -1 dBTP, duration below 180 seconds, and a
   strict full decode.
4. Watch the complete export at normal speed with headphones. Check every cut,
   spoken amount, product label, caption boundary, and the Codex/GPT-5.6
   disclosure. Do not use the silent captioned QA master as the upload file.

## Post-upload gate

After processing finishes, verify while signed out on both desktop and mobile:

- Visibility is **Public** and playback works without an account.
- Duration is below three minutes and 1080p is available.
- Narration is clearly audible from start to finish.
- English selectable captions are available and synchronized. Disable the
  selectable track when checking a burned-caption QA copy to avoid duplicate
  text; the clean public master should use selectable captions.
- The description renders the eight chapter links and both repository links.
- The custom thumbnail is visible and not cropped incorrectly.
- The repository and judge quick-start links open without authentication.

Only after those checks should the public YouTube URL replace the `[PENDING]`
value in `docs/devpost_submission.md` and be saved in Devpost Project details.
Final Devpost submission still requires Yurii's explicit approval.
