# Unified Web MCP Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a runnable local MCP gateway that unifies free web access, the existing MiniMax MCP, and DeepSeek Search/Fetch APIs with deterministic fallback.

**Architecture:** One stdio MCP server exposes two web tools and a status tool. A provider-independent router invokes small adapters, applies timeouts and cooldowns, and normalizes outputs. All credentials and provider launch settings live in `config.json`.

**Tech Stack:** Node.js 24 ES modules, official MCP server/client packages, Zod, Cheerio, fast-xml-parser, `node:test`.

## Global Constraints

- Project root: `D:\Claude\unified-web-mcp`.
- Do not modify any existing client configuration or restart any existing client/process.
- Never print or commit real credentials. `config.json` is private; only `config.example.json` contains placeholders.
- Use official DeepSeek endpoints `POST /v1/tools/search` and `POST /v1/tools/fetch` at `https://api.deepseek.com`.
- Use only stderr for server diagnostics; stdout is reserved for MCP.
- No cache, HTTP transport, automatic client registration, DSH bundle, or AI routing in this prototype.

---

### Task 1: Project, configuration, and provider contracts

**Files:**
- Create: `package.json`, `.gitignore`, `config.example.json`
- Create: `src/config.js`, `src/errors.js`, `test/config.test.js`

**Interfaces:**
- Produces: `loadConfig(path)` returning a validated new configuration object.
- Produces: `ProviderError(message, {provider, retryable, status})` and `InputError(message)`.
- Config shape: `{server, routes, providers:{free,minimax,deepseek}}`.

- [ ] **Step 1: Write configuration tests**

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { validateConfig } from '../src/config.js';

test('rejects an unknown route provider', () => {
  assert.throws(() => validateConfig({ routes: { search: ['unknown'], fetch: [] } }), /unknown/);
});

test('applies independent default routes', () => {
  const config = validateConfig({});
  assert.deepEqual(config.routes.search, ['free', 'minimax', 'deepseek']);
  assert.deepEqual(config.routes.fetch, ['free', 'minimax', 'deepseek']);
});
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `npm test`
Expected: failure because `src/config.js` does not exist.

- [ ] **Step 3: Implement validation and package setup**

```js
export function validateConfig(input = {}) {
  const config = structuredClone(input);
  config.server = {
    providerTimeoutMs: 12000,
    requestTimeoutMs: 40000,
    cooldownMs: 30000,
    maxSearchResults: 8,
    maxFetchChars: 20000,
    fallbackOnEmptySearch: false,
    ...config.server,
  };
  config.routes = {
    search: ['free', 'minimax', 'deepseek'],
    fetch: ['free', 'minimax', 'deepseek'],
    ...config.routes,
  };
  config.providers = { free: {}, minimax: {}, deepseek: {}, ...config.providers };
  for (const name of [...config.routes.search, ...config.routes.fetch]) {
    if (!['free', 'minimax', 'deepseek'].includes(name)) throw new Error(`Unknown provider: ${name}`);
  }
  return config;
}
```

Add validation for positive integer limits, non-empty route arrays, MiniMax command/tool settings, and DeepSeek base URL. `loadConfig` must read UTF-8 JSON and return `validateConfig` output without mutating the parsed input. Package scripts are `start: node src/index.js`, `test: node --test`, and `smoke: node scripts/smoke.js`.

- [ ] **Step 4: Run tests**

Run: `npm test`
Expected: configuration tests pass.

### Task 2: Router and deterministic fallback

**Files:**
- Create: `src/router.js`, `test/router.test.js`

**Interfaces:**
- Consumes: validated config and provider map.
- Produces: `createRouter(config, providers)` with `search({query,maxResults})`, `fetch({url,maxChars})`, `status()`, and `close()`.
- Provider adapter shape: `{search?(args, context), fetch?(args, context), close?()}`.

- [ ] **Step 1: Write router tests**

```js
test('falls back and reports attempts', async () => {
  const router = createRouter(baseConfig(), {
    free: { search: async () => { throw new ProviderError('down', {provider:'free'}); } },
    minimax: { search: async () => ({ sources: [{title:'ok',url:'https://example.com',snippet:''}] }) },
  });
  const result = await router.search({query:'test'});
  assert.equal(result.provider, 'minimax');
  assert.equal(result.fallback, true);
  assert.deepEqual(result.attempts.map(x => x.provider), ['free', 'minimax']);
});

test('empty search is a valid result by default', async () => {
  const router = createRouter(baseConfig(), {
    free: { search: async () => ({sources: []}) },
    minimax: { search: async () => { throw new Error('must not run'); } },
  });
  assert.deepEqual((await router.search({query:'none'})).sources, []);
});
```

Add tests proving cooldown skips a failed provider, unsupported fetch capability is skipped, and `InputError` is returned without trying the next provider.

- [ ] **Step 2: Run router tests and confirm they fail**

Run: `node --test test/router.test.js`
Expected: failure because `src/router.js` does not exist.

- [ ] **Step 3: Implement router**

Implement one private `execute(operation, args)` used by both public operations. It must validate non-empty search queries and HTTP(S) fetch URLs, enforce per-attempt and total deadlines, skip cooldowns, record sanitized attempts, preserve valid empty search results, and optionally fall back on empty results when configured. Return a new result object with routing metadata; never mutate provider responses. `close()` closes all adapters and ignores duplicate close calls.

- [ ] **Step 4: Run router tests**

Run: `node --test test/router.test.js`
Expected: all router tests pass.

### Task 3: Real provider adapters and HTTP safety

**Files:**
- Create: `src/http.js`, `src/providers/free.js`, `src/providers/minimax.js`, `src/providers/deepseek.js`
- Create: `test/providers.test.js`

**Interfaces:**
- Consumes: provider configuration and router context `{signal}`.
- Produces: `createFreeProvider(config)`, `createMiniMaxProvider(config)`, `createDeepSeekProvider(config)`.
- Search result: `{sources:[{title,url,snippet,publishedAt?}]}`.
- Fetch result: `{title,url,content,truncated}`.

- [ ] **Step 1: Write normalization and safety tests**

```js
test('normalizes MiniMax organic results', () => {
  assert.deepEqual(normalizeMiniMaxSearch({organic:[{title:'A',link:'https://a.test',snippet:'B',date:''}]}).sources[0], {
    title:'A', url:'https://a.test', snippet:'B', publishedAt:null,
  });
});

test('blocks local fetch targets', async () => {
  await assert.rejects(() => assertPublicUrl('http://127.0.0.1/admin'), /private|local|public/i);
});

test('normalizes DeepSeek search results', () => {
  const result = normalizeDeepSeekSearch({results:[{title:'A',url:'https://a.test',summary:'S',date:null}]});
  assert.equal(result.sources[0].snippet, 'S');
});
```

- [ ] **Step 2: Run provider tests and confirm they fail**

Run: `node --test test/providers.test.js`
Expected: failure because provider modules do not exist.

- [ ] **Step 3: Implement adapters**

Use built-in `fetch` with caller signals. Parse Bing RSS using `XMLParser`, using `item.link/title/description/pubDate`. Parse MiniMax MCP `structuredContent`, direct result objects, or JSON text blocks. DeepSeek uses bearer authorization from config and official request/response fields. Direct free fetch validates every redirect, limits downloaded bytes, strips executable/non-content HTML elements, and reports truncation.

- [ ] **Step 4: Run all unit tests**

Run: `npm test`
Expected: all unit tests pass.

### Task 4: MCP entry point, integration smoke test, and usage documentation

**Files:**
- Create: `src/index.js`, `scripts/smoke.js`, `test/mcp.test.js`, `README.md`

**Interfaces:**
- MCP tools: `unified_web_search`, `unified_web_fetch`, `unified_web_status`.
- CLI: `node scripts/smoke.js search "query"` and `node scripts/smoke.js fetch "https://example.com"`.

- [ ] **Step 1: Write MCP integration test**

Spawn `src/index.js` with a test config containing only fake providers disabled, connect with the official MCP client, call `listTools()`, assert all three names are present, call status, and assert no key material appears. Close client and child transport in `finally`.

- [ ] **Step 2: Run integration test and confirm it fails**

Run: `node --test test/mcp.test.js`
Expected: failure because the entry point does not exist.

- [ ] **Step 3: Implement server and smoke command**

Use `McpServer.registerTool` and `serveStdio` from the official packages. Register Zod input schemas, return JSON text content, set `isError:true` for tool failures, and sanitize errors. The smoke command invokes the router directly and prints JSON without config or credentials.

- [ ] **Step 4: Run complete automated verification**

Run: `npm test`
Expected: all unit and MCP integration tests pass.

- [ ] **Step 5: Run local real-provider smoke checks**

Run: `node scripts/smoke.js search "Model Context Protocol official documentation"`
Expected: successful normalized sources with actual provider metadata.

Run: `node scripts/smoke.js fetch "https://example.com"`
Expected: successful page content with actual provider metadata.

- [ ] **Step 6: Review changed files**

Check for `TODO`, skipped tests, stub providers, debug logging, hardcoded credentials, and stdout logging in the MCP server. Report any unrun real-provider check explicitly.

## Execution

Use subagent-driven implementation with a separate review pass. The parent session will populate the private MiniMax credential from the existing local configuration without displaying it, then run verification. No Git commit is possible because `D:\Claude` is not a Git repository; do not initialize one unless the user asks.
