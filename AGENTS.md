# Repository Guide

## Purpose

This is one public repository containing four independently distributed tools:

- `kling_wb2api_newapi/`: a New API Task Plugin, distributed through the root `index.json`.
- `jihuarst-image/`: an Agent Skill, installed into a client's skills directory.
- `zaiwen-image-generation/`: an Agent Skill, installed into a client's skills directory.
- `unified-web-mcp/`: an MCP server, configured in an MCP client.

Only the Task Plugin belongs in the New API marketplace. Never add Skills or MCP servers to `index.json`.

## Repository and installation rules

- Keep the current four top-level project directories. Do not move `kling_wb2api_newapi/plugin.js` to the repository root.
- New API does **not** recursively scan GitHub repositories. The root `index.json` is the marketplace entry point and must list every installable Task Plugin explicitly.
- Add a source using the raw index URL, not the repository homepage:

  `https://raw.githubusercontent.com/HeWenbin-bobo/new-api-plugins/main/index.json`

- A version `path` is resolved relative to the index URL. Keep it relative and on the same origin; the current path is `kling_wb2api_newapi/plugin.js`.
- New API requires Task Plugin API v1 support. Plugin installation and channel configuration are administrator trust decisions; review source before activation.
- Installing the New API plugin does not install the Skills or MCP server. Follow each project's own README or SKILL.md for those.

## Plugin release rules

When releasing `workbuddy-kling`:

1. Run the plugin's offline tests.
2. Increment `meta.version` in `kling_wb2api_newapi/plugin.js` and the corresponding `package.json` version using semantic versioning.
3. Add a new entry to `index.json` under `plugins[0].versions`; do not overwrite an existing version with different source.
4. Set `latest` to the new version and update `sha256` to the lowercase SHA-256 hash of the exact LF-normalized `plugin.js` bytes. `.gitattributes` preserves this format across Windows checkouts.
5. Keep `key`, `models`, `protocols`, `minApiVersion`, and `kind` consistent with the plugin manifest and API contract.
6. Validate that the raw index and source URLs return HTTP 200 after pushing. Do not claim marketplace installation was tested unless it was exercised in New API itself.

Releases need immutable versioned source paths if multiple versions are retained. Until a second release exists, the single current path is sufficient.

## Secrets and local artifacts

- Never commit `config.json`, `config.local.json`, `.env*`, API keys, access tokens, or credentials. Only `*.example.json` files with empty placeholders are distributable.
- Do not print secrets while auditing. Check the staged diff, not only the working tree.
- Before publication, verify real local configs are ignored and untracked, then compare their non-empty credential values against every tracked Git blob; check all history and compare the remote tree after pushing.
- Suppress credential values in audit output. Classify obvious test fixtures separately, and do not claim absolute absence of unknown historical secrets.
- Do not stringify upstream exceptions or response bodies into logs without sanitization; they may echo credentials, authorization headers, request payloads, or large media inputs. Reuse each project's existing redaction path and cover new error paths with an offline test.
- Keep `node_modules/`, Python caches, logs, `.idea/`, `.remember/`, and other local state out of Git using the root `.gitignore`.
- Keep generated `unified-web-mcp/unified-web-mcp-package/` contents out of Git; distribute any needed ZIP as a GitHub Release asset.
- The Skills' local configurations are machine-specific and must not be replaced by real credentials in examples.

## Git and GitHub workflow

- Commit, tag, push, or rewrite history only when the user explicitly requests it. Force-pushing, rebasing published work, and hard resets require specific authorization.
- Use Conventional Commit subjects (`feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`) and describe the user-visible change. Keep each commit focused; separate source changes from regenerated artifacts.
- Before committing, inspect `git status`, the complete staged file list, `git diff --cached --check`, and the staged sensitive-data audit. Never rely on ignore rules alone.
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
- Never turn failed, skipped, or unavailable work into a successful or empty result. Preserve explicit failure states in return values and user-visible output; use bounded retries with timeouts and backoff for transient errors, and handle fatal or invalid-input errors before generic retryable ones.
- When adding or changing cache or resume behavior, bind entries to the source bytes and behavior-affecting configuration, reject stale or mismatched results, and write replacement state atomically so failure preserves the last valid result. Test both first-time creation and rejection of an outdated result.
- Run tests from each project's own directory:
  - `kling_wb2api_newapi/`: `npm test`
  - `jihuarst-image/`: `PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v`
  - `unified-web-mcp/`: `npm test` (Node.js 24+; use `npm ci` in a clean checkout)
- Keep automated tests offline with temporary fake configurations and loopback mock services; never require real credentials or paid API calls.
- Read the final test summary and exit code. Expected failures printed by mock scenarios are not suite failures; do not infer success from selected log lines.
- For release verification, test a clean export of the exact staged or committed tree so ignored local configuration and generated artifacts cannot hide defects.
- Run relevant offline tests for changed projects. For documentation-only changes, at minimum validate JSON parsing, plugin source hash, local links, and the absence of ignored or sensitive staged files.
- Report the commands run, final counts, and any unverified scope with its reason. Never present design expectations or partial checks as completed verification.
- `CLAUDE.md` must contain only `@AGENTS.md`; keep all repository instructions here.
