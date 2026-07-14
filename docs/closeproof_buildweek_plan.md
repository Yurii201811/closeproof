# CloseProof Build Week execution plan

## Critical path

`requirements → visual contract → isolated worktree → deterministic local controls → subscription-first GPT-5.6 boundary → reviewer UI → QA → real Codex demo proof → submission`

## Gates

| Gate | Required evidence |
|---|---|
| G0 Eligibility | Rules matrix, selected track, clean base hash, pre-existing capability boundary |
| G1 Design lock | `PRODUCT.md`, `DESIGN.md`, accepted desktop and mobile concepts |
| G2 Vertical slice | Fresh synthetic case to reviewed workpaper with no model, network, API, or manual data repair |
| G3 Model validity | Existing Codex sign-in requests `gpt-5.6-sol`; the structured advisory materially interprets the ambiguous case and passes fail-closed validation. Returned model identity is disclosed as unreported; manual ChatGPT import and explicitly opted-in Responses API remain secondary routes |
| G4 Release candidate | Full checks green; no secret, real data, unsafe write, broken golden path, or uncited conclusion |
| G5 Submission | Clean-clone proof, public repo, under-three-minute public video with audio, validated Codex request provenance with the returned-identity limitation disclosed, primary-task `/feedback` ID, checked Devpost links |

## Schedule in Europe/Stockholm

- July 13: rules, idea verification, isolated branch, product/design lock.
- July 14-16: deterministic case engine, plugin workflow, server, vertical slice.
- July 17: Codex subscription path, manual import fallback, optional API route,
  and shared fail-closed evaluation.
- July 18: accepted UI, responsive states, accessibility pass.
- July 19: feature freeze, security and regression hardening.
- July 20: README, demo script, recording rehearsal, release candidate.
- July 21 by 18:00: target submission, eight hours before the hard deadline.
- July 22 at 02:00: absolute deadline; emergency link fixes only.

## Cut order if schedule slips

Cut decorative animation, extra dashboards, persistence beyond the event log,
drag-and-drop, additional invoice variants, and deployment automation in that
order. Never cut the source citation, deterministic calculation, validated
Codex advisory step, human decision, workpaper export, safety boundary, or reproducible
setup. The Responses API route may be cut before the subscription-first Codex
path because it is optional.

## Advisory command contract

The CLI surface is:

```bash
python3 -m accounting_agent.cli closeproof-advisory status
python3 -m accounting_agent.cli closeproof-advisory prepare
python3 -m accounting_agent.cli closeproof-advisory import
python3 -m accounting_agent.cli closeproof-advisory codex \
  --confirm-use-codex-allowance
python3 -m accounting_agent.cli closeproof-advisory api \
  --enable-network-advisory
```

- `status` is read-only and makes no advisory request.
- `prepare` writes the bounded prompt and strict response contract to
  `.local/closeproof-demo/advisory-request.json` by default.
- `codex` uses the existing Codex sign-in and eligible ChatGPT plan allowance;
  it requests the concrete Codex catalog ID `gpt-5.6-sol` and does not require a
  separate API credential or API billing account.
- `import` validates `.local/closeproof-demo/advisory-output.json` by default,
  including structured JSON produced through the manual ChatGPT fallback.
- Every completed route discards provider-authored prose before persistence.
  Only validated citations, uncertainty, invariant amounts, and the presence of
  missing evidence survive into a locally generated controlled-language display.
- `api` is disabled by default and requires explicit opt-in plus
  `OPENAI_API_KEY`. A direct ChatGPT subscription is not an API credential.

Do not call subscription use universally free. Access, allowances, and rate
limits depend on the operator's plan.

## Verification matrix

- Python unit tests for PDF parsing, money allocation, controls, case snapshot,
  advisory validation, decision validation, event-chain integrity, and export.
- React component tests for stage order, statuses, proof content, validation, and
  decision state.
- Production frontend build and Python package checks.
- Browser checks at 1440x900, 1280x800, 768x1024, 390x844, and 320x800.
- Keyboard-only and reduced-motion flows.
- Axe critical/serious target: zero on primary, loading, error, and decided states.
- No unexpected external requests in the default demo.
- Route checks: local-only, Codex unavailable/running/validated, manual import
  awaiting/invalid/validated, and API disabled/missing-key/running/validated.
- The default case contains no fixture advisory and starts `not_requested`;
  fixture or simulated content is never labeled live or validated model output.
- Real competition proof records the concrete `gpt-5.6-sol` request provenance
  from Codex; the API-only `gpt-5.6` alias is documented separately.
- Secret scan and synthetic-data audit.
- Full repository `unittest` regression.

## Submission artifact checklist

- Public repository and license.
- README with prerequisites, exact setup, test, run, subscription-first Codex,
  manual import, optional API, and demo commands.
- Architecture and deterministic-versus-model boundary.
- Synthetic fixture declaration and safety limitations.
- Codex acceleration and key decision notes.
- Primary Codex `/feedback` session ID plus a real Codex run requesting
  `gpt-5.6-sol`, validated structured output, and an explicit disclosure when
  the transport does not report returned model identity.
- Public YouTube demo under three minutes with audible narration.
- Devpost Work & Productivity selection and verified links.
