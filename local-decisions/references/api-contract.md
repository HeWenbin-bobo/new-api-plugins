# Local decisions (Piccolo + Jev-Omni) New API contract

This document describes the decision endpoint exposed by a New API **Task Plugin (type 61)** channel backed by Piccolo or Jev-Omni runtimes. The adapter supports `choice` and `noul` questions only. It does not generate answer text.

## Endpoint

```http
POST {base_url}/v1/systemone
Authorization: Bearer <NEW_API_TOKEN>
Content-Type: application/json
Accept: application/json
```

- `base_url` is the New API gateway root, for example `http://127.0.0.1:3000`.
- If the gateway is mounted under a prefix, include that prefix in `base_url`.
- A trailing `/v1` in `base_url` is accepted by the bundled client and stripped before appending `/v1/systemone`.
- Do not put the token in a query parameter.
- The call is synchronous. There is no task ID, polling step, or streaming response.

## Reference deployment

The author's local deployment uses the values below. They describe one deployment, not a universal default. Ask your gateway operator for the URL, token group, and enabled model IDs.

| Item | Value |
|---|---|
| New API version | `v1.0.0-rc.49` |
| Channel | `#82`, name `Local Decisions (Piccolo + Jev-Omni)`, type `61` |
| Plugin key | `local-decisions` (`0.4.x`) |
| Channel groups | `ssvip`, `svip`, `ROOT`, `vip`, `GPT` |
| Upstream routers | Piccolo `http://127.0.0.1:18083`; Jev-Omni `http://127.0.0.1:18503` |
| Models | `Piccolo-4B-Q4_K_M`, `Piccolo-9B-Q8_0`, `Jev-Omni-12B-Q4_K_M` |

These values describe one deployment, not a universal default. Ask the gateway operator for the URL, token group, and enabled model IDs.

## Models

Only three model IDs are accepted:

- `Piccolo-4B-Q4_K_M` — default; lower latency.
- `Piccolo-9B-Q8_0` — higher capacity; slower on CPU.
- `Jev-Omni-12B-Q4_K_M` — broader general-purpose text decisions; separate Jev-Omni runtime.

The model must be enabled on the channel and the caller's token group must be allowed by that channel. Do not use `piccolo-router`, `piccolo-test`, or `piccolo-9b` as the request model: those are internal/router aliases, not accepted channel model IDs. `Jev-Omni-12B-Q4_K_M` is the channel ID; the wrapper may echo it or an internal alias in `response.model`.

The upstream Piccolo router's `GET /v1/models` may return only `piccolo-router`; it is not a reliable list of callable New API model IDs. Use the New API channel configuration or the three IDs above.

## Request

```json
{
  "model": "Piccolo-4B-Q4_K_M",
  "state": "The user asked for the total in /data/orders.csv. The proposed action is read-only read_file('/data/orders.csv'). No write or delete is requested.",
  "questions": {
    "action": {
      "type": "choice",
      "instructions": "Select the next action.",
      "criteria": {
        "read": "Read the CSV without modifying it.",
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

### Fields

| Field | Required | Type | Constraints |
|---|---|---|---|
| `model` | yes | string | Exactly `Piccolo-4B-Q4_K_M`, `Piccolo-9B-Q8_0`, or `Jev-Omni-12B-Q4_K_M` |
| `state` | yes | string or array | Non-empty; string preferred. The adapter accepts an array but serializes it as JSON evidence. |
| `questions` | yes | object | At least one entry; keys must be non-empty after trimming |
| `questions.<name>.type` | yes | string | `choice` or `noul` |
| `questions.<name>.instructions` | yes | string | Non-empty; ask one neutral question |
| `questions.<name>.criteria` | for `choice` | object | `2` to `256` entries; every value must be a string |
| `questions.<name>.criteria` | optional for `noul` | object | If supplied, use `false` and `true` keys with string descriptions |

No other question types are supported by this adapter. `score`, free-form text, and multi-turn chat are not available.

### `choice` semantics

`criteria` is a map from option ID to a short description. The option IDs are returned unchanged in the response. They should be:

- mutually exclusive;
- collectively exhaustive for the decision;
- short and stable, because they become response keys;
- defined by observable conditions, not vague labels.

Example:

```json
{
  "type": "choice",
  "instructions": "Which action should the agent take next?",
  "criteria": {
    "allow": "Execute the read-only query now.",
    "ask": "Ask the user for missing scope or confirmation.",
    "deny": "Refuse because the request is outside the authorized scope."
  }
}
```

### `noul` semantics

`noul` is a binary decision rendered as `no` / `yes`, keyed internally as `false` / `true`. The response field `noul` is **P(yes)**.

```json
{
  "type": "noul",
  "instructions": "Could this operation delete or overwrite existing user data?",
  "criteria": {
    "false": "The operation is read-only or creates a new file.",
    "true": "The operation can remove or overwrite existing data."
  }
}
```

The optional `criteria` descriptions anchor what `false` and `true` mean. They are not required by the adapter, but they reduce polarity mistakes. Always record the question's polarity in your audit log: the same numeric `noul` can mean “safe” or “dangerous” depending on how the question is phrased.

### Token budget

The runtime allows up to **8,192 input tokens per compiled prompt row**. The adapter does not silently truncate; an oversized request fails. Multiple questions repeat the full state in separate prompt rows, so total input usage grows with the number of questions.

Practical guidance:

- Keep `state` under roughly `4,000` tokens for a multi-question request.
- Do not paste an entire conversation; include the request, the proposed action, its target, authorization, side effects, and relevant history.
- If the request is rejected for size, shorten `state` first, then reduce the number of questions.

## Response

```json
{
  "model": "piccolo-test",
  "answers": {
    "action": {
      "type": "choice",
      "choice": "read",
      "probabilities": {
        "read": 0.9997,
        "delete": 0.0003
      },
      "confidence": 0.9994
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

### Response fields

| Field | Type | Meaning |
|---|---|---|
| `model` | string | Upstream runtime alias, often `piccolo-test`; not necessarily the requested model ID |
| `answers` | object | One entry per request question, keyed by the question name |
| `answers.<name>.type` | string | Echoes `choice` or `noul` |
| `answers.<name>.choice` | string | Winning option ID for a `choice` question |
| `answers.<name>.probabilities` | object | Option ID to probability; keys match the request criteria; values are in `[0, 1]` and sum to `1` within `0.001` |
| `answers.<name>.confidence` | number | Runtime certainty score in `[0, 1]`; not a calibrated accuracy guarantee, and its scale is runtime-specific |
| `answers.<name>.noul` | number | P(yes) for a `noul` question, in `[0, 1]` |
| `usage.input_tokens` | integer | Input tokens consumed, `0` to `8192` |
| `usage.output_tokens` | integer | Must be exactly `0` |

A valid response must satisfy all of the following:

1. `answers` is an object and contains every requested question.
2. Each answer's `type` matches the request.
3. For `choice`, the probability keys equal the criteria keys and the values sum to `1` within `0.001`.
4. `choice` names an option whose probability is the maximum (ties are allowed).
5. For `noul`, the value is a finite number in `[0, 1]`.
6. `usage.output_tokens` is `0` and `usage.input_tokens` is an integer in `[0, 8192]`.

The bundled client enforces these checks and exits with code `4` if any fail.

## New API behavior

- The channel is type `61` (Task Plugin). The plugin key is `local-decisions`.
- The plugin accepts `POST /v1/systemone` and forwards the JSON body to the model-specific backend: Piccolo models to `18083`, Jev-Omni to `18503`.
- The response body is the native decision envelope; it is not wrapped in an OpenAI `choices` array.
- Images and video are not exposed through this channel. They use the Jev-Omni wrapper's direct `/v1/decide` endpoint instead.
- Authentication, group selection, quotas, and usage accounting are handled by New API.
- The call is synchronous: the HTTP response contains the decision. There is no asynchronous task to poll.
- `/v1/chat/completions` is not implemented for this channel. Calling it returns `404`.

## Errors

New API authentication errors use the standard envelope:

```json
{
  "error": {
    "code": "",
    "message": "Invalid token (request id: ...)",
    "type": "new_api_error"
  }
}
```

Upstream validation errors may use:

```json
{
  "error": {
    "code": 400,
    "message": "\"state\" must be provided",
    "type": "invalid_request_error"
  }
}
```

| HTTP | Typical cause | Client behavior |
|---|---|---|
| `400` | Missing/invalid `state`, `questions`, `model`, or criteria | Exit `3`; fix the request; do not retry unchanged |
| `401` | Missing, expired, or wrong token | Exit `3`; fix the token |
| `404` | Wrong path or model not exposed by the channel | Exit `3`; use `/v1/systemone` and an exact model ID |
| `429` | Rate or concurrency limit | Exit `3`; back off and retry at most twice |
| `500` / `502` / `503` / `504` | Piccolo or Jev-Omni runtime, router, or gateway failure | Exit `3`; bounded retry, then fall back |
| Network timeout | CPU inference exceeded the client timeout | Exit `3`; raise the timeout or fall back |

Do not retry `400`, `401`, or `404` without changing the request or configuration. Do not treat any error as an `allow` decision.

## Latency and concurrency

Measured on the current CPU host with short two-question text requests:

| Model | HTTP status | Elapsed |
|---|---|---|
| `Piccolo-4B-Q4_K_M` | `200` | `4.09 s` |
| `Piccolo-9B-Q8_0` | `200` | `9.91 s` |
| `Jev-Omni-12B-Q4_K_M` | `200` | `5.62 s` |
| `Jev-Omni-12B-Q4_K_M` (choice) | `200` | `4.45 s` |

Earlier 398–596-input-token requests took about `6–9 s` on 4B and `17–20 s` on 9B, so treat these as typical ranges rather than fixed costs. Under concurrent host load, later runs were slower (`15.7 s` for 4B, `37.1 s` for 9B, and `20.8 s` for Jev-Omni). Each model has one parallel slot; Piccolo and Jev-Omni are separate runtimes but share the host's CPU budget. Use at least `30 s` timeout for 4B and `60 s` for 9B or Jev-Omni. These are observations, not service-level guarantees; measure your own deployment.

## Verified behavior

Verified on 2026-11-12 through the local New API channel `#82`:

- all three models returned HTTP `200`;
- `choice` probabilities were normalized and `choice` matched the maximum;
- a read-only `noul` test returned a low P(yes) for “Could this operation delete or overwrite existing data?”, confirming that `noul` is P(yes), not P(safe);
- `usage.output_tokens` was `0` in every successful response;
- the same channel routed Piccolo and Jev-Omni through the merged plugin without a second channel.

These checks validate the transport and schema, not the model's accuracy on your domain.
