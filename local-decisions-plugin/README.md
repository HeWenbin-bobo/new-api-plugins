# Local Decisions (Piccolo + Jev-Omni) — New API Task Plugin

A third-party **New API Task Plugin API v1** adapter that exposes Piccolo and Jev-Omni decision models through the native `/v1/systemone` route.

- Plugin key: `local-decisions`
- Version: `0.4.0`
- Models: `Piccolo-4B-Q4_K_M`, `Piccolo-9B-Q8_0`, `Jev-Omni-12B-Q4_K_M`
- Submit: `POST /v1/systemone`
- Synchronous: the HTTP response is the decision. There is no task ID, no polling and no streaming.

This is a decision adapter, not a chat model. It returns option probabilities with `usage.output_tokens === 0`; it does not generate answer text and does not implement `/v1/chat/completions`.

## Install in New API

1. Review `plugin.js`. The driver uses synchronous ECMAScript and has no imports, arbitrary network access, filesystem access or environment-variable reads.
2. Import `plugin.js` as a Task Plugin, or add this repository's root `index.json` as a marketplace source. The host must support Task Plugin API v1.
3. Keep the plugin key `local-decisions`; channels bind by key. Loading the source under a different key will not update an existing channel.
4. Add a **Task Plugin (type 61)** channel and bind `local-decisions`.
5. Every model is routed through `MODEL_BASE_URLS`, so the channel Base URL is not used for the three shipped models: both Piccolo models go to `http://127.0.0.1:18083` and `Jev-Omni-12B-Q4_K_M` to `http://127.0.0.1:18503`. The runtimes must therefore run on the New API host itself. To serve them elsewhere, change `MODEL_BASE_URLS` and `meta.allowedHosts` together and publish a new version with a recomputed index `sha256`; editing the shipped file in place breaks the published hash.
6. Enable the models you intend to serve, configure permitted user groups, and set expression pricing for `input_tokens` and `output_tokens`. Add `output_tokens` at zero or a nominal price; it is always `0` and exists only to keep the usage expression well-formed.
7. Use a channel timeout of at least 60 s. Piccolo and Jev-Omni each have a single inference slot, so requests to the same backend serialize.

Both default upstreams are plaintext loopback HTTP. That is suitable only for a trusted local host; put a TLS proxy in front of any non-loopback deployment. This is not a claim that a public TLS endpoint has been deployed or tested.

## Call

```bash
curl -X POST https://your-new-api.example/v1/systemone \
  -H 'Authorization: Bearer <your-new-api-user-token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Piccolo-4B-Q4_K_M",
    "state": "User request: read /data/orders.csv. Proposed action: read_file(path=/data/orders.csv, mode=read). No write, rename or delete is requested.",
    "questions": {
      "risk": {"type": "noul", "instructions": "Could this operation delete or overwrite existing data?"}
    }
  }'
```

`state` is the only evidence the model sees, so it must be self-contained. A `choice` question takes 2–256 mutually exclusive `criteria`; a `noul` question is binary and returns **P(yes)**. Probabilities cover exactly the supplied criteria and sum to 1 within 0.001. The compiled prompt is capped at 8,192 input tokens and oversized requests fail rather than being truncated.

A probability is not an authorization. Treat every result as advice: keep a human confirmation path for destructive, irreversible, financial or production-changing actions, and never convert a timeout, `401`, invalid probabilities or a nonzero `output_tokens` into an `allow`.

For the client-side workflow — request shapes, validation and safe application — see the companion Skill in [`local-decisions/`](../local-decisions/SKILL.md).

## Quota reservation

`extractUsage` validates the request and reserves the 8,192-token maximum before the call, and `extractUsageOnComplete` reconciles to the `input_tokens` the runtime reports; completion also rejects a nonzero `output_tokens`. Caller-supplied usage cannot reduce the initial reservation.

## Marketplace index

The repository's root `index.json` publishes only the latest `local-decisions@0.4.0` source at:

```text
local-decisions-plugin/plugin.js
```

Add the **raw root index URL**, not the repository homepage:

```text
https://raw.githubusercontent.com/HeWenbin-bobo/new-api-plugins/main/index.json
```

The version path resolves relative to that index on the same origin. The source SHA-256 is recorded in the index and must be regenerated whenever the plugin changes. Never reuse a version number for different source bytes. Installing this Task Plugin does not install the companion Skill, an inference runtime or model weights.

## Validate

`evals/plugin_fixture.json` is the deterministic fixture for the routing, request-shape, response-validation and usage contracts. From this project directory, run the dependency-free offline runner:

```bash
npm test
```

The current source passes all **17/17** fixture cases with no skipped or todo tests.

This executes exported hooks in Node.js against a fixture. It does not verify New API's moejs runtime, host routing, quotas, or the deployed Piccolo/Jev-Omni runtimes. Reported live checks refer to one deployment (`POST /v1/systemone` through New API `v1.0.0-rc.49`, channel `#82`, 2026-11-12); they are evidence for that deployment, not a fresh verification performed during this repository integration, and they validate transport and schema rather than model accuracy.

## Independent project

This is an independent integration. Piccolo, Jev-Omni, llama.cpp and New API retain their own licenses. See `LICENSE` and `CHANGELOG.md`.

## Maintenance note

If you edit `plugin.js`, regenerate the index `sha256`, bump the version, and restart New API so its plugin cache reloads.
