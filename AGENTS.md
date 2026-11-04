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
- Keep `node_modules/`, Python caches, logs, `.idea/`, `.remember/`, and other local state out of Git using the root `.gitignore`.
- Keep generated `unified-web-mcp/unified-web-mcp-package/` contents out of Git; distribute any needed ZIP as a GitHub Release asset.
- The Skills' local configurations are machine-specific and must not be replaced by real credentials in examples.

## Changes and verification

- Keep projects independent; avoid root build tooling or dependencies unless a real shared need arises.
- Preserve the existing plugin, Skill, and MCP behavior when changing repository documentation or release metadata.
- Run relevant offline tests for changed projects. For documentation-only changes, at minimum validate JSON parsing, plugin source hash, local links, and the absence of ignored or sensitive staged files.
- `CLAUDE.md` must contain only `@AGENTS.md`; keep all repository instructions here.
