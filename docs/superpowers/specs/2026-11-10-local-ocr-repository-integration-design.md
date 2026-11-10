# Local OCR Repository Integration Design

Date: 2026-11-10
Branch: `main` (working-tree integration only; no commit or push authorized)

## Scope

Integrate the user-supplied `local-ocr` New API Task Plugin 0.1.6 and corresponding `local-document-ocr` Agent Skill as the repository's seventh and eighth independent products. Keep the six existing products unchanged.

The approved layout follows the existing products:

- `local-ocr-task-plugin/plugin.js` is the only authoritative plugin source.
- `local-ocr-task-plugin/evals/plugin_fixture.json` remains the contract fixture.
- `local-ocr-task-plugin/README.md`, `CHANGELOG.md`, and `LICENSE` remain project-local.
- `local-document-ocr/SKILL.md`, `scripts/parse.py`, `evals/test_parse.py`, and `assets/` form the Skill directly at its product root.

Remove only the superseded source/archive/index duplicates created by flattening. Preserve the supplied archives until their entries have been checked and the authoritative source has been copied; do not publish the input archives under release names.

## Marketplace contract

Add `local-ocr` to root `index.json` with key, name, icon, bilingual description, both models, native routes, page usage schema, task/provider/transform flags, latest version 0.1.6, API v1 and kind `task`. Set the sole version path to `local-ocr-task-plugin/plugin.js` and SHA-256 to `c10ce313198ff5e4e33b9f6638fbfd44d1901ce745997fdd82261906e24ad60a`, matching the unchanged LF-normalized source. Keep the supplied default private hostname as a deployment example, not as a public endpoint.

Do not add `local-document-ocr` to the Task Plugin marketplace index. Installing the plugin does not install the Skill or an OCR inference service. The plugin requires an independently deployed, authenticated OCR task gateway; no Docker stack or model weights are introduced.

## Verification

Add a dependency-free Node test runner and package metadata to the plugin. It imports `plugin.js` and evaluates every supplied fixture case against the exported hook, including deep expected values and expected errors. This reproduces the fixture offline but does not replace New API's own moejs runtime, host multipart handling, persistence, or billing implementation.

Retain the Skill's documented Python unittest discovery command. Its initial 17-test run passes when run from its Skill root; isolated Python `-I` discovery cannot resolve the local `scripts` package and is not the documented command. Do not rewrite production code to satisfy an unrelated import mode.

The supplied plugin README states 11 fixture cases and real New API tests for both models. Preserve these explicitly as supplied/user-reported evidence, not a fresh verification by this integration. The local environment has no `new-api` executable, and this task does not perform live New API installation or upload documents.

## Distribution and maintenance

Generate exactly:

- `local-ocr-task-plugin/local-ocr-task-plugin.zip`: `plugin.js`, `package.json`, `README.md`, `CHANGELOG.md`, `LICENSE`, and `evals/plugin_fixture.json`, plus the offline test runner.
- `local-document-ocr/local-document-ocr.zip`: `SKILL.md`, `scripts/parse.py`, `assets/config.example.json`, `assets/minimal.png`, and `evals/test_parse.py`, rooted at `local-document-ocr/` for direct skills-directory extraction.

Add only these two paths to `.gitignore` exceptions and `.githooks/check-push.js`; extend the guard's existing release-ZIP fixture array so all allowlisted paths receive the same checks. Use explicit packaging allowlists, verify CRC, entry paths, source-byte equality, clean extraction, offline tests, and exact local credential values without printing them.

Update root `README.md` for three Task Plugins, four Skills, one MCP server, and eight products. Update `AGENTS.md` product tables, marketplace paths, release rules, archive tables, offline commands, and OCR-specific boundaries. Update `docs/PROJECT_STATUS.md` with a new current integration section and eight-product table; do not rewrite historical six-product statements. Keep root `CLAUDE.md` exactly `@AGENTS.md`.

Do not change plugin or Skill runtime behavior, model IDs, version, or source hash. An independently reproduced Skill error-reporting defect may receive a minimal regression-tested correction; retain the public task ID after submission and never add resubmission. Do not commit, tag, push, create a PR, install into New API, or invoke external OCR services without separate explicit authorization.
