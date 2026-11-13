---
name: local-decisions
description: Use when a downstream user or agent needs to call Piccolo 4B/9B or Jev-Omni 12B decision models through a New API Task Plugin channel, build /v1/systemone choice or noul questions, validate probabilities, and apply results as advice with human fallback.
---

# Local Decisions through New API (Piccolo + Jev-Omni)

Call a Piccolo or Jev-Omni decision model behind a New API **Task Plugin (type 61)** channel. This is a decision API, not a chat API: it returns candidate probabilities, not generated text. Do not call `/v1/chat/completions` for these models.

## When to use this Skill

Use it when you need a cheap, local second opinion for a bounded decision:

- choose among known tool actions, routes, or workflow branches;
- estimate whether a proposed action is risky;
- decide whether context should be retained;
- review a permission request before a human sees it;
- use Jev-Omni when you want a broader general-purpose text classifier than Piccolo.

Jev-Omni can also process images and video through its direct wrapper, but this Skill and New API channel expose only the text `/v1/systemone` decision route. It is not an OCR quality model; OCR remains a separate pipeline.

Do not use these models as a general conversational model, a code generator, or an autonomous authorization mechanism.

## Prerequisites

Confirm all four items before the first call:

1. **New API base URL** — the gateway root, for example `http://127.0.0.1:3000`. The endpoint is `POST {base_url}/v1/systemone`. A trailing `/v1` is accepted and stripped by the bundled client.
2. **Caller token** — an ordinary New API user token, not an administrator PAT. Send it as `Authorization: Bearer <token>`.
3. **Token group access** — the gateway's task-plugin channel must include your token's group. A token whose group is not enabled on that channel may see no available channel.
4. **Exact model ID** — `Piccolo-4B-Q4_K_M`, `Piccolo-9B-Q8_0`, or `Jev-Omni-12B-Q4_K_M`. These are the only accepted IDs.

The channel must already be enabled with plugin key `local-decisions`. The key matches the Skill name so the task-plugin binding is unambiguous. Do not invent a channel ID, endpoint, or model name.

## Quick start

Set credentials in the environment; never commit them:

```bash
export NEW_API_BASE_URL="http://127.0.0.1:3000"
export NEW_API_KEY="<your New API user token>"
```

Run a ready-made request:

```bash
python scripts/local_decide.py --request assets/request-multi.json
```

Choose the 9B model and a longer timeout:

```bash
python scripts/local_decide.py \
  --request assets/request-choice.json \
  --model Piccolo-9B-Q8_0 \
  --timeout 60
```

Use Jev-Omni for a broader text decision:

```bash
python scripts/local_decide.py \
  --request assets/request-jev.json \
  --model Jev-Omni-12B-Q4_K_M \
  --timeout 60
```

Read a request from stdin:

```bash
cat assets/request-noul.json | python scripts/local_decide.py --request -
```

The client prints JSON to stdout and uses exit code `0` on success, `2` for input/configuration errors, `3` for HTTP or network errors, and `4` for invalid upstream responses. It never prints the token or the full request body.

## Request shape

The gateway accepts one synchronous JSON object:

```json
{
  "model": "Piccolo-4B-Q4_K_M",
  "state": "The user asked for the total in /data/orders.csv. The proposed action is read-only read_file('/data/orders.csv'). No write or delete is requested. The file is the only copy.",
  "questions": {
    "action": {
      "type": "choice",
      "instructions": "Select the next action.",
      "criteria": {
        "read": "Read the CSV without modifying it.",
        "write": "Modify or overwrite the CSV.",
        "delete": "Delete the CSV."
      }
    },
    "keep": {
      "type": "noul",
      "instructions": "Should the user request and file path remain in context for the next step?"
    }
  }
}
```

- `state` must be a non-empty string or array. Prefer a string. It is the **only evidence** the model sees; make it self-contained.
- `questions` must be a non-empty object. Each key becomes a key in the response.
- `choice` needs `2` to `256` mutually exclusive `criteria`; `noul` is a yes/no question. See [the full API contract](references/api-contract.md).
- The hard ceiling is `8,192` input tokens across the compiled prompt. Keep `state` well below that, especially with several questions. Oversized requests fail; they are not silently truncated.

## Response shape

```json
{
  "model": "piccolo-test",
  "answers": {
    "action": {
      "type": "choice",
      "choice": "read",
      "probabilities": {
        "read": 0.9997,
        "write": 0.0002,
        "delete": 0.0001
      },
      "confidence": 0.9995
    },
    "keep": {
      "type": "noul",
      "noul": 0.91
    }
  },
  "usage": {
    "input_tokens": 412,
    "output_tokens": 0
  }
}
```

- `answers.<name>.choice` is the highest-probability option.
- `probabilities` cover exactly the supplied criteria and sum to `1` within `0.001`.
- `confidence` is a runtime certainty score, not a calibrated probability that the decision is correct. Its scale is runtime-specific; use it only as a relative signal.
- `noul` is **P(yes / true)** for the instruction. If you ask “Could this operation delete data?”, a high value means high risk. If you ask “Is this operation read-only?”, a high value means low risk. Keep the polarity explicit.
- `usage.output_tokens` must be `0`. `response.model` may be the upstream runtime alias (`piccolo-test`, `piccolo-9b`, or `Jev-Omni-12B-Q4_K_M`), not necessarily the model ID you requested; use your request's `model` for routing and audit.

## Model choice

| Model | Use it for | Observed on this host |
|---|---|---|
| `Piccolo-4B-Q4_K_M` | Default; fast reviews, tool selection, routine permission checks | typically `4–9 s`; up to ~`15 s` under host load |
| `Piccolo-9B-Q8_0` | Harder or higher-stakes decisions where latency is acceptable | typically `10–20 s`; up to ~`37 s` under heavy load |
| `Jev-Omni-12B-Q4_K_M` | Broader general-purpose text decisions; use when Piccolo's domain fit is uncertain | typically `5–6 s`; up to ~`21 s` under host load |

The Piccolo 4B/9B and Jev-Omni backends each have one parallel slot, so requests to the same backend serialize. Piccolo and Jev are separate CPU runtimes and can run concurrently, but they still compete for the host's 20-thread budget. Do not use this as a high-QPS service. Use `--timeout 30` for 4B and `--timeout 60` for 9B or Jev-Omni; lower timeouts may cut off legitimate CPU inference.

## Apply the result safely

The decision is **advice**, not authorization. A probability is not a safety guarantee.

A conservative policy for an approval decision:

```text
risk = answers["risk"]["noul"]          # P(yes) to "Could this delete or overwrite data?"
action = answers["action"]["choice"]
p = answers["action"]["probabilities"][action]

if risk >= 0.90:
    ask_human()
elif action == "allow" and p >= 0.90 and operation_is_read_only:
    allow()
else:
    ask_human()
```

Rules that should not be relaxed:

- Destructive, irreversible, financial, or production-changing actions always require human confirmation.
- On timeout, `401`, `400`, invalid probabilities, or `output_tokens != 0`, fall back to the existing policy. Never convert an error into `allow`.
- Do not use `0.51` as permission. Calibrate thresholds on your own labeled cases; see [decision design](references/decision-design.md).
- Do not send secrets, full credentials, or unrelated personal data in `state`. Send the minimum evidence needed for the decision.
- Do not log the token or the full `state`. Log the model ID, question names, chosen option, probabilities, latency, and a redacted case ID.

## Errors and retries

| Symptom | Meaning | Action |
|---|---|---|
| `401` `Invalid token` | Missing, expired, or wrong New API token | Fix the token; do not retry blindly |
| `400` `"state" must be provided` or similar | Request body rejected by the adapter or gateway | Fix the request; do not retry unchanged |
| `404` | Wrong path, or model not exposed by the channel | Use `/v1/systemone` and an exact model ID |
| `429` | Rate or concurrency limit | Back off, then retry at most twice |
| `502` / `503` / `504` | Piccolo or Jev-Omni runtime/router unavailable | Bounded retry, then fall back |
| Timeout | CPU inference exceeded the budget | Raise the timeout for 9B or Jev-Omni, or fall back |

Retry only `429`, `5xx`, and timeouts, with exponential backoff and at most two retries. The decision call itself is side-effect-free, but the action you take afterward is not: never repeat a destructive action because the decision request was retried.

## Files

| Path | Purpose |
|---|---|
| `scripts/local_decide.py` | Standard-library client for Piccolo and Jev-Omni; validates request and response, supports timeout and raw output |
| `references/api-contract.md` | Endpoint, fields, limits, error envelopes, New API specifics |
| `references/decision-design.md` | How to write `state`, `choice`, `noul`, thresholds, and evaluation |
| `assets/request-choice.json` | Permission-review example with a choice and a risk noul |
| `assets/request-noul.json` | Minimal read-only risk check |
| `assets/request-multi.json` | Two-question request with choice and noul |
| `assets/request-jev.json` | Jev-Omni text decision example |
| `assets/response-multi.json` | Matching response for the multi-question example |
| `evals/test_local_decide.py` | Offline smoke tests against a local fake HTTP server |

## Packaging

The Skill directory is self-contained: `SKILL.md`, `references/`, `scripts/`, `assets/`, and `evals/`. Upload the directory as one repository or copy it under `skills/local-decisions/`. It contains no credentials, model weights, runtime binaries, logs, or generated output. Keep real tokens in environment variables or a local secret store; never add a `.env` file to the package.
