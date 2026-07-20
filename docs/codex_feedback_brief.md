# BalanceDocket Codex feedback and release-review brief

This brief prepares the primary OpenAI Build Week engineering task for an
evidence-based `/feedback` capture and final owner review. It is a release
control document, not a substitute for the Session ID returned by `/feedback`.

Use this sequence in the existing primary task. Do not create a fresh showcase
task: the Build Week FAQ requires the `/feedback` Session ID from the task where
the majority of the core work occurred.

## Professional engineering record

Yurii Bakurov is the entrant, product owner, and final decision-maker for
BalanceDocket. The task should make the following engineering decisions easy to
inspect:

- selected the **Work & Productivity** track and a controller or senior
  accountant as the primary user;
- narrowed a broad accounting-agent concept to one evidence-bound month-end
  exception workflow;
- assigned dates, integer-öre arithmetic, hashes, and close dependencies to
  deterministic code;
- made GPT-5.6 material in the judged flow for bounded citation selection,
  uncertainty, and an evidence-gap flag, without approval or execution
  authority;
- required an explicit human rationale and disposition before recording a
  decision;
- preserved a local, synthetic-only, network-off, API-free baseline with zero
  ERP writes and zero external accounting actions; and
- retained human authority over scope, technical tradeoffs, public release,
  terms acceptance, and submission.

Codex accelerated repository analysis, architecture, implementation, test
generation, UI iteration, browser verification, release hardening, and
documentation. Describe that collaboration directly. Do not imply that every
artifact was typed manually or that Codex independently owned product decisions.

## Review operating contract

### Source precedence

1. Official Build Week rules and FAQ govern eligibility.
2. Directly observed repository, browser, remote, and media state governs
   current status.
3. Fresh verifier output governs technical claims.
4. Repository contracts explain intent but cannot self-verify.

Report every conflict. Never infer `verified` or `missing` from an external
system that could not be accessed.

### Required state header

Every review begins with:

- observation timestamp and time zone;
- workspace, branch, and clean or dirty status;
- private source HEAD and tree;
- sanitized candidate HEAD and tree;
- publication-ready HEAD and tree, when it exists;
- public remote HEAD and observation time;
- relevant tool versions and exact commands; and
- retained report, log, media, or artifact locations.

### Evidence status vocabulary

Use exactly one of these states for each requirement:

- `verified` — directly proven by current evidence;
- `contradicted` — current evidence disproves the claim;
- `incomplete` — some required evidence exists, but a gate is unfinished;
- `missing` — the required artifact or value is directly confirmed absent;
- `unverified` — access, authority, or evidence is insufficient to decide.

The evidence matrix must include `Requirement`, `State`, `Scope`, `Evidence`,
`Observed at`, and `Next gate`. A P0 finding or any `unverified` mandatory
requirement prevents an eligibility-ready conclusion. Never shorten `locally
ready` to `ready`.

### Required response schema

Every stage response must use this order:

1. State header
2. Findings ordered P0, P1, then P2
3. Six-column evidence matrix
4. Engineering decision record
5. Authorized mutations performed, or `none`
6. Unverified external state
7. Smallest next action
8. Gate result

The final line must be exactly one of `BLOCKED`, `LOCALLY READY`,
`PUBLICLY RECONCILED`, or `READY FOR OWNER REVIEW`. Use only the result that the
current evidence supports; the label does not authorize the next external
action.

### Engineering decision record

Use this compact table when explaining significant design or release choices:

| Engineering decision | Tradeoff | Failure mode prevented | Verification | Final owner |
| --- | --- | --- | --- | --- |

Professionalism comes from traceable judgment, not adjectives. Do not rewrite
historical user messages or imply that every earlier prompt used polished
release-engineering language.

### Mutation and stop rules

- An audit is read-only except for writing its requested report.
- Do not alter source, release artifacts, media, browser drafts, or external
  systems unless the prompt explicitly authorizes that bounded change.
- Do not push, upload, publish, accept terms, spend credits, run `/feedback`, or
  submit Devpost without the required action-time owner approval.
- Never perform a final accounting action.
- When a gate fails, stop the readiness claim and identify the smallest concrete
  next action.

## Evidence anchors

- Product contract: [`PRODUCT.md`](../PRODUCT.md)
- Design contract: [`DESIGN.md`](../DESIGN.md)
- Build-period boundary: [`build_week_provenance.md`](build_week_provenance.md)
- Public judge path: [`README.md`](../README.md)
- Verification gates:
  [`closeproof_submission_checklist.md`](closeproof_submission_checklist.md)
- Devpost copy: [`devpost_submission.md`](devpost_submission.md)
- Timed recording plan: [`closeproof_demo_script.md`](closeproof_demo_script.md)
- YouTube delivery package:
  [`balancedocket_youtube_package.md`](balancedocket_youtube_package.md)
- Narration capture and assembly:
  [`balancedocket_voiceover_recording_guide.md`](balancedocket_voiceover_recording_guide.md)

The current release proof is intentionally ignored and private. Resolve it by
searching the repo-adjacent `.local` audit roots for `RELEASE_PROOF.md`, record
the selected path in the private state header, and never copy that path into a
public artifact. If exactly one applicable current proof cannot be established,
mark current release qualification `unverified`.

### Canonical verification commands

Use the repository's commands and scripts rather than paraphrased test claims:

```bash
git status --short
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git rev-parse HEAD^{tree}
git diff --check
./scripts/verify_closeproof.sh
python3 scripts/verify_balancedocket_video.py --help
```

Also retain the exact commands and output for reachable-history secret and
private-path scanning, archive-versus-tree file comparison, the Python-only
no-rebuild judge probe, public-remote resolution, and signed-out checks. Use the
video verifier's current CLI contract from `--help`; do not guess its arguments.

## Baseline runtime-qualification checkpoint

- Private source commit:
  `f433d11d713e3fcd979edb21cbbdb9a57541b1f6`
- Sanitized candidate commit:
  `65a0bb9d52abbdf430ea46cee7c4ed0f7884ccf3`
- Matching source and candidate tree:
  `2b0b82c2645d90c3f326a0ac3d1eeefb35fdf97c`
- Public baseline observed on 2026-07-15:
  `916ab51f1bbf86fda7e1a84c93a4576627ab8da1`
- Runtime evidence: 215 frontend packages installed with zero reported
  vulnerabilities; 17 focused BalanceDocket tests, 32 frontend tests, and 344
  full Python tests passed; production build and checked-bundle parity passed.
- Python-only judge clone: no `node_modules`; root HTTP 200; synthetic-only and
  zero-ERP-write health contract passed; hostile Host and cross-site POST probes
  returned HTTP 403.
- Video: the 172.005167-second captioned picture lock passed strict decode,
  black-frame, and visual checks but intentionally has no audio. Yurii's eight
  narration takes are still required.

This is the retained baseline checkpoint, not a permanent `HEAD` or latest-run
claim. Current release qualification is recorded in the local release proof.
Every prompt must resolve the live commits and trees with `git rev-parse HEAD`
and `git rev-parse HEAD^{tree}` and must identify later documentation-only
changes separately from runtime qualification.

## Five-stage professional sequence

### Stage 1 — release engineering audit

Run after any material code, release-package, browser-draft, or media change.

> Read and apply `docs/codex_feedback_brief.md`, especially Review operating
> contract, Evidence anchors, Canonical verification commands, and Exact
> action-time approvals. Act as the senior release engineer for BalanceDocket's OpenAI Build Week 2026
> candidate. Audit the exact current repository and external state. Do not rely
> on earlier summaries where live evidence is available. This audit is
> read-only except for writing its report; do not change source, release
> artifacts, media, browser drafts, or external systems.
>
> Apply this source precedence: official rules govern eligibility; directly
> observed repository, browser, remote, and media state governs current status;
> fresh verifier output governs technical claims; project documentation explains
> intent but cannot self-verify. Report every conflict explicitly.
>
> Begin with the required state header. Then verify the Work & Productivity fit,
> pre-existing-work boundary, material Codex and GPT-5.6 use, deterministic
> accounting calculations, citation and snapshot binding, human decision
> authority, synthetic-only and no-ERP-write guarantees, accessibility,
> security, clean-clone installation, production build and bundle parity,
> Python-only no-rebuild judge launch, reachable-history secret scanning, video
> duration, narration, captions, audio delivery, and every Devpost requirement.
>
> After the state header, present findings ordered P0 to P2. Follow with the
> six-column evidence
> matrix using only `verified`, `contradicted`, `incomplete`, `missing`, or
> `unverified`. Record exact commits, tree hashes, commands, test counts,
> artifact hashes, URLs, observation times, and unresolved external actions.
> Include the engineering decision table for material tradeoffs. Any P0 or
> unverified mandatory requirement blocks an eligibility-ready conclusion.
> Distinguish local readiness from public readiness and end with the smallest
> next action. Follow the required response schema and terminal gate-result
> vocabulary exactly.

### Stage 2 — pre-feedback readiness handoff

Run only when the release audit has no unresolved technical P0 and before asking
Yurii to authorize `/feedback`.

> Read and apply `docs/codex_feedback_brief.md`, especially Review operating
> contract, Evidence anchors, Canonical verification commands, and Exact
> action-time approvals. Produce a pre-feedback readiness handoff for
> BalanceDocket. Re-resolve the
> live source, candidate, public remote, media, and authenticated Devpost draft.
> Confirm whether every technical and privacy prerequisite for the primary-task
> `/feedback` capture is directly verified.
>
> Begin with the state header and findings. Confirm that this is the primary task
> where the majority of core work occurred; the readable task projection passed
> secret scanning; no credentials, tokens, client data, private source history,
> or advisory-run identifier are intended for publication; and the advisory
> provider run ID will not be confused with the `/feedback` Session ID. Treat
> encrypted-content handling as an owner-approved upload decision, not as public
> proof.
>
> Provide: (1) the evidence matrix, (2) the engineering decision record, (3) the
> exact remaining public-release and media gates, and (4) a short action-time
> approval block. Do not run `/feedback`. If any mandatory item is missing or
> unverified, stop and name the smallest next action. Follow the required
> response schema and terminal gate-result vocabulary exactly.

### Stage 3 — approved `/feedback` capture

This stage is a paste-ready action prompt. Use it only after the exact approval
phrase in the approval table has been recorded in the primary task.

> Read and apply `docs/codex_feedback_brief.md`, especially Review operating
> contract, Evidence anchors, Canonical verification commands, and Exact
> action-time approvals. Perform the approved `/feedback` capture for
> BalanceDocket in this same primary
> task. First verify that Yurii's exact action-time approval is present, this is
> the task where the majority of core work occurred, and the pre-feedback
> readiness handoff has no unresolved privacy or technical P0. If any precondition
> fails, perform no mutation and return the required schema ending in `BLOCKED`.
>
> If every precondition passes, the only permitted mutations are: run `/feedback`
> for this primary task, copy the returned Session ID into the private Devpost
> `/feedback` field, save that field, reload Additional info, and verify that a
> non-empty value persisted. Do not place the raw Session ID in the response,
> repository, video, screenshot, log, or any public field. Do not use the advisory
> provider run ID or create a replacement task.
>
> Report whether the command returned a Session ID, whether the private field was
> saved, and whether persistence was directly verified, without reproducing the
> value. Record the exact authorized mutations performed and any failure. Follow
> the required response schema. A completed private capture may end in `LOCALLY READY`;
> it does not establish public readiness or authorize any later action.

### Stage 4 — public evidence reconciliation

Run only after the approved candidate, narrated public video, approved project
images, and required `/feedback` capture exist.

> Read and apply `docs/codex_feedback_brief.md`, especially Review operating
> contract, Evidence anchors, Canonical verification commands, and Exact
> action-time approvals. Reconcile BalanceDocket's public competition evidence
> end to end. Re-read the
> current official Build Week rules and the authenticated Devpost draft. Begin
> with the required state header and use the defined source precedence and
> status vocabulary.
>
> Confirm that the public GitHub HEAD exactly matches the approved
> publication-ready commit and that its tree exactly matches the approved
> sanitized candidate tree; the public reachable history passes secret
> scanning; the README exposes the free no-rebuild judge path and accurately
> explains Codex, GPT-5.6, and pre-existing work; and the public YouTube video is
> under three minutes, audible, English-captioned, and viewable while signed out
> on desktop and mobile. Verify every Devpost field by exact saved value. This
> reconciliation is read-only by default. If a separately recorded approval
> authorizes specific field edits, limit mutation to the named field allowlist,
> record before and after values plus the save result, reload, and verify
> persistence. Keep authenticated draft checks separate from signed-out public
> checks.
>
> Verify that the demo shows the working product and explains how Codex
> accelerated engineering and how GPT-5.6 performs the bounded advisory role.
> Preserve the disclosure that Codex requested `gpt-5.6-sol` while the retained
> CLI did not independently report returned-model identity. Confirm that no
> private source history, credential, token, client data, Session ID, or
> advisory-run identifier is public. Report every discrepancy as a blocker.
> Produce the evidence matrix and engineering decision record. Do not accept
> terms or perform the final Devpost submission. Follow the required response
> schema and terminal gate-result vocabulary exactly.

### Stage 5 — final owner sign-off

Run after public reconciliation passes and immediately before Yurii's manual
review of the final submission screen.

> Read and apply `docs/codex_feedback_brief.md`, especially Review operating
> contract, Evidence anchors, Canonical verification commands, and Exact
> action-time approvals. Produce the final evidence-based engineering handoff
> for BalanceDocket. After
> the required state header, begin findings with any remaining blocker; if none
> exists, state exactly what was verified, where, and when. Summarize the problem,
> architecture, deterministic-versus-model boundary, Codex workflow, GPT-5.6 role, human
> authority, security posture, accessibility evidence, tests, public release
> commit and tree, judge path, video verification, and persisted Devpost draft
> state.
>
> Record Yurii Bakurov as entrant, product owner, and final decision-maker.
> State honestly that Codex accelerated analysis, implementation, testing, UI
> iteration, release hardening, and submission preparation under human
> supervision. Preserve the pre-existing-work disclosure and returned-model
> caveat. Use the evidence matrix and engineering decision record, then end with
> a concise owner-review checklist. Stop before terms acceptance and final
> Devpost submission. Follow the required response schema and terminal gate-result
> vocabulary exactly.

## Exact action-time approvals

Each phrase is one-shot and authorizes only its named action. Record the target
account, repository, commit, file set, or form before acting. A later action needs
its own approval.

| Action | Exact approval phrase | Permitted scope | Explicit exclusions |
| --- | --- | --- | --- |
| Primary-task feedback | `Approve /feedback upload for this primary thread.` | Run `/feedback`, store the returned Session ID only in the private Devpost field, save, and verify persistence. | No public disclosure and no replacement task. |
| Devpost images | `Approve the four Devpost project-image uploads.` | Upload the prepared project thumbnail plus the three named gallery images; save and verify persistence. | No video upload, terms acceptance, or final submission. |
| Public repository | `Approve publishing BalanceDocket release commit <PUBLICATION_COMMIT> to Yurii201811/closeproof main.` | Push only the stated reviewed publication commit to the stated branch, then verify the remote. | No force push, tag, release, or unrelated repository changes. |
| Public video and captions | `Approve uploading the verified BalanceDocket video, thumbnail, and English captions to YouTube as public.` | Upload only the named final video, thumbnail, and caption file as public; verify signed-out playback. | No visibility change for any other video and no Devpost submission. |
| Devpost field correction | `Approve these Devpost field edits only: <FIELD ALLOWLIST>.` | Change only the listed fields, save, reload, and report before and after values. | No other draft edits, uploads, terms acceptance, or submission. |
| Devpost terms | `Approve accepting the displayed Devpost terms for BalanceDocket.` | Accept only the currently displayed competition terms after recording their identity and observation time. | No final submission. |
| Final submission | `Approve final Devpost submission for BalanceDocket submission 1085175.` | Click the final submit control once after the owner-review evidence is current. | No post-submit edits or other external actions. |

The optional-credit request is no longer actionable: its July 17 deadline has
passed and the official event update says the available credits were
distributed. Credits are not an eligibility requirement.

## Feedback capture guardrails

- The readable task projection passed secret scanning; encrypted-content
  handling remains an owner-approved upload decision.
- Do not use the advisory provider run ID as the `/feedback` Session ID.
- Do not expose the `/feedback` Session ID in the video or public repository.
- Do not claim Codex CLI independently reported the returned model identity.
  The retained run requested `gpt-5.6-sol`; structured output and invariants
  were validated; Codex CLI `0.144.0` reported no returned model identity.
- Do not use the manual ChatGPT-import state as competition model proof.
- Do not claim production deployment, measured customer impact, autonomous
  accounting, or universally free subscription-backed access.
- Keep public-release, terms-acceptance, and final-submit authority with Yurii.
