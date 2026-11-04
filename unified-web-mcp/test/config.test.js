import test from 'node:test';
import assert from 'node:assert/strict';
import { validateConfig, loadConfig } from '../src/config.js';
import { ProviderError, InputError } from '../src/errors.js';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('rejects non-object config and section blocks', () => {
  for (const value of [null, [], 'bad', 42, true]) {
    assert.throws(() => validateConfig(value), /config.*object/i);
  }
  for (const section of ['server', 'routes', 'providers']) {
    for (const value of [null, [], 'bad', 42]) {
      assert.throws(
        () => validateConfig({ [section]: value }),
        error => error.message.includes(section) && /object/.test(error.message),
      );
    }
  }
});

test('rejects null, array, and non-object free provider blocks', () => {
  for (const value of [null, [], ['free'], 'bad', 42]) {
    assert.throws(() => validateConfig({ providers: { free: value } }), /providers\.free.*object/);
  }
  assert.deepEqual(validateConfig({ providers: { free: {} } }).providers.free.engines, {
    search: ['anysearch', 'bing', 'duckduckgo', 'searxng'],
    fetch: ['direct', 'anysearch', 'jina'],
  });
});

test('rejects an unknown route provider', () => {
  assert.throws(() => validateConfig({ routes: { search: ['unknown'], fetch: [] } }), /unknown/);
});

test('applies independent default routes', () => {
  const config = validateConfig({});
  assert.deepEqual(config.routes.search, ['free', 'minimax', 'deepseek']);
  assert.deepEqual(config.routes.fetch, ['free', 'minimax', 'deepseek']);
  assert.notEqual(config.routes.search, config.routes.fetch);
});

test('does not mutate input', () => {
  const input = { server: { providerTimeoutMs: 5000 } };
  const snapshot = JSON.stringify(input);
  validateConfig(input);
  assert.equal(JSON.stringify(input), snapshot);
});

test('rejects non-positive integer limits', () => {
  assert.throws(() => validateConfig({ server: { providerTimeoutMs: 0 } }));
  assert.throws(() => validateConfig({ server: { providerTimeoutMs: -1 } }));
  assert.throws(() => validateConfig({ server: { providerTimeoutMs: 1.5 } }));
  assert.throws(() => validateConfig({ server: { requestTimeoutMs: 0 } }));
  assert.throws(() => validateConfig({ server: { cooldownMs: 0 } }));
  assert.throws(() => validateConfig({ server: { maxSearchResults: 0 } }));
  assert.throws(() => validateConfig({ server: { maxFetchChars: 0 } }));
});

test('rejects empty route arrays', () => {
  assert.throws(() => validateConfig({ routes: { search: [], fetch: ['free'] } }), /search/);
  assert.throws(() => validateConfig({ routes: { search: ['free'], fetch: [] } }), /fetch/);
});

test('rejects invalid MiniMax settings', () => {
  assert.throws(() => validateConfig({ providers: { minimax: { command: 123 } } }));
  assert.throws(() => validateConfig({ providers: { minimax: { tools: 'not-an-array' } } }));
  assert.throws(() => validateConfig({ providers: { minimax: { tools: [1, 2] } } }));
});

test('rejects array-typed MiniMax and DeepSeek provider blocks', () => {
  assert.throws(() => validateConfig({ providers: { minimax: [] } }), /minimax/);
  assert.throws(() => validateConfig({ providers: { minimax: ['x'] } }), /minimax/);
  assert.throws(() => validateConfig({ providers: { deepseek: [] } }), /deepseek/);
  assert.throws(() => validateConfig({ providers: { deepseek: ['x'] } }), /deepseek/);
});

test('rejects empty or whitespace MiniMax command and tools', () => {
  assert.throws(() => validateConfig({ providers: { minimax: { command: '' } } }), /command/);
  assert.throws(() => validateConfig({ providers: { minimax: { command: '   ' } } }), /command/);
  assert.throws(() => validateConfig({ providers: { minimax: { command: '\t\n' } } }), /command/);
  assert.throws(() => validateConfig({ providers: { minimax: { tools: [''] } } }), /tools/);
  assert.throws(() => validateConfig({ providers: { minimax: { tools: ['ok', '  '] } } }), /tools/);
});

test('preserves original MiniMax command/tools strings when valid', () => {
  const c = validateConfig({
    providers: { minimax: { command: '  node  ', tools: [' web_search '] } },
  });
  assert.equal(c.providers.minimax.command, '  node  ');
  assert.deepEqual(c.providers.minimax.tools, [' web_search ']);
});

test('rejects invalid MiniMax args entries', () => {
  assert.throws(() => validateConfig({ providers: { minimax: { args: 'not-array' } } }), /args/);
  assert.throws(() => validateConfig({ providers: { minimax: { args: [1, 2] } } }), /args/);
  assert.throws(() => validateConfig({ providers: { minimax: { args: ['ok', null] } } }), /args/);
  assert.throws(() => validateConfig({ providers: { minimax: { args: [{}] } } }), /args/);
});

test('accepts valid MiniMax args', () => {
  const c = validateConfig({ providers: { minimax: { args: ['a', 'b', 'c'] } } });
  assert.deepEqual(c.providers.minimax.args, ['a', 'b', 'c']);
});

test('rejects invalid MiniMax env values', () => {
  assert.throws(() => validateConfig({ providers: { minimax: { env: [] } } }), /env/);
  assert.throws(() => validateConfig({ providers: { minimax: { env: 'str' } } }), /env/);
  assert.throws(() => validateConfig({ providers: { minimax: { env: { KEY: 42 } } } }), /KEY/);
  assert.throws(() => validateConfig({ providers: { minimax: { env: { KEY: null } } } }), /KEY/);
  assert.throws(() => validateConfig({ providers: { minimax: { env: { KEY: true } } } }), /KEY/);
  assert.throws(() => validateConfig({ providers: { minimax: { env: { KEY: ['a'] } } } }), /KEY/);
  assert.throws(() => validateConfig({ providers: { minimax: { env: { KEY: {} } } } }), /KEY/);
});

test('accepts valid MiniMax env', () => {
  const c = validateConfig({
    providers: { minimax: { env: { MINIMAX_API_KEY: 'placeholder', OTHER: 'x' } } },
  });
  assert.equal(c.providers.minimax.env.MINIMAX_API_KEY, 'placeholder');
});

test('rejects invalid DeepSeek base URL', () => {
  assert.throws(() => validateConfig({ providers: { deepseek: { baseUrl: 'not-a-url' } } }));
  assert.throws(() => validateConfig({ providers: { deepseek: { baseUrl: 42 } } }));
  assert.throws(() => validateConfig({ providers: { deepseek: { baseUrl: 'ftp://example.com' } } }));
});

test('accepts valid DeepSeek base URL', () => {
  const c = validateConfig({ providers: { deepseek: { baseUrl: 'https://api.deepseek.com/v1' } } });
  assert.equal(c.providers.deepseek.baseUrl, 'https://api.deepseek.com/v1');
});

test('loadConfig reads JSON file and validates', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'uwm-'));
  try {
    const p = join(dir, 'config.json');
    writeFileSync(p, JSON.stringify({ server: { providerTimeoutMs: 7000 } }), 'utf8');
    const c = await loadConfig(p);
    assert.equal(c.server.providerTimeoutMs, 7000);
    assert.deepEqual(c.routes.search, ['free', 'minimax', 'deepseek']);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('loadConfig rejects missing file', async () => {
  await assert.rejects(() => loadConfig('D:/__does_not_exist__/nope.json'));
});

test('ProviderError carries fields', () => {
  const e = new ProviderError('boom', { provider: 'minimax', retryable: true, status: 429 });
  assert.equal(e.message, 'boom');
  assert.equal(e.provider, 'minimax');
  assert.equal(e.retryable, true);
  assert.equal(e.status, 429);
  assert.equal(e.name, 'ProviderError');
  assert.ok(e instanceof Error);
});

test('InputError is an Error', () => {
  const e = new InputError('bad input');
  assert.equal(e.message, 'bad input');
  assert.equal(e.name, 'InputError');
  assert.ok(e instanceof Error);
});
