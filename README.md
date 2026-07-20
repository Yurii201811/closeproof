# BalanceDocket

BalanceDocket is an evidence-bound month-end close reviewer for controllers and
senior accountants. Rules calculate the exact treatment, GPT-5.6 performs the
citation-bound interpretation in the judged flow, and the accountable human
decides—all in one inspectable trail. If model access is unavailable, the same
case fails safely to deterministic human review rather than blocking the free
judge path.

This is the repository's **OpenAI Build Week 2026 · Work & Productivity**
project. It is built on selected pre-existing Accounting Agent primitives; the
[Build Week provenance](docs/build_week_provenance.md) records that boundary.

> **Compatibility note:** BalanceDocket is the approved public display name.
> The released product deliberately retains the stable `closeproof` technical
> namespace for CLI commands, environment variables, schemas, plugin IDs,
> source paths, and the public repository URL. Those identifiers remain
> unchanged so the tested judge path and evidence hashes do not break.

## Judge quick start

Prerequisite: Python 3.11+. From a fresh clone, one command generates the
synthetic case and serves the checked-in competition bundle on loopback. It
does not need Node.js, npm, an OpenAI account, a model, or a rebuild:

```bash
git clone https://github.com/Yurii201811/closeproof.git
cd closeproof
./scripts/run_closeproof_prebuilt.sh
```

To rebuild the reviewer from source first, install Node.js 20.19+ or 22.12+ and
npm, then run:

```bash
./scripts/run_closeproof_demo.sh
```

Open <http://127.0.0.1:4173>. Set `CLOSEPROOF_PORT=4187` if the default port is
occupied. The script never contacts an accounting, bank, email, tax, payment,
or filing system. Alternate ports use a port-scoped ignored output directory by
default, so starting a second demo cannot reset the first demo's decisions:

```bash
CLOSEPROOF_PORT=4187 ./scripts/run_closeproof_prebuilt.sh
```

The default run stores state in `.local/closeproof-demo`; a non-default port
stores it in `.local/closeproof-demo-$CLOSEPROOF_PORT` (for example,
`.local/closeproof-demo-4187`). The launcher prints the resolved state directory
and advisory case path. `CLOSEPROOF_OUTPUT` may be used to choose a different
dedicated directory explicitly.

### Install the optional Codex plugin

The local reviewer works without a plugin or an OpenAI account. To add the
BalanceDocket workflow to a plugin-capable Codex installation from this clone:

```bash
codex plugin marketplace add .
codex plugin add closeproof@personal
```

Start a new Codex task so the installed skill is discovered, then invoke
`$closeproof`. The plugin orchestrates the same local scripts and may optionally
use the operator's existing Codex sign-in for the bounded advisory step.

### Supported and tested platforms

- Supported runtime: macOS or Linux with Bash and Python 3.11+. The source-build
  route additionally needs a Vite-compatible Node.js release and npm.
- Verified on July 14, 2026: macOS 27.0 arm64, Python 3.11.5, Node.js 25.4.0,
  npm 11.7.0, Codex CLI 0.144.0, Chromium through the in-app Browser flow,
  Playwright Firefox/WebKit desktop and 320×800 reduced-motion smoke runs, and
  native Safari keyboard, VoiceOver, and maximum-zoom checks.
- Native Windows is not supported because the local event log uses POSIX file
  locking. Linux and WSL remain unverified release surfaces. Safari verification
  is limited to the macOS version above rather than a broad version-support
  claim.

## What the demo proves

The golden path takes a bundled synthetic GL CSV and a deterministically
generated text PDF through duplicate, cutoff, and prepaid controls; shows one
ambiguous Adjustments exception; adds a citation-bound GPT-5.6 interpretation
through Codex in the competition flow; requires a human
approve/request-evidence/reject decision; and exports a hash-bound workpaper.
The no-model fallback preserves the deterministic review but does not replace
GPT-5.6's material competition role. Neither path performs an ERP write or
accounting action.

### Run the deterministic demo manually

Prerequisites: Python 3.11+, Node.js 20.19+ or 22.12+, and npm.

```bash
python3 -m accounting_agent.cli closeproof-demo
npm --prefix apps/closeproof-web ci
npm --prefix apps/closeproof-web run build
python3 -m accounting_agent.cli closeproof-serve
```

Open <http://127.0.0.1:4173>. If that port is occupied, pass another loopback
port, for example `--port 4187`.

The default path is deterministic, model-free, API-free, and network-off. It
does not require an OpenAI account. It writes only ignored local artifacts under
`.local/closeproof-demo`:

- `case.json` — evidence-bound reviewer state;
- `invoice_INV-4821.pdf` — generated synthetic text PDF;
- `manifest.json` — inputs, outputs, snapshot, and zero-call counters;
- `decision-events.jsonl` and its chain head — created only after a human action.

The exact control result is SEK 5,260.27 June expense and SEK 114,739.73 prepaid
asset from 16 of 365 inclusive service days. The generated case starts with the
advisory `not_requested`; it contains no fixture or simulated model response.

### Add GPT-5.6 advice with your existing Codex sign-in

The primary competition path uses Codex signed in through ChatGPT and the
GPT-5.6 access included with the operator's eligible plan allowance. It does not
need a separate API key or API billing account. Plan availability, rate limits,
and usage terms still apply; subscription-backed use is not universally free.

The advisory commands are:

```bash
python3 -m accounting_agent.cli closeproof-advisory status
python3 -m accounting_agent.cli closeproof-advisory prepare
python3 -m accounting_agent.cli closeproof-advisory import
python3 -m accounting_agent.cli closeproof-advisory codex \
  --confirm-use-codex-allowance
python3 -m accounting_agent.cli closeproof-advisory api \
  --enable-network-advisory
```

Those defaults target the port-4173 state in `.local/closeproof-demo`. For a
demo started on another port, pass its port-scoped case and keep the prepared
request/manual response in that same state directory. For example, after
starting with `CLOSEPROOF_PORT=4187`:

```bash
state_dir=.local/closeproof-demo-4187
case_path="$state_dir/case.json"

python3 -m accounting_agent.cli closeproof-advisory status \
  --case "$case_path"
python3 -m accounting_agent.cli closeproof-advisory prepare \
  --case "$case_path" \
  --output "$state_dir/advisory-request.json"
python3 -m accounting_agent.cli closeproof-advisory import \
  --case "$case_path" \
  --input "$state_dir/advisory-output.json"
python3 -m accounting_agent.cli closeproof-advisory codex \
  --case "$case_path" \
  --confirm-use-codex-allowance
python3 -m accounting_agent.cli closeproof-advisory api \
  --case "$case_path" \
  --enable-network-advisory
```

- `status` reports the current provider/provenance advisory envelope without
  making an advisory request.
- `prepare` writes the citation-bounded prompt, evidence packet, and response
  schema to `.local/closeproof-demo/advisory-request.json` by default.
- `codex` is the judged path: use the existing Codex sign-in, request the
  concrete Codex catalog model `gpt-5.6-sol`, validate the structured result,
  and retain its provenance. The optional Responses API route uses the
  `gpt-5.6` API alias, which OpenAI maps to GPT-5.6 Sol; BalanceDocket does not
  silently substitute between provider identifiers.
- `import` validates a structured result produced from the prepared prompt. For
  the manual fallback, paste the prompt into ChatGPT, choose GPT-5.6, save only
  the requested JSON to `.local/closeproof-demo/advisory-output.json`, and import it.
  A ChatGPT subscription is an interactive product entitlement, not an API
  credential.
- `api` is an optional Responses API route. It must require explicit opt-in and
  `OPENAI_API_KEY` supplied through an approved secret mechanism. BalanceDocket
  must never print or persist the key.

All advisory routes may send or expose only the bundled synthetic source
excerpts and deterministic amounts. Validation rejects unknown citations,
changed amounts, malformed output, or a false `cannot_approve` invariant.
Provider-authored prose is never persisted or rendered: BalanceDocket retains only
the validated citations, uncertainty, exact amounts, and whether evidence was
flagged, then generates controlled display language locally. Codex and API
results must also pass the available model/provenance checks. A manual
ChatGPT import remains labeled `Unverified model identity` unless its identity
can be independently established. If advisory generation is unavailable, the
local case remains reviewable and exportable with the advisory marked not
requested or unavailable.

The Build Week recording must show a real Codex run requesting `gpt-5.6-sol`
whose structured output passes BalanceDocket validation. Codex CLI `0.144.0` did
not report the returned model identity in the retained run, so the repository
does not claim that identity was independently verified. A fixture advisory,
manual text pasted without validated provenance, or API-shaped mock response is
not acceptable as competition proof. Run `/feedback` in the primary Codex task
and retain the returned session ID for the submission.

### Verify BalanceDocket

```bash
./scripts/verify_closeproof.sh
```

Or run the layers separately:

```bash
python3 -m unittest tests.test_closeproof
npm --prefix apps/closeproof-web test
npm --prefix apps/closeproof-web run build
python3 -m unittest discover
```

See [PRODUCT.md](PRODUCT.md), [DESIGN.md](DESIGN.md), the
[Build Week plan](docs/closeproof_buildweek_plan.md), the
[problem validation](docs/problem_validation.md), the
[provenance record](docs/build_week_provenance.md), the
[demo script](docs/closeproof_demo_script.md), and the
[submission checklist](docs/closeproof_submission_checklist.md). Draft Devpost
copy and remaining placeholders live in
[docs/devpost_submission.md](docs/devpost_submission.md).

## How Codex and GPT-5.6 contributed

Codex accelerated the Build Week work end to end: competition and practitioner
research, repository mapping, product architecture, Python and React
implementation, UI mockup iteration, browser checks, accessibility tests,
security review, and plugin/release packaging. The human entrant selected the
Work & Productivity track and controller persona, chose the evidence-first
exception-review wedge, required the local/API-free default, kept calculations
deterministic, prohibited ERP writes and model approval authority, and accepted
the final product direction.

GPT-5.6 has a deliberately material but bounded role: interpret the ambiguous
synthetic service-period exception, cite only the supplied evidence, preserve
the exact deterministic amounts, state uncertainty, and flag missing evidence.
BalanceDocket discards its prose and renders those validated selections through
local controlled-language templates for human review. A retained Codex CLI run
requested `gpt-5.6-sol` and its output passed BalanceDocket validation; Codex CLI
0.144.0 did not report the
returned model identity, so this repository does not claim independent model
attestation. The [Build Week provenance](docs/build_week_provenance.md) records
the detailed timeline, inherited-code boundary, acceleration, and human/model
decision split.

## Inherited Accounting Agent foundation

The broader repository is a Sweden-first, provider-neutral accounting
automation foundation for safe local proposals, exception review,
reconciliation, and evidence packaging. BalanceDocket deliberately uses only the
bounded primitives documented in the provenance record.

The functional runtime still uses synthetic local fixtures. It extracts invoice
fields, isolates duplicates by client, checks supplier and VAT risk, proposes
BAS/VAT treatment, prepares bank-reconciliation proposals, writes human review
packets, and records local evidence. It does not process real client data or
post, approve, send, pay, delete, change ERP settings, file tax, or call a live
provider.

Version 1 adds explicit legal-entity journals, evidence-bound approvals,
dependency-aware close readiness, resumable preparation agents, guarded ERP
read contracts, provider-neutral advisory-model routing, and a bilingual
Guided/Expert cockpit. International support is a schema and jurisdiction-pack
foundation, not a blanket compliance claim. Live provider writes remain
forbidden.

Inspect that machine-readable boundary:

```bash
python3 -m accounting_agent.cli platform-status
python3 -m accounting_agent.cli platform-status --json
python3 -m accounting_agent.cli v1-system-check --json
```

Run the complete local demo:

```bash
python3 -m accounting_agent.cli demo-supplier-invoice-autopilot
```

The demo writes normalized intake cases, extracted invoice JSON, accounting
proposals, risk findings, policy decisions, execution permits where applicable,
approval packets, Fortnox dry-run payloads, gnubok shadow output, and an audit
log to `.local/demo_supplier_invoice_autopilot`.

Run the full fake-client month dry run:

```bash
python3 -m accounting_agent.cli fake-client-dry-run
```

The fake-client run generates a synthetic Swedish consulting/service business
month, runs supplier invoice autopilot and bank reconciliation locally, writes
outputs to `.local/fake_client_dry_run`, and writes
`docs/fake_client_dry_run_report.md`. It uses no real client data and no live
external APIs.

Build the read-only local operations cockpit:

```bash
python3 -m accounting_agent.cli build-operations-cockpit
```

The cockpit writes `reports/operations_cockpit/index.html`. It is a local,
read-only Workbench generated from repo artifacts. Guided mode gives accountants
one clear next decision; Expert mode exposes policy, provider, specialist-agent,
and evidence detail. The main interface, review reasons, filters, workflow,
provider matrix, and dates switch between English and Swedish. The selected
guidance perspective changes explanatory emphasis only; risk priority and
safety policy remain fixed. It has no CDN or live-provider dependency and
remains observe/review only.

Build the separate deployable preview from built-in synthetic examples only:

```bash
python3 -m accounting_agent.cli build-public-preview \
  --output .local/accounting-agent-v1-preview
```

The public builder never reads local workflow artifacts and refuses unexpected
files in its target directory.

Private course references, if present, stay under `.local/course_reference/`
and are excluded from Git. They can inform topic coverage and plain-language
explanations, but current official law, BFN, Skatteverket, BAS, and SIE sources
remain authoritative.

Run the lower-level sample pipeline:

```bash
python3 -m accounting_agent.cli process-fixtures
```

Run tests:

```bash
python3 -m unittest
```

Fixture commands use an explicit 2026-05-16 evaluation date by default so risk
outcomes do not change with the wall clock. Pass `--as-of YYYY-MM-DD` to the
supplier fixture or demo command when testing a different review date.

## License

BalanceDocket is available under the [MIT License](LICENSE). Copyright © 2026
Yurii Bakurov. Runtime open-source components and their license texts are
listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Pre-existing and open-source components

BalanceDocket meaningfully extends selected primitives from a pre-existing
Accounting Agent foundation. Only the dedicated BalanceDocket case, controls,
snapshot and citation contract, bounded GPT-5.6 evaluator, human decision
chain, React reviewer, Codex plugin, workpaper export, tests, and release
material added during the Build Week submission period are presented as the
competition contribution. The dated boundary and file-level evidence are in
[the Build Week provenance record](docs/build_week_provenance.md).

The reviewer uses React, React DOM, Scheduler, and Lucide React under their
respective open-source licenses. Exact runtime versions, upstream projects,
copyright notices, and license texts are recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); the npm lockfile retains the
complete dependency graph.

Start with `docs/accounting_agent_v1.md` for the product, jurisdiction, ERP,
model, autonomy, computer-use, and release boundary. See
`docs/local_model_evaluation.md` for the local Ollama comparison,
`docs/v1_research_decisions.md` for the problem-to-product decisions,
`docs/local_demo_supplier_invoice_autopilot.md` for the one-command local demo,
`docs/mvp_supplier_invoice_autopilot.md` for the packet schema, and
`docs/operations_cockpit.md` for the interface workflow.
