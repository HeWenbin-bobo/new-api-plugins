import test from 'node:test';
import assert from 'node:assert/strict';
import { createRouter } from '../src/router.js';
import { validateConfig } from '../src/config.js';
import { ProviderError, InputError } from '../src/errors.js';

function baseConfig(server = {}) {
  return validateConfig({
    server: {
      providerTimeoutMs: 30,
      requestTimeoutMs: 100,
      cooldownMs: 1000,
      ...server,
    },
    routes: {
      search: ['free', 'minimax', 'deepseek'],
      fetch: ['free', 'minimax', 'deepseek'],
    },
  });
}

test('falls back and reports attempts', async () => {
  const router = createRouter(baseConfig(), {
    free: { search: async () => { throw new ProviderError('down', { provider: 'free' }); } },
    minimax: { search: async () => ({ sources: [{ title: 'ok', url: 'https://example.com', snippet: '' }] }) },
  });
  const result = await router.search({ query: 'test' });
  assert.equal(result.provider, 'minimax');
  assert.equal(result.fallback, true);
  assert.deepEqual(result.attempts.map(x => x.provider), ['free', 'minimax']);
  assert.equal(result.attempts[0].error, 'down');
});

test('empty search is a valid result by default', async () => {
  const router = createRouter(baseConfig(), {
    free: { search: async () => ({ sources: [] }) },
    minimax: { search: async () => { throw new Error('must not run'); } },
  });
  const result = await router.search({ query: 'none' });
  assert.deepEqual(result.sources, []);
  assert.equal(result.fallback, false);
});

test('falls back on empty search only when configured', async () => {
  const router = createRouter(baseConfig({ fallbackOnEmptySearch: true }), {
    free: { search: async () => ({ sources: [] }) },
    minimax: { search: async () => ({ sources: [{ title: 'ok', url: 'https://example.com', snippet: '' }] }) },
  });
  const result = await router.search({ query: 'test' });
  assert.equal(result.provider, 'minimax');
  assert.equal(result.sources.length, 1);
  assert.equal(result.fallback, true);
});

test('cooldown skips a failed provider without affecting fetch', async () => {
  let searchCalls = 0;
  const router = createRouter(baseConfig(), {
    free: {
      search: async () => { searchCalls += 1; throw new Error('down'); },
      fetch: async () => ({ title: 'ok', url: 'https://example.com', content: 'ok', truncated: false }),
    },
    minimax: { search: async () => ({ sources: [] }) },
  });

  await router.search({ query: 'first' });
  const second = await router.search({ query: 'second' });
  const fetched = await router.fetch({ url: 'https://example.com' });

  assert.equal(searchCalls, 1);
  assert.equal(second.provider, 'minimax');
  assert.equal(fetched.provider, 'free');
  assert.equal(router.status().providers.find(x => x.name === 'free').cooldown.search, true);
  assert.equal(router.status().providers.find(x => x.name === 'free').cooldown.fetch, false);
});

test('unsupported fetch capability is skipped', async () => {
  let minimaxCalls = 0;
  const router = createRouter(baseConfig(), {
    free: { search: async () => ({ sources: [] }) },
    minimax: {
      fetch: async () => {
        minimaxCalls += 1;
        return { title: 'ok', url: 'https://example.com', content: 'ok', truncated: false };
      },
    },
  });
  const result = await router.fetch({ url: 'https://example.com' });
  assert.equal(result.provider, 'minimax');
  assert.equal(minimaxCalls, 1);
});

test('provider InputError is returned without trying the next provider', async () => {
  const router = createRouter(baseConfig(), {
    free: { search: async () => { throw new InputError('bad provider input'); } },
    minimax: { search: async () => { throw new Error('must not run'); } },
  });
  await assert.rejects(() => router.search({ query: 'test' }), InputError);
});

test('ProviderError retryable:false stops fallback without cooldown', async () => {
  let freeCalls = 0;
  let fallbackCalls = 0;
  const router = createRouter(baseConfig(), {
    free: { search: async () => {
      freeCalls += 1;
      throw new ProviderError('target not found', { provider: 'free', retryable: false, status: 404 });
    } },
    minimax: { search: async () => { fallbackCalls += 1; return { sources: [] }; } },
  });

  for (let attempt = 0; attempt < 2; attempt += 1) {
    await assert.rejects(
      () => router.search({ query: 'test' }),
      error => error instanceof ProviderError && error.retryable === false && error.status === 404,
    );
  }
  assert.equal(freeCalls, 2);
  assert.equal(fallbackCalls, 0);
  assert.equal(router.status().providers.find(x => x.name === 'free').cooldown.search, false);
});

test('validates operation inputs before calling providers', async () => {
  let calls = 0;
  const router = createRouter(baseConfig(), {
    free: {
      search: async () => { calls += 1; return { sources: [] }; },
      fetch: async () => { calls += 1; return {}; },
    },
  });

  await assert.rejects(() => router.search({ query: '  ' }), InputError);
  await assert.rejects(() => router.search({ query: 'ok', maxResults: 0 }), InputError);
  await assert.rejects(() => router.fetch({ url: 'ftp://example.com/file' }), InputError);
  await assert.rejects(() => router.fetch({ url: 'https://example.com', maxChars: 1.5 }), InputError);
  assert.equal(calls, 0);
});

test('enforces per-attempt timeout and falls back', async () => {
  const router = createRouter(baseConfig({ providerTimeoutMs: 10 }), {
    free: { search: (_args, { signal }) => new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    }) },
    minimax: { search: async () => ({ sources: [] }) },
  });
  const result = await router.search({ query: 'test' });
  assert.equal(result.provider, 'minimax');
  assert.match(result.attempts[0].error, /timed out|deadline/i);
});

test('enforces the total deadline across attempts', async () => {
  let deepseekCalls = 0;
  const router = createRouter(baseConfig({ providerTimeoutMs: 15, requestTimeoutMs: 25 }), {
    free: { search: () => new Promise(() => {}) },
    minimax: { search: () => new Promise(() => {}) },
    deepseek: { search: async () => { deepseekCalls += 1; return { sources: [] }; } },
  });
  await assert.rejects(() => router.search({ query: 'test' }), /timed out|deadline/i);
  assert.equal(deepseekCalls, 0);
});

test('caller cancellation aborts without fallback or cooldown', async () => {
  const controller = new AbortController();
  let fallbackCalls = 0;
  const router = createRouter(baseConfig(), {
    free: { search: (_args, { signal }) => new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    }) },
    minimax: { search: async () => { fallbackCalls += 1; return { sources: [] }; } },
  });

  const pending = router.search({ query: 'test' }, { signal: controller.signal });
  controller.abort();
  await assert.rejects(() => pending, error => error?.name === 'AbortError');
  assert.equal(fallbackCalls, 0);
  assert.equal(router.status().providers.find(x => x.name === 'free').cooldown.search, false);
});

test('does not mutate provider results', async () => {
  const providerResult = Object.freeze({ sources: Object.freeze([]) });
  const router = createRouter(baseConfig(), {
    free: { search: async () => providerResult },
  });
  const result = await router.search({ query: 'test' });
  assert.notEqual(result, providerResult);
  assert.deepEqual(providerResult, { sources: [] });
  assert.equal(result.provider, 'free');
});

test('sanitizes provider credentials from errors and status', async () => {
  const secret = 'router-test-secret-not-a-real-key';
  const config = baseConfig();
  config.providers.minimax.env = { MINIMAX_API_KEY: secret };
  const router = createRouter(config, {
    free: { search: async () => { throw new Error(`upstream rejected ${secret}`); } },
  });

  await assert.rejects(
    () => router.search({ query: 'test' }),
    error => {
      assert.equal(error instanceof ProviderError, true);
      assert.equal(error.message.includes(secret), false);
      assert.equal(error.attempts.every(attempt => !attempt.error?.includes(secret)), true);
      return true;
    },
  );
  assert.equal(JSON.stringify(router.status()).includes(secret), false);
});

test('close closes each adapter once and ignores duplicate calls', async () => {
  let freeCloses = 0;
  let minimaxCloses = 0;
  const router = createRouter(baseConfig(), {
    free: { close: async () => { freeCloses += 1; } },
    minimax: { close: () => { minimaxCloses += 1; } },
  });
  await Promise.all([router.close(), router.close()]);
  await router.close();
  assert.equal(freeCloses, 1);
  assert.equal(minimaxCloses, 1);
});
