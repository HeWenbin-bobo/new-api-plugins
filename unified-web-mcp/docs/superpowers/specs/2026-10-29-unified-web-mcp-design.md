# Unified Web MCP Gateway Design

**Date:** 2026-10-29  
**Status:** Approved for local prototype

## Goal

Build a local MCP server exposing `unified_web_search` and `unified_web_fetch`. It routes each operation through an ordered provider list, defaulting to `free → minimax → deepseek`, without requiring the model to choose providers or perform fallback.

## Runtime and dependencies

- Windows 11, Node.js 24+, ES modules.
- Official `@modelcontextprotocol/server` and `@modelcontextprotocol/client` packages.
- `zod` for MCP input schemas, `fast-xml-parser` for Bing RSS, `cheerio` for HTML text extraction.
- Node built-in test runner; no TypeScript build step and no test framework.

## Configuration

`config.json` is the only source of service credentials. It contains server limits, independent `routes.search` and `routes.fetch` arrays, and provider settings. `config.example.json` contains placeholders only. Real `config.json` and `node_modules/` are ignored by Git.

MiniMax is launched through stdio using the configured command and arguments. Its environment is constructed from `config.json`; the gateway does not read Claude configuration at runtime. DeepSeek uses `https://api.deepseek.com/v1/tools/search` and `/v1/tools/fetch` with the bearer key from `config.json`.

## Providers

### free

- Search: Bing RSS, returning normalized `sources` entries.
- Fetch: direct HTTP(S) fetch with a browser-like user agent, HTML cleanup through Cheerio, plain-text/Markdown/JSON support, response-size limit and explicit truncation metadata.
- Fetch rejects URLs with credentials and non-HTTP(S) schemes. By default it rejects localhost, private, loopback, link-local and other non-public resolved addresses. Redirects are manually followed and revalidated, with a five-redirect limit.

### minimax

- Lazy stdio MCP client connection; the upstream process is started only when first needed.
- Search tool name comes from configuration (`web_search` locally). Fetch is used only when a fetch tool name is configured.
- Accepts structured content, direct objects, or JSON encoded in MCP text content. Normalizes MiniMax `organic[]` (`title`, `link`, `snippet`, `date`) into `sources[]`.

### deepseek

- Search request: `{query, count, need_content: false}`; maps official `results[]` to `sources[]`.
- Fetch request: `{url}`; maps `{title, content}`.
- Empty search results are successful and do not fall back unless `fallbackOnEmptySearch` is enabled.
- API keys are never included in errors, logs, returned tool content, tests, or documentation.

## Routing

- The router checks provider capability and per-provider/per-operation cooldown before attempting a call.
- Each provider attempt has a timeout; the whole request has a separate total deadline.
- Network errors, timeouts, 401/402/403/408/413/429 and 5xx may fall back. Local input validation errors and caller cancellation do not fall back.
- A provider failure opens a short cooldown so later calls skip it temporarily.
- Successful results include `provider`, `fallback`, `attempts`, and operation-specific data. Errors contain provider names and sanitized messages only.
- Search and fetch routes are independent. MiniMax is skipped for fetch when no upstream fetch tool is configured.

## MCP surface

- `unified_web_search({query, max_results?})`
- `unified_web_fetch({url, max_chars?})`
- `unified_web_status({})` reports enabled/configured providers and cooldown state without secrets.
- Stdio server supports the protocol negotiation provided by the official server package. Logs go to stderr only.

## Verification

- Unit tests cover route fallback, no fallback on valid empty search, cooldown, cancellation/validation behavior, MiniMax and DeepSeek normalization, config validation, and private-URL rejection.
- An MCP integration test spawns the actual server, lists tools and calls status.
- A direct smoke command runs a real search and fetch against configured providers.
- Existing MiniMax credentials are copied into the private config without being printed. DeepSeek remains unconfigured if no key is available; this must not prevent free/MiniMax operation.

## Explicitly deferred

Shared HTTP transport, caching, automatic editing of Claude Code/Codex/WorkBuddy/DSH configuration, DSH native provider bundle, accounting, and AI-based routing.
