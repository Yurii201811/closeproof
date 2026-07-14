# Local model evaluation

Run date: 2026-07-11 (Europe/Stockholm)

Purpose: verify that the real loopback-only Ollama adapter can accept a public
synthetic accounting-risk case, return strict JSON, preserve advisory-only
authority, and fail closed when a response is not parseable.

## Environment

- Local development workstation; hardware details are deliberately omitted from
  the public release
- loopback-only Ollama-compatible runtime; local version and complete model
  inventory are deliberately omitted
- three representative model variants exercised
- temperature 0, seed 17, thinking disabled, streaming disabled, JSON format
- no course data, client data, credentials, hosted inference, ERP call, or
  accounting write

This was a functional comparison on an already-running local service, not a
controlled cold-start performance benchmark. Timing observations are therefore
omitted; the reproducible claims are parser behavior, semantic assertions, and
the fail-closed authority boundary.

The deterministic adapter contract can be rechecked without a live model:

```bash
python3 -m unittest tests.test_model_runtime_v1
```

A live comparison should use an operator-owned loopback endpoint and public
synthetic fixtures, record the model identifier and runtime version outside the
repository when either is sensitive, and rerun the same semantic assertions.

## Synthetic assertion

The generated case contains a possible duplicate invoice, changed supplier
bank details, and uncertain VAT. A valid advisory response must:

- return one strict JSON object;
- set `decision` to `block_review`;
- set `requires_human` to `true`;
- set `can_execute` to `false`;
- return exactly the three expected risk flags;
- retain `may_approve=false` and `may_execute=false` in the typed envelope.

## Results

| Model | Adapter JSON parse | Semantic assertions | Authority |
| --- | --- | --- | --- |
| `qwen3:4b` | pass | pass | advisory only |
| `qwen3:30b-instruct` | pass | pass | advisory only |
| `gemma4:12b-mlx` | fail closed: `strict_json_object_required` | not scored | none |

The smaller and larger Qwen variants both produced the requested synthetic-risk
classification in this run. The Gemma MLX variant did not satisfy the strict
parser contract and was rejected; a plausible-looking response is not silently
repaired or promoted.

## Decision

Use deterministic controls without a model whenever possible. For advisory
classification in this evaluation environment, `qwen3:4b` is the first local
smoke-test target and `qwen3:30b-instruct` is a comparison target. Neither is an
accounting authority. Every output remains hash-bound, deterministically
validated, and human-reviewed. Do not auto-fallback from a rejected model
response to a more permissive parser.

Ollama documents JSON-schema-constrained responses, but syntactic structure
does not establish accounting correctness. The application therefore retains
both strict parsing and separate deterministic semantic checks. See
[Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).
