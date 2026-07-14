# CloseProof demo script

Target: 2 minutes 45 seconds. Record the real product at 1440×900 with audible
narration and captions. Do not use generated mockups as product footage.

## 0:00–0:18 — The problem

“Month-end review often separates the ledger, invoice, policy, calculation, and
human sign-off across different files. CloseProof gives a controller one
evidence-bound path through the exception.”

Show the persistent safety strip and the full nine-stage ledger.

## 0:18–0:42 — Codex entry point and synthetic pack

Invoke `$closeproof` and run `closeproof-demo`. Show the zero external-call / zero
ERP-write counters, snapshot SHA, and generated synthetic invoice PDF.

“Codex orchestrates the workflow. The fixture is synthetic, and the default run
is fully local and deterministic. It needs no model, network, or API key.”

## 0:42–1:12 — Deterministic controls

Show duplicate identity verified, posting cutoff verified, and prepaid service
period requiring review. Open Adjustments.

“Rules own identity, dates, dependencies, and arithmetic. Here the service
period runs from June 15, 2026 through June 14, 2027. Sixteen of 365 service days
belong to June, producing exactly SEK 5,260.27 expense and SEK 114,739.73
prepaid.”

## 1:12–1:42 — Material Codex GPT-5.6 step

Briefly show the provider/provenance status, prepared bounded prompt, and the
real Codex route:

```bash
python3 -m accounting_agent.cli closeproof-advisory status
python3 -m accounting_agent.cli closeproof-advisory prepare
python3 -m accounting_agent.cli closeproof-advisory codex \
  --confirm-use-codex-allowance
```

“GPT-5.6 handles the bounded interpretive step: connect the invoice wording,
synthetic policy, and exact control result; select supporting citations; expose
uncertainty and missing evidence. CloseProof discards provider prose and renders
the validated selections locally. This run uses my existing Codex sign-in and
eligible ChatGPT plan allowance, not a separate API key. It cannot change the
calculation or approve.”

Show `Codex requested · Validated output`, citation chips, uncertainty, retained
run provenance, and `Advisory — cannot approve`. Say precisely: “Codex requested
`gpt-5.6-sol`; CloseProof validated the structured output, citations, amounts,
no-authority invariant, and snapshot. Provider prose was discarded; this text
was generated locally from the validated citations, uncertainty, exact amounts,
and evidence flag. Codex CLI 0.144.0 did not report returned model identity.” Do
not use fixture or simulated advisory content as model proof.

## 1:42–2:15 — Human decision

Enter this fixed rationale:

> The cited inclusive service period and deterministic integer-öre allocation
> support the prepaid treatment; missing invoice-total evidence is recorded for
> human follow-up.

Choose **Request evidence**. This is the safe action for the retained advisory's
missing-invoice-total disclosure and makes the demo repeatable.

“The reviewer remains accountable. Every action requires rationale and is bound
to the evidence snapshot. The local hash chain is internally consistent; no
posting or ERP write occurs.”

## 2:15–2:36 — Workpaper

Export the workpaper. Show snapshot SHA, source hashes, deterministic control,
validated advisory hash, human action, chain head, and the explicit
`current_decision` semantic-validation scope.

“This is the product: not an autonomous accountant, but a review trail another
person can verify.”

## 2:36–2:45 — Build proof

Show the plugin skill, green readiness command, and the primary Codex task.
State that `/feedback` was captured for Devpost, but keep the exact session ID
in the required submission field rather than exposing it in the video.

“CloseProof was built with Codex for OpenAI Build Week in Work & Productivity.”

## Recording guardrails

- Record only synthetic evidence; never show secrets, credentials, or API keys.
- The safety strip must remain visible: `Synthetic demo · Local controls · No
  ERP writes · Advisory optional`.
- Do not call ChatGPT-plan use universally free. Plan eligibility, allowance,
  and rate limits apply.
- A direct ChatGPT subscription is not an API credential. Manual ChatGPT prompt
  and `closeproof-advisory import` are fallback steps; the Responses API command
  is optional and requires separate explicit opt-in plus `OPENAI_API_KEY`.
- The competition recording must use the real `codex` run, describe requested
  model versus validated output precisely, and include the primary Codex
  `/feedback` ID in the submitted materials.
- If Codex is unavailable or rate-limited before recording, stop and retry
  later. Never relabel a fixture, manual import, or API-shaped mock as the live
  competition result.
