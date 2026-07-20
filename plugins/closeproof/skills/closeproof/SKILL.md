---
name: closeproof
description: "Use for the bundled synthetic month-end close review: generate evidence, run deterministic controls locally, optionally obtain bounded GPT-5.6 advice through Codex, manual ChatGPT import, or the Responses API, open the reviewer workbench, and export a human-reviewed workpaper."
---

# BalanceDocket

Guide a controller through a source-linked close exception while preserving the
boundary between evidence, deterministic controls, model advice, and human
authority.

## Safety gate

- Use only the bundled synthetic BalanceDocket fixture.
- Do not ingest real client documents or identifiers.
- Do not call ERP, bank, email, tax, payment, or filing systems.
- Never claim to approve, post, lock, file, pay, or communicate.
- Keep the default path model-free, API-free, and network-off.
- Before any model route, confirm that the prepared packet contains only the
  bundled synthetic evidence.
- Treat Codex/ChatGPT subscription access and API access as separate. A ChatGPT
  subscription is not an API credential, and subscription use is not
  universally free; plan availability, allowances, and rate limits apply.

## Workflow

1. From the repository root, either launch the no-rebuild judge path:

   `./scripts/run_closeproof_prebuilt.sh`

   or generate the case without starting the server:

   `python3 -m accounting_agent.cli closeproof-demo`

2. Inspect `.local/closeproof-demo/case.json` and report the snapshot SHA, close
   outcome, control results, exact allocation, and cited source IDs.
3. Inspect the current provider/provenance advisory envelope without requesting
   advice:

   `python3 -m accounting_agent.cli closeproof-advisory status`

4. Prepare the citation-bound prompt, evidence packet, and response schema:

   `python3 -m accounting_agent.cli closeproof-advisory prepare`

5. If GPT-5.6 advice is requested, choose exactly one route:

   - Primary competition route — use the operator's existing Codex sign-in and
     eligible ChatGPT plan allowance with the concrete `gpt-5.6-sol` Codex
     catalog model, with no separate API key or API billing:

     `python3 -m accounting_agent.cli closeproof-advisory codex --confirm-use-codex-allowance`

   - Manual fallback — paste the prepared prompt into ChatGPT, explicitly choose
     GPT-5.6, save only the requested structured JSON to the prepared response
     path, then validate and import it:

     `python3 -m accounting_agent.cli closeproof-advisory import`

   - Optional programmatic route — only after explicit API opt-in, supply
     `OPENAI_API_KEY` through an approved secret mechanism and run:

     `python3 -m accounting_agent.cli closeproof-advisory api --enable-network-advisory`

   Never print or inspect the key. All three routes must retain the deterministic
   case if generation or validation fails. Do not generate or display a fixture
   advisory as though it were model output; keep the state `not_requested`.
6. When reviewing source changes, install the locked frontend dependencies and
   rebuild the web app. The checked-in judge bundle does not require this step:

   `npm --prefix apps/closeproof-web ci && npm --prefix apps/closeproof-web run build`
7. Start the loopback reviewer with:

   `python3 -m accounting_agent.cli closeproof-serve`

8. In the workbench, require a human rationale before Approve treatment,
   Request evidence, or Reject. The action records an append-only hash-chained
   event; it does not perform an accounting or ERP action.
9. Export the JSON workpaper and verify its snapshot and event-chain status.

For the Build Week recording, use the `codex` route and show a real run
requesting `gpt-5.6-sol` whose structured output passes citation, amount,
authority, schema, and snapshot validation. Disclose when the Codex transport
does not report returned model identity; requested model is not independent
proof of returned identity. Also run `/feedback` in the primary Codex task and
preserve its session ID. A fixture advisory, unverified paste, or API-shaped
mock does not satisfy this competition proof.

## Required response shape

Lead with the close outcome and the one human decision required. Then separate:

- source evidence;
- deterministic control result;
- GPT-5.6 advisory and uncertainty;
- human action still required;
- local artifact paths and verification status.

Never merge these layers into one authoritative-sounding conclusion.
