# BalanceDocket Build Week provenance

This document separates the Accounting Agent foundation that existed before
OpenAI Build Week from the BalanceDocket work added during the competition. It is
intended to accompany the private source history, not replace it. The existing
sanitized public repository begins with a new root commit, so the private
provenance hashes and diff command below are evidence references rather than
commits expected to resolve there. BalanceDocket is still a local release
candidate and its proposed display-name migration has not yet been published.

## Competition window and source of truth

- Official submission period: July 13, 2026 at 09:00 PT through July 21, 2026
  at 17:00 PT.
- BalanceDocket work period: July 13-21, 2026.
- Track: **Work & Productivity**.
- Official requirements: [Build Week overview](https://openai.devpost.com/) and
  [Official Rules](https://openai.devpost.com/rules).
- Pre-existing baseline:
  `aed4507d0c59eeda1ec9ccfbdeffd8fb8c550522`, committed July 11, 2026 at
  01:18:43 Europe/Stockholm with subject
  `release: ship Accounting Agent v1 foundation`.
- First feature checkpoint, then using the CloseProof working name:
  `58e2f28681c07a120abe8b1c60d22db923aa7315`, committed July 14, 2026 at
  10:18:53 Europe/Stockholm with subject
  `feat: add CloseProof evidence-led close review`.

Development began under the CloseProof working name. BalanceDocket is the later
proposed display-only name; the historical commit subject remains unchanged as
an exact provenance record.

The rules state that a pre-existing project is judged only on meaningful work
added after the submission period began. In the retained private source
history, the authoritative code boundary is:

```bash
git diff --name-status \
  aed4507d0c59eeda1ec9ccfbdeffd8fb8c550522..HEAD
```

## What existed before Build Week

The July 11 baseline was the broader Accounting Agent project. It already
provided:

- synthetic local accounting fixtures and evidence packaging;
- supplier-invoice and bank-reconciliation proposal workflows;
- reusable evidence records and source hashes;
- dependency-aware close-readiness primitives;
- provider-neutral advisory-model routing foundations;
- guarded, read-only provider contracts and Fortnox dry-run artifacts;
- a bilingual Guided/Expert operations cockpit; and
- the safety boundary that forbids live posting, approval, payment, filing,
  communication, deletion, and provider-setting changes.

Those inherited capabilities remain useful infrastructure, but they are not
presented as new Build Week work.

## What was added during Build Week

BalanceDocket is the new, focused controller workflow built on top of that
foundation:

| New work | Repository evidence |
|---|---|
| A dedicated Nordix Services AB June 2026 golden case using only synthetic GL, invoice, and policy inputs | `fixtures/closeproof/` |
| Deterministic invoice generation/parsing and exact duplicate, cutoff, and prepaid calculations | `accounting_agent/closeproof/pdf.py`, `accounting_agent/closeproof/case.py` |
| A BalanceDocket evidence snapshot that binds source hashes, citations, exact integer-ore amounts, and review context | `accounting_agent/closeproof/case.py`, `accounting_agent/closeproof/integrity.py` |
| The inherited nine-stage dependency model bound into one concrete close-review case and exposed through a loopback service | `accounting_agent/closeproof/server.py` |
| An optional, bounded GPT-5.6 advisory path through Codex, manual ChatGPT import, or an explicitly opted-in Responses API route | `accounting_agent/closeproof/advisory.py`, `accounting_agent/cli.py` |
| Fail-closed checks for schema, citations, amounts, snapshot, provider provenance, and the no-authority invariant; provider prose is discarded and replaced by locally generated controlled display language | `accounting_agent/closeproof/advisory.py` |
| Human approve/request-evidence/reject actions with required rationale and a BalanceDocket-specific append-only hash chain | `accounting_agent/closeproof/decisions.py` |
| Evidence-bound JSON workpaper export that reports zero accounting actions and zero ERP writes | `accounting_agent/closeproof/server.py` |
| A responsive React evidence-ledger workbench with keyboard-accessible review states | `apps/closeproof-web/` |
| A Codex plugin skill that guides the same bounded workflow | `plugins/closeproof/` |
| Dedicated Python, integrity, frontend, accessibility, build, and regression checks | `tests/test_closeproof.py`, `tests/test_closeproof_integrity.py`, `apps/closeproof-web/src/App.test.tsx`, `scripts/verify_closeproof.sh` |
| Product, design, demo, safety, and submission documentation | `PRODUCT.md`, `DESIGN.md`, `docs/closeproof_*` |

BalanceDocket does not claim the inherited Accounting Agent platform was created
during Build Week. The competition contribution is the new end-to-end,
evidence-bound month-end exception workflow and its dedicated product surface,
model boundary, decision record, export, plugin, and verification suite.

## How Codex contributed

Codex was used throughout the Build Week period as an engineering collaborator:

1. It researched the live competition requirements and tested the idea against
   the Work & Productivity definition and four judging criteria.
2. It inspected the existing Accounting Agent repository, identified reusable
   primitives, and preserved the no-write and synthetic-only boundaries.
3. It helped plan the product contract, architecture, desktop/mobile visual
   direction, model boundary, failure states, and release gates.
4. It implemented and revised the Python workflow, loopback service, React
   workbench, plugin, tests, and documentation under human direction.
5. It exercised unit, integration, frontend, accessibility, build, browser,
   clean-clone, secret, and regression checks, then used findings to harden the
   product.

Timestamped competition-period commits and private task evidence document this
collaboration. Raw authenticated provider/task identifiers are retained
privately and deliberately excluded from public documentation. The required
`/feedback` session ID must be recorded separately before submission and should
only be placed where the competition requires it.

## Human product and technical decisions

The human entrant retained decision authority and made the consequential
choices, including:

- selecting **Work & Productivity** and a controller/senior-accountant persona;
- narrowing the product to one month-end close exception instead of a generic
  autonomous accountant;
- making source evidence the primary interface rather than a chatbot or KPI
  dashboard;
- keeping dates, arithmetic, hashes, and dependencies deterministic;
- limiting GPT-5.6 to an optional, cited interpretation that cannot approve,
  post, lock, pay, file, send, or mutate source data;
- requiring a human rationale and disposition before a decision is recorded;
- keeping the default path local, network-off, API-free, and usable without an
  OpenAI account;
- using only bundled synthetic evidence and performing no external accounting
  action or ERP write; and
- separating Codex/ChatGPT plan access from API access. A ChatGPT subscription
  is not an API credential, and the optional API route requires separate opt-in,
  credentials, billing, limits, and terms.

## Real advisory-run evidence

One authenticated Codex advisory run was retained on July 14, 2026. **Codex
requested `gpt-5.6-sol` and structured output was validated, but Codex CLI
`0.144.0` did not report returned model identity.** This is evidence of the
requested model, transport provenance, and validated structured result; it is
not an independent attestation of the service's returned model identity.

| Evidence | Value |
|---|---|
| Codex advisory run record | Retained privately; raw authenticated identifier excluded from the public repository |
| Requested model | `gpt-5.6-sol` |
| Transport | `codex_cli_chatgpt` |
| Codex CLI | `0.144.0` |
| Provider structured-result SHA-256 before controlled display | `73e139d091f9007556d72543a3cb0f526484953e6745d24d27a3bc0921db259e` |
| Persisted controlled-advisory SHA-256 | `c4f6a767bf4aeb54ddd5362fb8dcdaff56a8e7a19a290d78d220535c24fa2233` |
| Evidence snapshot SHA-256 | `fda76d0752396535f0e5eb2f7f7b8a3e374db2ea44ee5431ba7ea4a18e10243b` |
| Human-decision review context | `ecafb2cd52a3bb3443f1e805caaada5bd86cfbcf39f75597562d266ac23aeef8` |
| Human decision event SHA-256 | `0efe2256133ec08efae37019802c2ff8a30cee4d08f8891e8bc79caa157e20d9` |
| Validation result | Structured schema, citations, invariant amounts, controlled-language normalization, no-authority boundary, and snapshot binding passed |
| External accounting effects | Zero accounting actions and zero ERP writes |

The private advisory-run identifier is **not** the Build Week `/feedback`
session ID. Do not substitute one for the other.

## Public release boundary

The working repository's ancestry previously contained private machine and
workspace metadata. Removing that material from the current tree does not
remove it from Git history. Therefore the existing history must not be pushed
to a public remote.

After explicit human approval, the original CloseProof public baseline was
created from a sanitized tip-only archive, initialized with a new root commit,
and checked for secrets and private metadata. The complete verifier passed in
that exact export and in a clean clone after the lockfile install. An
unauthenticated API request, raw README/LICENSE requests, a credential-disabled
clone, and the no-rebuild judge path then passed after the visibility change.
Commit hashes elsewhere in this document describe the private build provenance;
they are not expected to exist in the sanitized public history.

Yurii approved the BalanceDocket display name and MIT publication. The
sanitized code release was published as
`c2778b9ffb294fae0383e41a04ae06114244e458`, including the hashed frontend
bundle, third-party notices, and disclosure files. A fresh unauthenticated clone
then passed the full verifier and Python-only no-rebuild judge flow. The private
source history itself was not pushed to the public remote.

## Submission evidence status

- `/feedback` session ID from the primary Codex task: **PROVIDED PRIVATELY IN
  DEVPOST**. The value is deliberately excluded from public documentation.
- Sanitized tip-only public repository and license:
  <https://github.com/Yurii201811/closeproof> · MIT. BalanceDocket code release
  `c2778b9ffb294fae0383e41a04ae06114244e458` was verified on 2026-07-20.
- Public YouTube demo URL under three minutes with audio:
  <https://youtu.be/lCoD5W-rCQs> · Public · 172 seconds · 1920×1080 · English
  subtitle track · eight chapters.
- Free no-rebuild judge path: `./scripts/run_closeproof_prebuilt.sh` using the
  checked-in `plugins/closeproof/assets/web/` bundle. A fresh public clone
  returned HTTP 200 and completed a synthetic Request evidence workflow with a
  valid one-event hash chain and zero external actions on 2026-07-20.
- Pre-rebrand public repository and judge-path verification without GitHub
  authentication: **PASSED 2026-07-14**.
- BalanceDocket code release, disclosure package, clean-clone, and no-rebuild
  verification: **PASSED 2026-07-20**. The fresh clone passed 17
  focused tests, 32 frontend tests, the production build and bundle-parity
  check, and 344 full repository tests after `npm ci` installed 215 packages
  with 0 vulnerabilities.
- Public video metadata, English subtitle publication, description chapters,
  and authenticated Devpost saved-link/preview verification: **PASSED
  2026-07-20**. Uninterrupted human headphone playback remains open.
- Final Devpost `Submitted` status: **PENDING PERSONAL RULES/TERMS
  CONFIRMATION**.
- Post-submission availability: keep the repository, video, and judge path
  public, free, and unrestricted through at least August 7, 2026.

The remaining account-bound gates are Yurii's personal eligibility and
Rules/Terms confirmation, final submission, and confirmation that Devpost shows
the project as `Submitted`.
