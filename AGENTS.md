# Repository Guide

## Purpose

This is one public repository containing five independently distributed tools:

- `video_wb2api_newapi/`: a New API Task Plugin, distributed through the root `index.json`.
- `jihuarst-image/`: an Agent Skill, installed into a client's skills directory.
- `jihuarst-video/`: an Agent Skill, installed into a client's skills directory.
- `zaiwen-image-generation/`: an Agent Skill, installed into a client's skills directory.
- `unified-web-mcp/`: an MCP server, configured in an MCP client.

Only the Task Plugin belongs in the New API marketplace. Never add Skills or MCP servers to `index.json`.

## Project map and progress

- Keep repository-wide design and implementation records in `docs/superpowers/specs/` and `docs/superpowers/plans/`. Existing project-local historical documents may remain with their project; do not move or duplicate them merely for naming consistency.
- `docs/PROJECT_STATUS.md` is the cross-project handoff and verification snapshot. Update it after a meaningful completed milestone or published release; keep durable maintenance rules in this file rather than mixing them into the status history.
- Root files have fixed roles: `README.md` is the user/install guide, `index.json` is the Task Plugin marketplace index, `.githooks/` contains publication guards, and `.gitattributes` preserves release-source normalization.
- Each product directory owns its source, tests, public documentation, and exact allowlisted client ZIP. Keep real local configuration and generated verification material outside Git; `.omc/` is ignored session state, not an authoritative project document.
- Do not reorganize the five product trees or create parallel source/archive locations for cosmetic cleanup. Use focused documentation and path updates when the public organization changes.

## Repository and installation rules

- Keep the current five top-level project directories. Do not move `video_wb2api_newapi/plugin.js` to the repository root.
- New API does **not** recursively scan GitHub repositories. The root `index.json` is the marketplace entry point and must list every installable Task Plugin explicitly.
- Add a source using the raw index URL, not the repository homepage:

  `https://raw.githubusercontent.com/HeWenbin-bobo/new-api-plugins/main/index.json`

- A version `path` is resolved relative to the index URL. Keep it relative and on the same origin; the current path is `video_wb2api_newapi/plugin.js`.
- Preserve the New API-selected model in upstream requests (`ctx.upstreamModel || ctx.model`). Adding a model requires synchronized manifest, protocol, index, documentation, and forwarding-test updates; do not silently substitute another model.
- New API requires Task Plugin API v1 support. Plugin installation and channel configuration are administrator trust decisions; review source before activation.
- Installing the New API plugin does not install the Skills or MCP server. Follow each project's own README or SKILL.md for those.

## Plugin release rules

When releasing `workbuddy-video`:

1. Run the plugin's offline tests.
2. Increment `meta.version` in `video_wb2api_newapi/plugin.js` and the corresponding `package.json` version using semantic versioning.
3. Replace `plugins[0].versions` in `index.json` with a single entry for the new release, removing superseded versions. Never reuse an existing version number for different source.
4. Set `latest` to the new version and update `sha256` to the lowercase SHA-256 hash of the exact LF-normalized `plugin.js` bytes. `.gitattributes` preserves this format across Windows checkouts.
5. Keep `key`, `models`, `protocols`, `minApiVersion`, and `kind` consistent with the plugin manifest and API contract.
6. Validate that the raw index and source URLs return HTTP 200 after pushing. Do not claim marketplace installation was tested unless it was exercised in New API itself.

The marketplace intentionally exposes only the latest release through the single current source path; older source remains in Git history but is not listed for installation.

## Secrets and local artifacts

- Never commit `config.json`, `config.local.json`, `.env*`, API keys, access tokens, or credentials. Only `*.example.json` files with empty placeholders are distributable.
- Do not print secrets while auditing. Check the staged diff, not only the working tree.
- Before publication, verify real local configs are ignored and untracked, then compare their non-empty credential values against every tracked Git blob; check all history and compare the remote tree after pushing.
- Suppress credential values in audit output. Classify obvious test fixtures separately, and do not claim absolute absence of unknown historical secrets.
- Do not stringify upstream exceptions or response bodies into logs without sanitization; they may echo credentials, authorization headers, request payloads, or large media inputs. Reuse each project's existing redaction path and cover new error paths with an offline test.
- Keep `node_modules/`, Python caches, logs, `.idea/`, `.remember/`, and other local state out of Git using the root `.gitignore`.
- Keep generated `unified-web-mcp/unified-web-mcp-package/` contents other than its allowlisted client ZIP, and all non-allowlisted `*.zip`, `*.7z`, `*.rar`, `*.tar`, and `*.tgz` archives, out of Git. Track only the five client ZIPs listed below for direct download.
- The Skills' local configurations are machine-specific and must not be replaced by real credentials in examples.
- Never include `config.json`, `config.local.json`, `.env*`, real credentials, caches, local state, or nested archives in distributable ZIPs. Include only example configurations with empty credentials; after packaging, inspect every entry and scan all archived bytes for exact non-empty credential values from local configs without printing those values.

## Git and GitHub workflow

- Commit, tag, push, or rewrite history only when the user explicitly requests it. Force-pushing, rebasing published work, and hard resets require specific authorization.
- Use Conventional Commit subjects (`feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`) and describe the user-visible change. For nontrivial commits, add a concise body covering the reason, important behavior changes, verification performed, and relevant limitations; a subject alone is not a substitute for that context. Keep each commit focused; separate source changes from regenerated artifacts.
- Before committing, inspect `git status`, the complete staged file list, `git diff --cached --check`, and the staged sensitive-data audit. Never rely on ignore rules alone; ignored files can still be force-added, and deleting a leaked file in a later commit does not remove it from history.
- The checked-in `.githooks/pre-push` wrapper must remain the final local defense. After cloning or changing machines, run `git config core.hooksPath .githooks`; verify with `git config --get core.hooksPath`. The hook requires Node.js, scans every outgoing commit (including staged content on an unborn branch), compares exact non-empty values from ignored local configs, blocks private config paths and non-allowlisted archives, and never prints credential values. The five allowlisted ZIPs are parsed offline with entry, path, nested-archive, and expansion limits; their contents undergo the same private-path and exact-credential checks, and malformed or unsupported ZIPs fail closed.
- Test the guard with `node --test .githooks/check-push.test.js`. Keep it offline and fail closed. Do not use `--no-verify`, weaken a rule, or suppress a finding to make a real push succeed; fix the source or remove the content from every outgoing commit. This heuristic guard cannot prove the absence of unknown secrets.
- Treat `--all` history findings and outgoing-push findings separately. The current guard also applies current archive-path policy to historical paths, so a formerly allowlisted but now removed release ZIP can block `--all`; record the exact path and reason. Do not mistake that known limitation for an outgoing-push failure, bypass it, or rewrite published history without explicit authorization. A normal pre-push pass does not prove all historical blobs are safe.
- A passing local hook is necessary but not sufficient. Before pushing, verify the remote and branch and inspect `git diff --name-only origin/main...HEAD`; after pushing, compare the GitHub tree with the local commit. GitHub push protection, when available and enabled, is an additional service-side layer rather than a replacement for this check.
- After changing ignore rules, verify representative paths with `git check-ignore -v` and `git ls-files`; test nested paths explicitly because `*` and `**` have different recursion behavior. Removing a file from the index does not delete its local copy.
- Check binary and generated-file sizes before staging. Keep tracked files below a 95 MB safety limit; use Git LFS, a GitHub Release asset, or an external link rather than approaching GitHub's 100 MB file limit.
- This repository is public. Before pushing, verify the remote and branch, confirm authorization for included third-party content, and treat every current and historical object as publicly distributable.
- If a real credential is ever published, revoke or rotate it immediately. Deleting it from the latest revision does not remove it from history; history rewriting requires explicit authorization and does not replace revocation.
- Regenerate distributable artifacts from the exact source being released and verify that they match. Keep one authoritative copy and do not let stale or duplicate artifacts silently replace current source.

## Changes and verification

- Keep projects independent; avoid root build tooling or dependencies unless a real shared need arises.
- Make the smallest task-scoped change. Do not add parallel implementations or bundle unrelated refactoring and cleanup.
- Preserve the existing plugin, Skill, and MCP behavior when changing repository documentation or release metadata.
- When documentation conflicts with executable behavior, verify the actual behavior and correct the stale side in the same change; never import another project's status or conclusions.
- When changing commands, options, defaults, or configuration fields, synchronize the relevant README, `SKILL.md`, example configuration, and tests.
- Use UTF-8 and focused edits; preserve the LF normalization enforced by `.gitattributes` for executable sources and release metadata.
- Use explicit exceptions for production runtime validation; reserve `assert` for tests and offline self-checks.
- Do not add telemetry, automatic updates, crash reporting, implicit downloads, or other undeclared network destinations. Before real paid API calls or external uploads, confirm the requested scope, data leaving the machine, and likely cost; use the smallest useful validation first.
- For real video verification, fix one explicit HTTPS base URL and model per run unless broader fallback testing is authorized. Distinguish submission, task completion, MP4 download, and local validation in the result; only the complete path proves end-to-end delivery. Keep paid outputs and sensitive local configuration under ignored `.omc/artifacts/`, never in release ZIPs or public status documents. Record file size, SHA-256, and MP4 signature checks; disclose when codec, duration, decoding, or visual-quality verification is unavailable. Do not publish real task IDs, credentials, or paid media.
- Keep API reference facts layered: declared interface contract, observed gateway behavior, client-side transformation, and local delivery result are separate claims. Date live observations and scope them to the tested endpoint, model, and deployment. Third-party API or frontend notes are hypotheses to verify, never evidence that overrides this gateway's measured behavior; do not infer transparency, output format, size, billing, or streaming support from another deployment.
- Never turn failed, skipped, or unavailable work into a successful or empty result. Preserve explicit failure states in return values and user-visible output; use bounded retries with timeouts and backoff for transient errors, and handle fatal or invalid-input errors before generic retryable ones.
- For Jihuarst Image, success means all requested images are completely saved locally. Retry every remaining selected URL/model combination after generation, response, download, validation, count, or local-output failure; disclose that post-artifact retries may be billed again. Validate local inputs before paid requests, never expand explicit `--base-url`/`--model` restrictions, preserve atomic recovery, and sanitize every error path.
- For asynchronous Jihuarst Video, do not create a replacement paid task after obtaining a task ID merely because polling has a nonterminal error or a completed task cannot be downloaded. Preserve the original task information and explicit failure. Do not transfer the image Skill's exhaustive-retry policy to video tasks.
- When adding or changing cache or resume behavior, bind entries to the source bytes and behavior-affecting configuration, reject stale or mismatched results, and write replacement state atomically so failure preserves the last valid result. Test both first-time creation and rejection of an outdated result.
- After every upgrade to a distributable project, regenerate its client ZIP without a separate reminder; packaging is part of the upgrade, not an optional follow-up:
  - `video_wb2api_newapi/` → `video_wb2api_newapi/video_wb2api_newapi.zip`
  - `jihuarst-image/` → `jihuarst-image/jihuarst-image.zip`
  - `jihuarst-video/` → `jihuarst-video/jihuarst-video.zip`
  - `zaiwen-image-generation/` → `zaiwen-image-generation/zaiwen-image-generation.zip`
  - `unified-web-mcp/` → `unified-web-mcp/unified-web-mcp-package/unified-web-mcp-<version>.zip`
  Track only these five exact ZIP paths in Git; all other archives remain blocked. Use an explicit file allowlist, verify a clean extraction passes the project's offline tests, compare archived files byte for byte with the current source, and run the archive-content credential and safety audit before staging.
- Run tests from each project's own directory:
  - Repository push guard: `node --test .githooks/check-push.test.js` (run from the repository root)
  - `video_wb2api_newapi/`: `npm test`
  - `jihuarst-image/`: `PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v`
  - `jihuarst-video/`: `PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v`
  - `unified-web-mcp/`: `npm test` (Node.js 24+; use `npm ci` in a clean checkout)
- Keep automated tests offline with temporary fake configurations and loopback mock services; never require real credentials or paid API calls.
- Invoke discovery commands from the owning project directory with its documented relative test path. On Windows, prefix Python test commands with `PYTHONIOENCODING=utf-8`; console mojibake alone is not a test failure, but an import/discovery error is not a valid test result.
- Read the final test summary and exit code. Expected failures printed by mock scenarios are not suite failures; do not infer success from selected log lines.
- For release verification, test a clean export of the exact staged or committed tree so ignored local configuration and generated artifacts cannot hide defects.
- Run relevant offline tests for changed projects. For documentation-only changes, at minimum validate JSON parsing, plugin source hash, local links, and the absence of ignored or sensitive staged files.
- Report the commands run, final counts, and any unverified scope with its reason. Never present design expectations or partial checks as completed verification.
- `CLAUDE.md` must contain only `@AGENTS.md`; keep all repository instructions here.
