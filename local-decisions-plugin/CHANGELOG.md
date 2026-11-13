# Changelog

## 0.4.0

- Publish the native `/v1/systemone` decision adapter for `Piccolo-4B-Q4_K_M`, `Piccolo-9B-Q8_0` and `Jev-Omni-12B-Q4_K_M` under plugin key `local-decisions`.
- Route every model through `MODEL_BASE_URLS`: both Piccolo models to `127.0.0.1:18083` and Jev-Omni to its own runtime at `127.0.0.1:18503`. The channel base URL is only a fallback for models absent from that map, so the runtimes must be co-located with the New API host.
- Validate `choice` (2–256 criteria) and `noul` questions, normalized probabilities, and `usage.output_tokens === 0` before a caller can act on a response.
- Return decisions synchronously with no task retrieval endpoint.
- Reserve the 8,192-token maximum before each call and reconcile to the reported `input_tokens` on completion.
- Add a 17-case offline fixture covering routing, request shape, response validation and usage.
