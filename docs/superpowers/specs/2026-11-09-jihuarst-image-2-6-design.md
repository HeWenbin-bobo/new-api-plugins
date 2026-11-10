# Jihuarst Image 2.6 Support Design

Date: 2026-11-09
Branch: `feat/jihuarst-image-2-6`

## Scope

Update `jihuarst-image` for the upstream model IDs `gpt-image-2.6-sunburst`, `gpt-image-2.6-exact`, and `gpt-image-2.6-flare`. Support the New API v1.0.0-rc.49 Images API fields `complexity`, `svg`, `frame_count`, `frame_duration_ms`, and `markup`, including local SVG/GIF delivery.

The three IDs were returned by `https://api.jihuarst.top/v1/models` in a read-only check on 2026-11-09. This verifies model publication, not generation behavior, parameter semantics, output quality, or pricing. New API release notes and PR #8208 are the contract evidence for forwarding, not live Jihuarst behavior evidence.

Do not change `jihuarst-video`, `video_wb2api_hub_newapi`, or `video_wb2api_panel_newapi`: they use `/v1/videos` and the Task Plugin `openai_video` protocol, not the Images API extended by rc.49.

## Request contract

Prepend the three new GPT IDs to both existing GPT fallback lists, in the order sunburst, exact, flare. Keep all older candidates and URL-first fallback unchanged.

Add these CLI options:

| Option | Local input | Request encoding |
| --- | --- | --- |
| `--output-format` | `png`, `jpeg`, `webp`, `svg`, or `gif` | Plain format string in either request mode |
| `--complexity TEXT` | `low`, `medium`, or `high` | Unchanged string |
| `--svg JSON` | Any non-null JSON value (approved gateway-extension behavior) | Native value in JSON; compact JSON text in multipart |
| `--frame-count INTEGER` | Integer from 2 through 16 | Integer in JSON; decimal text in multipart |
| `--frame-duration-ms INTEGER` | Integer of at least 20 ms | Integer in JSON; decimal text in multipart |
| `--markup IMAGE` | Existing, non-empty local image within the existing 64 MiB reference limit | Separate `markup` multipart file |
| `--markup-json JSON` | Any non-null JSON value | Native value in JSON; compact JSON text in multipart |

`--markup` and `--markup-json` are mutually exclusive, and both are mutually exclusive with `--mask`. The local file requires at least one `--ref`, hence the edits endpoint; JSON `markup` is also forwarded as a native JSON field by generations as an explicitly approved Jihuarst/New API compatibility extension beyond the official generations schema. The five feature options and `--output-format svg|gif` are restricted to `gpt-image-2.6-*` models by this client's conservative routing policy, not by a universal New API restriction. Without `--model`, supplying one of these selects the three-model 2.6 chain at each configured URL; an explicitly selected non-2.6 model is rejected before any request. Without these options, the default chain includes all seven candidates. Raster `output_format` values retain the normal model chain. Generation and delivery failures still follow the selected URL/model candidates without changing parameters or silently substituting models.

Both request modes default to `response_format=url` to avoid multi-MiB base64 JSON. This is a Jihuarst deployment-specific compatibility choice, not the OpenAI GPT Image contract; official GPT Image responses use base64. Existing b64_json and data-URL responses remain accepted. Downloads retain public-address validation, direct validated-IP connections, TLS hostname verification, redirect restrictions, and API-key isolation. A minimal `Mozilla/5.0` User-Agent replaces Python's default because a same-URL control changed from HTTP 403 to 200 with this header alone; response 200 does not by itself prove complete body delivery. Download errors expose only bounded HTTP status or exception-category details, never signed URLs, response bodies, or credentials.

`svg` and `markup-json` deliberately preserve arbitrary JSON because that is the approved permissive gateway-extension design. New API's `json.RawMessage` proves forwarding, not conformance of arbitrary values to an upstream schema. Official `svg` is a structured object containing `model` and `reasoning`, so clients needing strict official semantics must supply that shape themselves. Official GIF bounds are 2–16 frames and at least 20 ms per frame; the client enforces those minima/maxima before any request. Official duration rounding, defaults, and encoded upper bound remain upstream behavior and are not reimplemented locally. Invalid, zero, negative, NaN, or infinite CLI timeout values also fail before loading credentials or opening a request.

Official markup is a transparent PNG for edits, overlaid on the first image after orientation/size alignment, and cannot be combined with mask. The client preserves that incompatibility for both local and JSON markup. Official sources currently conflict about edits SVG support: the OpenAPI contains SVG-related edit definitions while the Python SDK still excludes them and retains a prior prohibition. Local SVG byte handling is not evidence that upstream edits SVG is supported. `gpt-image-2.6-exact` is a Jihuarst catalog ID, not a claimed OpenAI official model enumeration entry.

## Delivery contract

Keep `data` entries and `n` as the delivery count contract. `frame_count` describes animation frames inside one GIF, not separate response images. Keep caller-selected output names and suffixes.

Accept existing PNG/JPEG/GIF/WebP signatures plus SVG documents. SVG recognition decodes a bounded prefix as UTF-8, permits an XML declaration, repeated comments and DOCTYPE declarations, and requires a normal or self-closing `<svg>` opening root. Reject HTML, arbitrary markup, invalid UTF-8, empty content, and oversized responses. Never execute, render, or fetch resources referenced by SVG. Existing byte limits, base64 bounds, public-address download validation, credential isolation, retries, and atomic replacement remain unchanged.

## Documentation and packaging

Update `jihuarst-image/SKILL.md` with model ordering, all new CLI options, markup rules, SVG/GIF handling, the 2.6-only selection when new options are used, and untested live semantics. Record the milestone and video assessment in `docs/PROJECT_STATUS.md`. Regenerate only `jihuarst-image/jihuarst-image.zip` from the exact four-file release allowlist (`SKILL.md`, `scripts/generate.py`, `tests/test_generate.py`, `config.example.json`), excluding credentials, caches, and local state.

## Verification

Use TDD against the standard-library offline suite. Cover model lists, native JSON and multipart field types, valid GIF frame values, arbitrary JSON values, local markup upload, markup/mask and markup/markup input conflicts, local-file reference requirements and JSON generation without references, non-2.6 rejection before requests, complexity and frame bounds, invalid finite/non-finite timeout rejection, SVG/GIF acceptance, SVG spoof rejection, CLI forwarding, and unchanged legacy delivery behavior.

Run the full image suite with `PYTHONIOENCODING=utf-8`. Run the video Skill and both video plugin suites as regression evidence without changing their source. Verify clean ZIP extraction, CRC, exact source equality, entry allowlist, and credential scans.

The user's later explicit extension authorizes real paid Jihuarst Image generation, edits, parameter and compatibility matrices, and necessary client fixes. Each case is pinned to `https://api.jihuarst.top` and one model, with synthetic local inputs. Existing image URLs may be downloaded without new generation for download-only diagnosis. SVG/GIF/markup and gateway failures must be reported, not simulated as live successes. New API installation is not included. This authorization does not add paid video tasks, publication, commits, or pushes.

## Evidence

- https://github.com/QuantumNous/new-api/releases/tag/v1.0.0-rc.49
- https://github.com/QuantumNous/new-api/pull/8208/files
