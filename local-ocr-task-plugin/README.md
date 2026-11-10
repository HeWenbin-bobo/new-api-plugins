# Local Document OCR — New API Task Plugin

A third-party **New API Task Plugin API v1** driver for asynchronous PDF and image OCR through a self-hosted OCR task service.

- Plugin key: `local-ocr`
- Version: `0.1.6`
- Models: `mineru-pipeline-cpu`, `paddleocr-vl-1.6-cpu`
- Recommended submit: `POST /local-ocr/v1/parse` with multipart `model` and `file`
- Query: `GET /v1/tasks/{publicTaskId}`
- Artifacts: `GET /v1/tasks/{publicTaskId}/artifacts` and `/artifacts/{key}/content`
- Page usage is reported through the `pages` usage field; the plugin does not set a price.

This package contains only the gateway integration and its deterministic offline fixture. It does **not** include MinerU/PaddleOCR models, a Docker inference stack, real configuration, credentials, user documents, result data, caches or logs.

## Install in New API

1. Review `plugin.js`. The driver uses synchronous ECMAScript and has no imports, arbitrary network access, filesystem access or environment-variable reads.
2. Add this repository's root `index.json` as the New API marketplace source, or review and upload `plugin.js` directly. The host must support Task Plugin API v1. The supplied development report says the integration was exercised on `v1.0.0-rc.49`; this repository integration did not repeat that live test.
3. Add a **Task Plugin (type 61)** channel and bind `local-ocr`.
4. Set the channel Base URL to your OCR task gateway. This gateway must expose the fixed upstream service behind internal authentication; the plugin does not itself provide an OCR model.
5. Set the upstream key to the OCR gateway's internal key. Give callers only an ordinary New API user token, not the upstream internal key.
6. Enable the two models, configure permitted user groups and set a price. For a private zero-cost test, use `tier("free", u("pages") * 0)` for both models.
7. If using the included default `local-ocr.local` address, pin that name to your OCR gateway in the host and New API container `/etc/hosts` and allow its hostname/port in Fetch settings. Change it to your own DNS name for another deployment; do not expose an unauthenticated OCR gateway publicly.

The example default uses plaintext HTTP. Use it only on a trusted loopback/private network; on an untrusted network, configure HTTPS with normal certificate verification so caller tokens, the internal gateway key and document bytes are not exposed in transit. This preserves the supplied 0.1.6 source and is not a claim that a public TLS endpoint has been deployed or tested.

**0.1.6 pricing limitation:** `extractUsage()` uses a supplied `pages` value where present, or one page otherwise, before the gateway's trusted page count is available; completion usage is reconciled later. A multi-page PDF can therefore be authorized against an insufficient initial reservation. Do not enable nonzero per-page pricing or rely on this hook as the sole quota control for this version. Keep the zero-price configuration above, or enforce a separate trusted quota/reservation, until a later release uses trusted document inspection or reserves the 100-page maximum. This limitation was identified by post-publication static review; actual New API reservation and debit behavior has not been exercised during this repository integration. This warning does not change the runtime source or its indexed hash.

## Call

```bash
curl -X POST https://your-new-api.example/local-ocr/v1/parse \
  -H 'Authorization: Bearer <your-new-api-user-token>' \
  -F 'model=mineru-pipeline-cpu' \
  -F 'file=@paper.pdf'
```

Use `paddleocr-vl-1.6-cpu` for the other route. Poll the returned public task ID, list artifacts and download `markdown`, `json`, `package`, or engine-specific structured results. A completed task is not proof of OCR accuracy.

On the tested CPU-only host, MinerU is preferred for long documents; PaddleOCR-VL is for small documents or comparison. This is a hardware-specific timing observation, not an accuracy ranking.

## Marketplace index

The repository's root `index.json` lists only the latest `local-ocr@0.1.6` source at:

```text
local-ocr-task-plugin/plugin.js
```

New API sources should use the **raw root index URL**, not the repository homepage:

```text
https://raw.githubusercontent.com/HeWenbin-bobo/new-api-plugins/main/index.json
```

The version path resolves relative to that index on the same origin. The source SHA-256 is recorded in the index and must be regenerated whenever the plugin changes. Never reuse a version number for different source bytes. Installing this Task Plugin does not install the companion Skill or an OCR inference service.

## Validate

`evals/plugin_fixture.json` is the official-style deterministic fixture for submit, polling, usage and artifact contracts. From this project directory, run the dependency-free offline runner:

```bash
npm test
```

The current source passes all **11/11** fixture cases with no skipped or todo tests. This executes exported hooks in Node.js; it does not verify New API's moejs runtime, host multipart handling, persistence, billing or marketplace installation.

The supplied development report also states that real New API tests passed for both models, including submission, polling, artifact listing and downloads. That is supplied evidence for the tested version and deployment, not a fresh live verification performed during this repository integration. Do not upload real configuration or generated test results to GitHub.

## Independent project

This is an independent integration, not an official Baidu, OpenDataLab or New API release. Upstream models and New API retain their own licenses. See `LICENSE` and `CHANGELOG.md`.
