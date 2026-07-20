# BalanceDocket final engineering audit

Audit date: 2026-07-15 (Europe/Stockholm)

This is the output of Prompt 1 in the primary Build Week engineering task. It
records evidence and blockers; it is not a claim that the project is publicly
released, eligible as submitted, or finally submitted.

## Findings

### P0 — submission blockers

1. **The required demo is not deliverable yet.** The captioned picture lock is
   172.005167 seconds and passed strict decode, black-frame, and visual checks,
   but it has no audio stream. The live voice-over folder contains `0/8`
   required narration takes. The official FAQ requires a public YouTube video
   of three minutes or less with a working demo and narration explaining what
   was built, how Codex was used, and how GPT-5.6 is integrated.
2. **The required `/feedback` Session ID is missing.** The official FAQ requires
   `/feedback` to be run in the primary task where the majority of core work
   occurred. This primary task is the correct task, but upload remains subject
   to Yurii's explicit approval and no Session ID has been generated.
3. **The tested sanitized release candidate is not public.** The public repository is
   still at `916ab51f1bbf86fda7e1a84c93a4576627ab8da1`. The tested sanitized
   candidate is local only. Signed-out final-repository verification therefore
   cannot yet be performed.
4. **Required Devpost media and `/feedback` remain incomplete.** The saved
   project story, eight technology tags, judge link, `Individual`, `Sweden`,
   `Work & Productivity`, repository URL, no-rebuild judge instructions, and
   plugin testing instructions all survived an authenticated save-and-reload
   check on 2026-07-15. The `/feedback` field, image gallery, and video URL are
   still blank. The draft remains `2/5` steps complete.
5. **Personal eligibility attestations remain owner-only.** Country support was
   checked for Sweden, but age of majority, ownership, excluded-employment or
   conflict status, and accuracy of team composition require Yurii's truthful
   confirmation in the authenticated submission.

### P1 — release and deadline risks

1. An earlier reload showed that unsaved Additional info values were absent.
   Those fields were re-entered, saved, and verified after reload on 2026-07-15;
   `/feedback` remains intentionally blank pending action-time approval.
2. Optional Codex credits are not an eligibility requirement, but the request
   form closes July 17, 2026 at 12:00 PM PT. Its final submission accepts the
   OpenAI Services Agreement and remains explicitly approval-gated.
3. At the time this audit was executed, the last full runtime qualification
   applied to sanitized candidate
   `65a0bb9d52abbdf430ea46cee7c4ed0f7884ccf3`, tree
   `2b0b82c2645d90c3f326a0ac3d1eeefb35fdf97c`. Later changes through the
   audit subject below were documentation-only. A later exact-tree rerun and
   publication-history scan are recorded in the local release proof.

## Audited state

- Private source commit before this audit record:
  `794ff8d682fb36c7415394f0fb8cac2fa8519759`
- Local sanitized candidate before this audit record:
  `37dcbe77251c30f14fe20ee5b4157806dc712c66`
- Matching source/candidate tree before this audit record:
  `b6e83fda1eb58c3742052b693034bd03cd7512bd`
- Public GitHub baseline:
  `916ab51f1bbf86fda7e1a84c93a4576627ab8da1`
- Captioned silent QA master SHA-256:
  `215206a4c7911877ab9b89c44f6610000a33454adc1bbc4c4611eb848efe47fe`
- Draft submission: `1085175-balancedocket`, `2/5` steps complete
- Primary Codex task: `BalanceDocket — OpenAI Build Week 2026 | Engineering & Release`

## Requirement-to-evidence matrix

| Requirement | State | Evidence and remaining action |
| --- | --- | --- |
| Eligible track | **verified** | Work & Productivity explicitly includes back-office operations; BalanceDocket is a controller month-end review workflow. |
| Existing-project disclosure | **verified** | `docs/build_week_provenance.md` identifies baseline commit `aed4507d0c59eeda1ec9ccfbdeffd8fb8c550522` and the Build Week additions. |
| Material Codex use | **verified locally** | Repository history, primary task, README, and feedback brief document architecture, implementation, UI, tests, browser verification, and release work performed with Codex under Yurii's supervision. `/feedback` upload is still missing. |
| Material GPT-5.6 use | **verified with caveat** | Judged advisory route requests `gpt-5.6-sol`; strict output and invariants were validated. Codex CLI `0.144.0` did not report returned-model identity, so no stronger claim is made. |
| Working non-trivial product | **verified locally** | Exact-tip fresh clone: 17 focused tests, 32 frontend tests, 344 full Python tests, production build, and checked-bundle parity passed. |
| No-rebuild judge path | **verified locally** | Python-only clone with no `node_modules` served HTTP 200; health reported `synthetic_only=true` and `erp_writes=false`. |
| Deterministic accounting calculation | **verified** | June allocation uses 16/365 inclusive days and integer öre: SEK 5,260.27 expense and SEK 114,739.73 prepaid asset. |
| Citation and snapshot binding | **verified** | Case snapshot `fda76d0752396535f0e5eb2f7f7b8a3e374db2ea44ee5431ba7ea4a18e10243b`; unknown citations, changed amounts, and stale snapshots fail closed. |
| Human decision authority | **verified** | Model authority is `advisory_only`; rationale and disposition are required; workpaper reports zero accounting actions and zero ERP writes. |
| Security and privacy | **verified locally** | Candidate tree and ten-commit history passed gitleaks; Host and cross-site POST probes returned 403; restrictive loopback headers passed. Feedback-log readable projection scanned clean; `/feedback` still requires approval. |
| Accessibility and responsive design | **verified locally** | Automated accessibility plus keyboard, VoiceOver, browser, reduced-motion, zoom, and reflow evidence is retained in the checklist and tests. |
| Public repository | **contradicted** | Public remote remains at the older baseline; approved candidate has not been pushed. |
| Public demo under three minutes | **incomplete** | Picture lock is 172.005167 seconds, but narration is `0/8`, final audio master does not exist, and no public YouTube URL exists. |
| English captions | **verified locally** | 41 final SRT cues are present and burned into the silent QA export; selectable YouTube captions still require upload and signed-out verification. |
| Primary-task `/feedback` ID | **missing** | Run `/feedback` in this task only after explicit approval; store the returned ID only in Devpost's private field. |
| Devpost project description | **verified** | The saved story contains the provenance disclosure, eight tags, judge link, and the corrected 344-test claim. |
| Devpost Additional info | **incomplete** | `Individual`, `Sweden`, `Work & Productivity`, repository URL, judge instructions, and plugin testing instructions persisted after save and reload. The required `/feedback` Session ID is still blank. |
| Devpost images | **missing** | Four prepared files exist locally; upload is explicit-approval gated. |
| Signed-out end-to-end access | **missing** | Must follow publication and YouTube upload; verify repository, raw files, judge launch, video, captions, and every Devpost URL. |
| Final Devpost submission | **prohibited pending approval** | Stop before final submission and obtain Yurii's explicit owner approval. |

## Professional next-action order

1. Yurii records the eight narration WAV files using the prepared script.
2. Build and verify the narration track, import it into Final Cut, complete an
   uninterrupted playback, export the master, and pass the final video verifier.
3. Obtain the narrowly scoped approvals for `/feedback`, four project-image
   uploads, candidate publication, optional credits if desired, and YouTube.
4. Publish the exact sanitized candidate, then repeat signed-out clean-clone,
   no-rebuild, raw-file, and secret checks against the public commit.
5. Upload the verified video and SRT, then check audible playback and captions
   while signed out on desktop and mobile.
6. After action-time approval, run `/feedback` in this primary task, save its
   Session ID in the private Devpost field, reload to verify persistence,
   reconcile every public URL, and prepare the final owner handoff.
7. Stop before final Devpost submission for Yurii's review and approval.

## Official live sources checked

- <https://openai.devpost.com/rules>
- <https://openai.devpost.com/details/faqs>
- Authenticated BalanceDocket Additional info and Project details forms on
  2026-07-15
