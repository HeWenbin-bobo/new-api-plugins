# WorkBuddy Video and Image Exhaustive Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename and generalize the video Task Plugin, and make image generation return success only after complete local image delivery, retrying every remaining URL/model combination after any attempt failure.

**Architecture:** Keep the existing New API request/poll/proxy flow and the existing image candidate loop. Change only plugin identity/model metadata and move image post-generation delivery and atomic output writing into the same per-candidate failure handling; do not add a second plugin, model substitution, or a parallel image implementation.

**Tech Stack:** JavaScript ES modules and Node.js built-in test runner; Python 3.9+ standard library and `unittest`; JSON marketplace metadata; allowlisted ZIP release artifacts.

## Global Constraints

- Rename `kling_wb2api_newapi/` to exactly `video_wb2api_newapi/`.
- Use key `workbuddy-video`, display name `WorkBuddy Video`, version `1.1.0`, and ordered models `minimax-video-h3`, `kling-video-v3`.
- Preserve `body: { ...requestBody, model: ctx.upstreamModel || ctx.model }`; do not add hidden model substitution.
- `index.json` must contain only the new `1.1.0` plugin version and path `video_wb2api_newapi/plugin.js`; hash exact LF-normalized source bytes.
- Image candidate order remains URL first, model second; explicit `--base-url` and `--model` continue to restrict candidates.
- Local input and CLI validation still fail before paid requests.
- Retry generation, response parsing, image download/validation/count, and local-output failures. Record sanitized errors and return success only after all requested images are saved.
- Repeated attempts after an upstream artifact may be billed again; disclose this in `SKILL.md` and final exhaustion errors.
- Preserve `_write_images_atomically()` staging, fsync, backup, reverse rollback, and failed-restoration backup preservation.
- Automated tests are offline, use temporary files and loopback mocks, and make no real paid API calls.
- Rebuild only `video_wb2api_newapi/video_wb2api_newapi.zip` and `jihuarst-image/jihuarst-image.zip` for these upgrades; old plugin ZIP is superseded.
- Do not commit, tag, push, or rewrite Git history without new explicit authorization.

---

### Task 1: Image delivery retries every remaining candidate

**Files:**
- Modify: `jihuarst-image/tests/test_generate.py`
- Modify: `jihuarst-image/scripts/generate.py`
- Modify: `jihuarst-image/SKILL.md`
- Regenerate: `jihuarst-image/jihuarst-image.zip`

**Interfaces:**
- Consumes: `generate_image(...) -> GenerationResult`, `_write_images_atomically(targets, images)`, `redact_secrets(text, api_key)`.
- Produces: unchanged public function/CLI signatures; successful return means every requested image was written locally.

- [ ] **Step 1: Convert terminal-delivery tests into failing fallback regressions**

For each case below, configure two explicit models on one loopback server: the first response exhibits the failure and the second returns valid `IMAGE_BYTES`; assert the second request occurs and `generate_image()` returns one saved output.

- Download failure, oversized download, non-HTTP redirect, non-image download.
- Malformed URL, non-image encoded data, oversized encoded data.
- Empty entries, non-list `data`, and fewer images than requested.
- Local output write failure on the first candidate, using a call-count-aware `os.replace` mock so only the first attempt fails.

Representative count regression:

```python
def test_incomplete_count_falls_back_to_next_model(self) -> None:
    with fake_api([200, 200], payloads=[{"data": []}, None]) as (server, url):
        result = self.module.generate_image(
            "cat", self.output, "test-key", [url], ["first", "second"], 2,
        )
    self.assertEqual([self.output], result.paths)
    self.assertEqual(IMAGE_BYTES, self.output.read_bytes())
    self.assertEqual(2, len(server.requests))
```

Adapt the fixture to its existing payload conventions rather than introducing a second server abstraction. Keep the existing failed-rollback test, but require the final sanitized error to contain the preserved backup path after all explicit candidates fail.

Add an all-candidates-fail test that uses two failures, asserts `RuntimeError`, both candidate labels, absence of a fabricated output, redaction of `test-key`, and the duplicate-charge warning.

- [ ] **Step 2: Run the focused tests and verify RED**

Run from `jihuarst-image/`:

```bash
PYTHONIOENCODING=utf-8 python -m unittest tests.test_generate -v
```

Expected: the changed fallback tests fail because the first post-artifact or output failure currently raises instead of reaching the second model.

- [ ] **Step 3: Make the minimal loop change**

Keep request generation, decoding, target construction, and `_write_images_atomically()` inside the per-candidate `try`. Remove the special terminal rethrow for `_PaidDeliveryError`; let its sanitized details join the common error list and `continue`. Replace the terminal local-output wrapper with the same per-attempt handling. Preserve the success return immediately after atomic writing.

The final error must say all selected combinations failed and later attempts may have caused duplicate charges:

```python
details = "\n".join(errors)
raise RuntimeError(
    f"{total} 次 URL/模型组合尝试均失败；未能完整保存所请求的图片。\n"
    "部分尝试可能已生成并计费；重试其他组合可能产生重复费用，请核对上游用量。\n"
    f"{details}"
)
```

Do not change `_write_images_atomically()`, validation, URL/model ordering, or result types.

- [ ] **Step 4: Verify focused and full image suites**

```bash
PYTHONIOENCODING=utf-8 python -m unittest tests.test_generate -v
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

Expected: all tests pass with zero failures/errors; expected mock failures may appear in logs but do not change the final result.

- [ ] **Step 5: Update the executable Skill contract**

In `jihuarst-image/SKILL.md`, replace all “已计费即终止/不再次提交” wording with the exhaustive candidate policy. State that response artifacts followed by download, validation, count, or local-output failure still advance, and that this can repeat paid generation. Preserve atomic recovery text and document the new final exhaustion error.

- [ ] **Step 6: Review and checkpoint without Git mutation**

Inspect the image diff for unimplemented branches, skipped tests, unsanitized new errors, and accidental changes to recovery logic. Do not commit or push.

---

### Task 2: Rename and upgrade WorkBuddy Video

**Files:**
- Rename: `kling_wb2api_newapi/` to `video_wb2api_newapi/`
- Modify: `video_wb2api_newapi/plugin.js`
- Modify: `video_wb2api_newapi/tests/plugin.test.js`
- Modify: `video_wb2api_newapi/package.json`
- Modify: `video_wb2api_newapi/README.md`

**Interfaces:**
- Consumes: existing Task Plugin API v1 handlers and `ctx.upstreamModel || ctx.model`.
- Produces: `meta.key == "workbuddy-video"`, ordered two-model support, and unchanged task/video proxy behavior.

- [ ] **Step 1: Write failing manifest and MiniMax forwarding tests**

Update the manifest assertions:

```javascript
assert.equal(meta.key, 'workbuddy-video');
assert.equal(meta.name, 'WorkBuddy Video');
assert.equal(meta.version, '1.1.0');
assert.deepEqual(meta.models, ['minimax-video-h3', 'kling-video-v3']);
```

Add a submission regression using the existing loopback fixture: decode a request selecting `minimax-video-h3`, submit it, then parse the captured upstream JSON and assert:

```javascript
assert.equal(upstreamBody.model, 'minimax-video-h3');
```

Retain the Kling forwarding test so neither model is replaced.

- [ ] **Step 2: Run tests and verify RED**

Run from `kling_wb2api_newapi/` before the rename:

```bash
npm test
```

Expected: manifest and MiniMax assertions fail against the Kling-only metadata.

- [ ] **Step 3: Rename the directory and update only identity/model metadata**

Rename with the filesystem, preserving all source content and history-visible paths:

```text
kling_wb2api_newapi/ -> video_wb2api_newapi/
```

Set:

```javascript
key: "workbuddy-video",
name: "WorkBuddy Video",
version: "1.1.0",
models: ["minimax-video-h3", "kling-video-v3"],
```

Generalize English/Chinese descriptions to video generation through the existing gateway. Keep the known-compatible icon and all handlers unchanged unless a test proves a necessary change.

Set package name to `workbuddy-video-task-plugin` and version to `1.1.0`. Update plugin README title, install/source paths, key, both model names, and version-specific examples.

- [ ] **Step 4: Verify the complete plugin suite**

Run from `video_wb2api_newapi/`:

```bash
npm test
```

Expected: all plugin tests pass with zero failures.

- [ ] **Step 5: Review and checkpoint without Git mutation**

Confirm no handler, polling, proxy, usage, or status-mapping behavior changed and no old public plugin identity remains in current plugin docs/source. Do not rewrite the historical plan merely to erase its original name. Do not commit or push.

---

### Task 3: Synchronize marketplace, release guards, documentation, and archives

**Files:**
- Modify: `index.json`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `.gitignore`
- Modify: `.githooks/check-push.js`
- Modify: `.githooks/check-push.test.js`
- Regenerate: `video_wb2api_newapi/video_wb2api_newapi.zip`
- Regenerate: `jihuarst-image/jihuarst-image.zip`
- Remove superseded artifact: `kling_wb2api_newapi/kling_wb2api_newapi.zip`

**Interfaces:**
- Consumes: final LF-normalized `video_wb2api_newapi/plugin.js` and final image Skill files.
- Produces: one marketplace entry for `workbuddy-video` `1.1.0`, exact new ZIP allowlists, and downloadable archives matching current source byte for byte.

- [ ] **Step 1: Update release-guard tests first**

Change the allowlisted plugin ZIP fixture and descriptions to exactly `video_wb2api_newapi/video_wb2api_newapi.zip`. Retain negative coverage proving the old/non-allowlisted plugin archive is rejected.

Run from the repository root:

```bash
node --test .githooks/check-push.test.js
```

Expected: the renamed allowlist case fails before `.githooks/check-push.js` is updated.

- [ ] **Step 2: Update guards and repository identity references**

In `.githooks/check-push.js`, replace only the old plugin ZIP entry. In `.gitignore`, use:

```text
!video_wb2api_newapi/video_wb2api_newapi.zip
```

Update root `README.md` and `AGENTS.md` project tables, source/download paths, release instructions, model lists, ZIP mapping, and test directory. `CLAUDE.md` remains exactly `@AGENTS.md`.

Verify ignore behavior and tracked paths:

```bash
git check-ignore -v video_wb2api_newapi/video_wb2api_newapi.zip
git check-ignore -v kling_wb2api_newapi/kling_wb2api_newapi.zip
git ls-files
```

Expected: the new ZIP is explicitly unignored/allowlisted; the old path is not a release exception and disappears with the renamed directory.

- [ ] **Step 3: Replace the marketplace release entry**

Set key/name/models/latest/path to the new values, retain `minApiVersion: 1`, `kind: "task"`, the existing base URL and `openai_video`, and include only version `1.1.0`. Calculate the lowercase hash without changing source bytes:

```bash
python -c "from pathlib import Path; import hashlib; p=Path('video_wb2api_newapi/plugin.js'); b=p.read_bytes().replace(b'\r\n', b'\n'); print(hashlib.sha256(b).hexdigest())"
```

Write that value to `versions[0].sha256`. Validate JSON and recompute the hash independently against the exact LF-normalized bytes.

- [ ] **Step 4: Regenerate both distributable ZIPs from exact current sources**

Use the existing local packaging helper after replacing its old plugin project/archive names. Plugin ZIP entries must be exactly:

```text
README.md
package.json
plugin.js
tests/plugin.test.js
```

Image ZIP retains its existing four-file allowlist. Do not include real `config.json`, `.env*`, caches, local state, or nested archives.

- [ ] **Step 5: Run clean-extraction and archive safety verification**

Clean-extract each newly generated archive into a separate new temporary directory and run the plugin/image offline suites from those exports. Compare every archived file byte for byte with source, check entry allowlists and CRCs, reject nested archives, and compare exact non-empty credential values from ignored local configs against every archived byte sequence without printing values.

Run from repository root:

```bash
node --test .githooks/check-push.test.js
```

Run from each source project:

```bash
cd video_wb2api_newapi && npm test
cd jihuarst-image && PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

Expected: all commands exit zero; final counts are reported from actual output.

- [ ] **Step 6: Independent final review and status report**

Give a fresh reviewer the full working-tree diff, approved design, and this plan. Require review of spec compliance, image billing/retry semantics, backup recovery, plugin model forwarding, marketplace hash/path consistency, and archive/guard changes. Fix actionable findings with regression tests and re-review.

Finally inspect `git status --short --branch` and the complete diff. Report actual test commands/counts, archive audits, independent review outcome, and unverified New API marketplace installation/upstream MP4 delivery. Leave all changes uncommitted and unpushed absent new explicit authorization.
