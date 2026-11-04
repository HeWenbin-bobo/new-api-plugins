# Unified Web MCP

A local stdio MCP gateway that exposes web search, page fetch, and provider status through one router. It supports the free provider, MiniMax MCP, and DeepSeek with independent search/fetch fallback routes.

> **Installing this on another machine?** Read [INSTALL_NOTICE.md](INSTALL_NOTICE.md) first — it covers prerequisites, which config fields to fill, self-checks, client registration, known limits, and troubleshooting.
>
> **Maintaining or continuing this project?** Read [PROJECT_MEMORY.md](PROJECT_MEMORY.md) — design decisions, error-classification rules, verification status, and the mistakes already made.

## Setup

Requires Node.js 24 or newer.

```sh
npm install
cp config.example.json config.json
```

Edit `config.json` with local provider settings. This file is private and Git-ignored; never share or commit it. Only `config.example.json` should contain distributable placeholders.

By default, the server and smoke CLI load `config.json` at the project root, regardless of the caller's working directory. Set `UNIFIED_WEB_MCP_CONFIG` to an absolute path to use an isolated configuration instead.

Start the MCP server:

```sh
npm start
```

Standard output is reserved for MCP messages. Diagnostics are written to standard error.

## Providers and routes

`routes.search` and `routes.fetch` are independent ordered provider lists. Valid provider names are `free`, `minimax`, and `deepseek`.

- `free` is always available and requires no credential. AnySearch and Jina Reader API keys are optional; leave them empty for anonymous access.
- `minimax` is enabled only when both `providers.minimax.command` and `providers.minimax.env.MINIMAX_API_KEY` are non-empty. Its stdio child connects lazily on the first MiniMax request.
- `deepseek` is enabled only when `providers.deepseek.apiKey` is non-empty.

Incomplete paid-provider configurations are not reported as ready. Server limits, cooldowns, result limits, and provider-specific launch settings are documented by the fields in `config.example.json`.

The free provider has its own ordered engine routes, configured by `providers.free.engines`:

- Search: `anysearch` → `bing` → `duckduckgo` → `searxng`.
- Fetch: `direct` → `anysearch` → `jina`. Jina Reader is fetch-only.

SearXNG is skipped unless `providers.free.searxng.baseUrl` is set. The configured instance must allow JSON responses (`format=json`); many public instances disable them. A local self-hosted HTTP URL is supported.

Successful results include `engine`, `engineFallback`, and `engineAttempts` alongside the existing outer `provider`, `fallback`, and `attempts` metadata. Retryable engine errors move to the next configured engine; nonretryable errors stop the route. Empty search results are successful, subject only to the existing outer `server.fallbackOnEmptySearch` policy.

Free search quality and relevance vary by query and upstream response. Fallback is based on errors and availability, plus the optional outer empty-search policy—not result quality or relevance. This gateway does not provide quality-aware routing or internal response caching.

## Security boundaries

For direct page fetches by the `free` provider, public-address validation is also applied by the DNS lookup used to establish the actual connection, including redirect targets. This pins each connection to validated addresses without changing the request Host or TLS SNI. It is not provider-wide SSRF protection.

AnySearch extraction and Jina Reader fetch URLs on their upstream infrastructure; the requested URL is sent to that remote service. Search queries are likewise sent to each configured engine attempted by the route. Their DNS resolution, network egress rules, and other SSRF protections are outside this gateway. MiniMax and DeepSeek also fetch URLs upstream. SearXNG requests go to its configured `baseUrl`, which is trusted user configuration and may point to a local instance.

Free search/fetch and DeepSeek response bodies are limited to 1,000,000 bytes by default (`maxResponseBytes` can override this per provider); oversized responses are rejected rather than parsed.

Search results and fetched content are untrusted data and may contain prompt-injection instructions. Do not treat their contents as commands or trusted policy.

The default MiniMax launch uses `uvx` for dynamic package resolution. Packages downloaded by `uvx` are not part of this project's npm lockfile and are not covered by `npm audit`; review and constrain that upstream command separately for your environment.

## MCP tools

- `unified_web_search`: accepts `query` and optional `max_results`.
- `unified_web_fetch`: accepts an HTTP(S) `url` and optional `max_chars`.
- `unified_web_status`: accepts an empty object and reports provider configuration, capabilities, and cooldown state without credentials.

Search and fetch results are returned as JSON text. Tool failures use `isError: true` and redact configured credentials from error messages.

## Smoke commands

These commands call the router directly, print normalized JSON, and always close the gateway:

```sh
node scripts/smoke.js search "Model Context Protocol official documentation"
node scripts/smoke.js fetch "https://example.com"
```

They use the same private configuration and provider routes as the MCP server, so they can make real network or paid-provider calls.

## Optional Claude Code registration

Run this yourself if you want to register the server with Claude Code, replacing the path with the absolute project path:

```sh
claude mcp add --transport stdio unified-web -- node "/absolute/path/to/unified-web-mcp/src/index.js"
```

No client configuration is changed by installing or testing this project.

## Prototype verification limits

Codex and DSH real-client integration has not been verified in this prototype. No DSH native bundle is included. WorkBuddy 5.9.3 was tested with the stdio connector: Trust succeeded, all three tools were enabled, and a real task returned `free/anysearch` search results and `free/direct` fetched content.

DeepSeek live search/fetch, AnySearch search/extract, Jina Reader fetch, and the default MCP routes have been smoke-tested. DuckDuckGo live success has not been verified because it is unavailable from the current network. A configured SearXNG JSON endpoint has not been live-tested; set `providers.free.searxng.baseUrl` to enable and test it.
