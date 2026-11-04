# WorkBuddy Kling Task Plugin Implementation Plan

**Goal:** Build an uploadable new-api Task Plugin v1 that serves `kling-video-v3` through a local workbuddy2api-hub gateway.

**Architecture:** One synchronous ECMAScript module implements the `openai_video` protocol and per-task driver hooks. New-api owns persistence and polling; the plugin only maps requests, responses, and the signed content URL.

**Tech Stack:** JavaScript Task Plugin API v1; Node.js built-in `node:test`; no runtime dependencies.

## Global Constraints

- Do not modify new-api or workbuddy2api-hub source code.
- Never embed a real API key or contact the paid upstream during tests.
- Preserve the signed `url` returned by workbuddy2api-hub; do not reconstruct its token.
- The project is not a Git repository, so no commits are created.

### Task 1: Plugin contract and driver

**Files:** `plugin.js`, `package.json`, `tests/plugin.test.js`

**Interfaces:** Export `meta`, `protocols.openai_video`, `buildSubmitRequest`, `parseSubmitResponse`, `buildQueryRequest`, `parseTaskResult`, `listArtifacts`, and `buildContentRequest` exactly as declared by new-api Task Plugin API v1.

- [x] Write tests for manifest, JSON text-to-video, JSON and multipart image-to-video, invalid input, task ID extraction, status mapping, failures, artifacts, signed downloads, and usage.
- [x] Run `npm test`; expected failure: `Cannot find module '../plugin.js'`.
- [x] Implement the smallest plugin satisfying those contracts. Use `ctx.upstreamModel` for model mapping, Bearer authentication for submit/query, and no credentials on signed content requests.
- [x] Run `npm test`; all 12 tests pass.

### Task 2: Installation documentation and verification

**Files:** `README.md`

- [x] Document upload, type-61 channel binding, model configuration, Docker base URL, and OpenAI Video request examples.
- [x] Run syntax checking and `npm test` again.
- [x] Inspect the finished source for placeholders, embedded credentials, or unsupported plugin APIs.
