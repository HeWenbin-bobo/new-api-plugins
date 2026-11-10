# Local OCR Repository Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Integrate the supplied Local OCR Task Plugin and Skill using the repository's standard product, marketplace, testing, documentation, and archive conventions.

**Architecture:** Flatten the two products without changing their runtime source. Add only a small Node fixture runner for the plugin, then synchronize the root index, public documentation, exact release archive allowlists, and verification status.

**Tech Stack:** ECMAScript modules, Node built-in test/assert modules, Python 3.9+ standard library, JSON, ZIP.

## Global Constraints

- Preserve `local-ocr` version 0.1.6 and plugin LF SHA-256 `c10ce313198ff5e4e33b9f6638fbfd44d1901ce745997fdd82261906e24ad60a`.
- Only `local-ocr` enters root `index.json`; the Skill never enters the marketplace.
- Keep the six existing products and root `CLAUDE.md` unchanged.
- No live New API installation, document upload, external OCR invocation, commit, or push is authorized.

### Task 1: Flatten sources and establish offline plugin tests

**Files:**
- Move: `local-ocr-task-plugin/plugins/tasks/local-ocr/0.1.6/plugin.js` → `local-ocr-task-plugin/plugin.js`
- Create: `local-ocr-task-plugin/package.json`
- Create: `local-ocr-task-plugin/tests/plugin.test.js`
- Move: Skill contents from nested `local-document-ocr/local-document-ocr/` to `local-document-ocr/`

**Interfaces:** `tests/plugin.test.js` imports all fixture hook names from `../plugin.js`, reads `evals/plugin_fixture.json`, and supplies `assert.deepEqual` for expected values and `assert.throws` for expected errors.

- [x] Check both supplied ZIPs for CRC, safe paths and nested archives before removing them.
- [x] Copy authoritative source bytes to the approved locations and compare their hashes.
- [x] Run `npm test` from `local-ocr-task-plugin/`; require all 11 supplied fixture cases to pass, no skip/todo and exit 0.
- [x] Run `PYTHONIOENCODING=utf-8 python -m unittest discover -s evals -p 'test_*.py' -v` from `local-document-ocr/`; require 17 passing tests and exit 0.

### Task 2: Synchronize the marketplace and repository documentation

**Files:**
- Modify: `index.json`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `local-ocr-task-plugin/README.md`
- Modify: `docs/PROJECT_STATUS.md`

**Interfaces:** Root index version path is exactly `local-ocr-task-plugin/plugin.js`; public installation and archive links resolve locally.

- [x] Merge the OCR manifest fields from the supplied index while updating the path and retaining the verified hash.
- [x] Describe eight products: three Task Plugins, four Skills, one MCP server. Do not add the Skill to the market index.
- [x] Document `npm test` for the plugin and the Skill's existing unittest discovery.
- [x] Distinguish fresh offline checks from supplied real New API reports and hardware-specific timing observations.
- [x] Add durable OCR task ID, same-origin credential, output, artifact and packaging rules to `AGENTS.md` without rewriting history.

### Task 3: Extend archive policy, rebuild releases and verify

**Files:**
- Modify: `.gitignore`
- Modify: `.githooks/check-push.js`
- Modify: `.githooks/check-push.test.js`
- Create: `local-ocr-task-plugin/local-ocr-task-plugin.zip`
- Create: `local-document-ocr/local-document-ocr.zip`

**Interfaces:** Both exact ZIP paths join the existing `RELEASE_ZIPS` set and offline `releaseZips` fixture array; no broad archive allowlist is added.

- [x] Build each archive from explicit final-source allowlists, with `local-document-ocr/` as the Skill ZIP root.
- [x] Verify CRC, safe entry names, absence of nested archives/private state, exact source-byte equality and exact local credential scans without printing values.
- [x] Test clean extraction: plugin fixture tests and the final Skill 22-test suite (17 supplied tests plus five review regressions).
- [x] Run `node --test .githooks/check-push.test.js` from the root and record the final counts and exit code.
- [x] Validate JSON, plugin LF hash, root index paths/models/routes, local documentation links, Git ignore/tracking boundaries and `git diff --check`.
- [x] Inspect final changes for placeholders, skipped/only tests, debug output, credentials and changes to existing products. Leave all work uncommitted.
- [x] Receive the independent read-only review, evaluate every concrete finding against the source and tests, fix any confirmed issue, and rerun affected checks before final reporting.
