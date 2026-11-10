# Jihuarst Image 2.6 Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver the three Jihuarst gpt-image-2.6 models, New API rc.49 image fields, markup file/JSON inputs, and SVG/GIF output through the existing Skill.

**Architecture:** Extend `scripts/generate.py`'s existing model selection, request builder, and byte validator; do not add a parallel client. Parse JSON CLI values in `main()` before generation, validate markup/reference and model restrictions before paid requests, and retain current response limits and atomic writes.

**Tech Stack:** Python 3.9+ standard library, `argparse`, `unittest`; no new dependencies.

## Additional implementation verified after the initial plan

- Generations and edits request `response_format=url`; private offline matrix self-checks cover forced legacy b64_json in both modes. The production default remains URL.
- `--output-format png|jpeg|webp|svg|gif` is forwarded as native JSON or plain multipart text. SVG/GIF select the 2.6 chain; raster formats do not. Explicit incompatible models fail before generation.
- `data` remains a strict count contract: nonempty responses must contain exactly `n` entries; extra entries are never truncated to manufacture success. Missing/null/empty data remains an ordinary empty response, while other non-array values are paid-delivery failures.
- Remote download errors include only a bounded HTTP status or exception category. A regression test verifies that a generic `Mozilla/5.0` User-Agent is sent through the production opener without Authorization. This follows a real same-URL 403-to-200 control; it does not claim that slow or incomplete bodies are fixed.
- The user subsequently expanded verification to paid Jihuarst Image matrices and necessary fixes. Completed cases and failures are recorded in `docs/PROJECT_STATUS.md` and `jihuarst-image/SKILL.md`; no new paid video tasks are authorized or run.
- Independent review scope is explicit: the output-format/UA delta review found no new defect in that increment and identified invalid timeout handling; its tests predated the final validation additions. The separate final-delta approval covered only the earlier 75-test, two-hash data-missing/null change and is not approval of the current full diff. The official-contract documentation review supplied forwarding/schema distinctions without modifying files or making paid calls.
- Follow-up regressions now require `complexity=low|medium|high`, `frame_count=2..16`, `frame_duration_ms>=20`, a positive finite CLI timeout, and mask/markup mutual exclusion. The new targeted tests first produced 14 expected failures on the old implementation, then passed after minimal preflight checks; the complete current source suite passes 80/80 offline tests. No new paid matrix was started for these local validation changes.
- Packaging is rebuilt only from the final current source and audited separately. Commit, push, tag, PR, and marketplace installation remain unauthorized.

## Global Constraints

- Work on `feat/jihuarst-image-2-6`; do not commit or push without explicit user authorization.
- Contract evidence: New API `v1.0.0-rc.49` and PR #8208. The three model IDs are read-only confirmed on Jihuarst `/v1/models` on 2026-11-09; no live generation behavior is implied.
- Default model order: sunburst, exact, flare, 2.5, 2.5-flare, 2, then the mode-specific Hunyuan model.
- New options require a `gpt-image-2.6-` model, as do `--output-format svg|gif`. With no `--model`, selecting these limits fallback to the three 2.6 models. Explicit non-2.6 models fail before requests; raster `output_format` values retain the normal chain.
- `--markup` and `--markup-json` are mutually exclusive, and both conflict with `--mask`. Local `--markup` requires references; JSON markup is forwarded natively by generations or compactly by edits as an approved gateway extension. `complexity` is an enum, GIF frames are 2–16, frame duration is at least 20 ms, and timeout is positive and finite. Keep all existing credential, URL, byte-limit, retry, and atomic-output protections.
- Modify only `jihuarst-image`, its exact allowlisted ZIP, and repository design/plan/status documents. Do not change video product source.

### Task 1: Extend model selection and request fields with regression tests

**Files:**
- Modify: `jihuarst-image/tests/test_generate.py`
- Modify: `jihuarst-image/scripts/generate.py`

**Interfaces:**
- `GPT26_MODELS = ["gpt-image-2.6-sunburst", "gpt-image-2.6-exact", "gpt-image-2.6-flare"]`
- `_build_request(..., new_fields: dict[str, object], markup: Path | None)` returns the existing `(Request, endpoint)` tuple.
- `generate_image(..., new_fields: dict[str, object] | None = None, markup: Path | None = None)` preserves positional callers by appending keyword arguments.
- `main()` parses `--svg` and `--markup-json` with `_json_value(text: str) -> object`.

- [x] **Step 1: Write failing model-chain, encoding, markup, and local-validation tests**

Update expected lists to:

```python
GPT26_MODELS = [
    "gpt-image-2.6-sunburst", "gpt-image-2.6-exact", "gpt-image-2.6-flare",
]
EXPECTED_MODELS = GPT26_MODELS + [
    "gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2", "hunyuan-image-alpha",
]
EXPECTED_EDIT_MODELS = GPT26_MODELS + [
    "gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2", "hunyuan-image-alpha-edit",
]
```

Add tests asserting:

```python
fields = {
    "complexity": "low",
    "svg": {"model": "gpt-image-2.6-exact"},
    "frame_count": 2,
    "frame_duration_ms": 20,
}
# JSON: native types and exact values, including a valid minimum duration.
# Multipart: complexity="low", svg='{"model":"gpt-image-2.6-exact"}',
# frame_count="2", frame_duration_ms="20", markup_json is named "markup".
# --markup adds file name "markup" alongside the existing image field.
# --markup and --markup-json fail before requests, as does local markup without -r.
# Mask plus either markup form fails before requests.
# Invalid complexity, frame ranges, and non-positive/non-finite timeout fail before requests.
# JSON markup without -r uses generations and retains its native JSON type.
# New fields plus --model gpt-image-2.5 fail before requests.
# With new fields and no --model, each URL tries only GPT26_MODELS.
```

CLI coverage must include both markup forms and `_json_value()` valid scalar/object plus invalid/null rejection. No test may use the real `config.json`.

- [x] **Step 2: Run targeted tests and observe failures**

Run from `jihuarst-image/`:

```bash
PYTHONIOENCODING=utf-8 python -m unittest tests.test_generate.GenerateTests.test_declared_priorities_match_requirements -v
```

Expected: FAIL because `MODELS` lacks the three 2.6 IDs. The other new tests fail on unexpected keyword arguments or missing CLI options.

- [x] **Step 3: Implement the smallest request changes**

Add the model constants and CLI options. Build a `new_fields` dictionary from non-`None` options. Preserve native JSON values and use `json.dumps(value, ensure_ascii=False, separators=(",", ":"))` for multipart JSON fields. Serialize validated frame integers as decimal strings in multipart. Add local `markup` using `_read_reference()` and the multipart file field `markup`; serialize `markup_json` to the API field `markup`.

In `generate_image()`, reject invalid model/options and markup/reference/mask combinations before network activity. In `main()`, restrict complexity to `low|medium|high`, frame count to `2..16`, duration to at least 20 ms, and timeout to a positive finite number before loading credentials. If new options are present and `models is None`, select `GPT26_MODELS`; otherwise retain the existing text/edit chain. Forward all values unchanged across each selected attempt.

- [x] **Step 4: Run the full image suite**

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

Expected: all existing and new tests PASS, exit 0. Any failure is fixed in source or a demonstrably wrong new test without weakening legacy assertions.

### Task 2: Support bounded SVG/GIF artifacts

**Files:**
- Modify: `jihuarst-image/tests/test_generate.py`
- Modify: `jihuarst-image/scripts/generate.py`

**Interfaces:**
- `_validate_image_bytes(raw: bytes) -> None` accepts the existing raster signatures, SVG documents, and rejects malformed/oversized content.
- Response decoding, output targets, and atomic writer signatures remain unchanged.

- [x] **Step 1: Add failing delivery tests**

```python
svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><path/></svg>'
gif = b"GIF89a" + b"test-animation"
# Both survive _decode_images and are saved byte-for-byte at out.svg/out.gif.
# These fail: b"<html><svg/></html>", b"<svgx/>", b"<svg onload=...",
# invalid UTF-8 before <svg>, and empty input.
```

`b"<svg onload=...>"` (closed opening root tag) is accepted and saved as inert bytes: root recognition does not sanitize SVG. Require whitespace after the root name, then `>` for the opening tag; accept `<svg>` and `<svg ...>`, not unclosed roots. SVG is never rendered or executed.

- [x] **Step 2: Verify new format tests fail on the old signature check**

Run the new tests using `python -m unittest` from `jihuarst-image/`. Expected: SVG cases FAIL with `图片响应不是支持的图片`; GIF acceptance already passes.

- [x] **Step 3: Add minimal SVG root recognition**

In `_validate_image_bytes()`, after existing size and raster checks, decode at most the first 4096 bytes with strict UTF-8 after stripping an optional UTF-8 BOM. Skip whitespace, one XML declaration, repeated comments, and DOCTYPE declarations using bounded prefix logic. Require the next token to match `<svg(?:\s[^>]*)?/?>`; do not use a permissive substring search or execute XML. Raise the existing `_ImageDownloadError` for all other inputs.

- [x] **Step 4: Re-run the complete image suite**

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

Expected: all tests PASS, exit 0.

### Task 3: Synchronize documentation, review, and rebuild the exact client archive

**Files:**
- Modify: `jihuarst-image/SKILL.md`
- Modify: `docs/PROJECT_STATUS.md`
- Rebuild: `jihuarst-image/jihuarst-image.zip`
- Verify: all changed files

**Interfaces:** No new API beyond Task 1 and Task 2. ZIP contains exactly `SKILL.md`, `scripts/generate.py`, `tests/test_generate.py`, and `config.example.json`.

- [x] **Step 1: Update public usage and observed/unverified limits**

Document the new model order, all options, markup mutual exclusion, the local-file edits requirement and JSON generation support, 2.6 model restriction, native/compact JSON encodings, GIF frame-count distinction, and SVG/GIF delivery. Update all 16-combination references to 28. Label rc.49 forwarding and `/v1/models` as contract/catalog evidence; do not claim live generation, visual quality, or price verification. Record why video projects are unchanged.

- [x] **Step 2: Obtain a separate review pass**

Use `oh-my-claudecode:code-reviewer` on the final diff, giving it the spec and actual files rather than the author's conclusions. Fix CRITICAL/HIGH correctness/security issues and re-run tests. Keep authoring and approval separate.

- [x] **Step 3: Run video regression checks without changing their source**

Run each from its own directory:

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v  # jihuarst-video
npm test                                                        # each video plugin
```

Record final counts and exit codes. These regressions do not prove live New API rc.49 behavior.

- [x] **Step 4: Rebuild and validate only the Jihuarst Image ZIP**

Use a Python standard-library ZIP writer with the exact four relative names above. Verify `testzip() is None`, exact name allowlist, no symlinks/nested archives/private files, and each entry equals its source bytes. Extract to a new empty ignored temporary directory and run tests there with `python -I -m unittest discover -s tests -v`. Do not copy `config.json` or `.omc` content.

- [x] **Step 5: Perform final completion and sensitive-data checks**

Run:

```bash
git status --short --branch
git diff --check
git diff --stat
git diff
git ls-files --others --exclude-standard
node --test .githooks/check-push.test.js  # from repository root
```

Inspect all changes for TODO/placeholders, skipped/only tests, debug prints, real credentials, and unintended video/source edits. Compare tracked entries against the exact credential values in local ignored configs without printing those values. Report test commands, counts, archive verification, unverified live behavior, and the uncommitted branch state accurately.
