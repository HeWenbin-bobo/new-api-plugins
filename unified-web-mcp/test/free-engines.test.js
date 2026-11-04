import test from 'node:test';
import assert from 'node:assert/strict';
import { validateConfig } from '../src/config.js';
import { ProviderError } from '../src/errors.js';
import { createFreeProvider } from '../src/providers/free.js';
import { createRouter } from '../src/router.js';

const PUBLIC_URL = 'https://93.184.216.34/page';
const ANYSEARCH_KEY = 'anysearch-test-key';
const JINA_KEY = 'jina-test-key';

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function mockFetch(t, implementation) {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (...args) => {
    calls.push(args);
    return implementation(...args);
  });
  return calls;
}

function ddgHtml() {
  return `<html><body>
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.test%2Fpage%3Fx%3D1&amp;rut=abc"> First </a>
      <div class="result__snippet">First snippet</div>
    </div>
    <div class="result">
      <a class="result__a" href="https://b.test/direct">Second</a>
      <a class="result__snippet">Second snippet</a>
    </div>
  </body></html>`;
}

test('applies free engine defaults without replacing existing limits', () => {
  const input = { providers: { free: { maxResponseBytes: 12345 } } };
  const snapshot = JSON.stringify(input);
  const config = validateConfig(input);

  assert.equal(config.providers.free.maxResponseBytes, 12345);
  assert.deepEqual(config.providers.free.engines, {
    search: ['anysearch', 'bing', 'duckduckgo', 'searxng'],
    fetch: ['direct', 'anysearch', 'jina'],
  });
  assert.deepEqual(config.providers.free.anysearch, {
    baseUrl: 'https://api.anysearch.com', apiKey: '', zone: '', language: '',
  });
  assert.deepEqual(config.providers.free.duckduckgo, {
    baseUrl: 'https://html.duckduckgo.com/html/', region: '',
  });
  assert.deepEqual(config.providers.free.searxng, { baseUrl: '', language: '' });
  assert.deepEqual(config.providers.free.jina, { baseUrl: 'https://r.jina.ai', apiKey: '' });
  assert.equal(JSON.stringify(input), snapshot);
});

test('validates free engine routes and nested engine settings', () => {
  for (const [operation, engine] of [['search', 'jina'], ['fetch', 'bing'], ['search', 'unknown']]) {
    assert.throws(
      () => validateConfig({ providers: { free: { engines: { [operation]: [engine] } } } }),
      new RegExp(`engines\\.${operation}|${engine}`),
    );
  }
  for (const operation of ['search', 'fetch']) {
    assert.throws(
      () => validateConfig({ providers: { free: { engines: { [operation]: [] } } } }),
      new RegExp(`engines\\.${operation}`),
    );
  }
  for (const engine of ['anysearch', 'duckduckgo', 'searxng', 'jina']) {
    for (const value of [null, [], 'bad']) {
      assert.throws(
        () => validateConfig({ providers: { free: { [engine]: value } } }),
        new RegExp(`free\\.${engine}.*object`),
      );
    }
    assert.throws(
      () => validateConfig({ providers: { free: { [engine]: { baseUrl: 42 } } } }),
      new RegExp(`${engine}\\.baseUrl`),
    );
  }
  for (const engine of ['anysearch', 'jina']) {
    assert.throws(
      () => validateConfig({ providers: { free: { [engine]: { apiKey: 42 } } } }),
      new RegExp(`${engine}\\.apiKey`),
    );
  }
  assert.throws(
    () => validateConfig({ providers: { free: { anysearch: { baseUrl: 'ftp://example.com' } } } }),
    /anysearch\.baseUrl/,
  );
  assert.doesNotThrow(() => validateConfig({ providers: { free: {
    anysearch: { apiKey: '' },
    jina: { apiKey: '' },
    searxng: { baseUrl: '', language: '' },
  } } }));
  assert.doesNotThrow(() => validateConfig({ providers: { free: {
    searxng: { baseUrl: 'http://127.0.0.1:8080' },
  } } }));
});

test('AnySearch search maps request, optional auth, dates, results, and metadata', async t => {
  const controller = new AbortController();
  const calls = mockFetch(t, async () => jsonResponse({
    code: 0,
    data: {
      results: [
        { title: 'A', url: 'https://a.test', content: 'First', published_at: 'today' },
        { title: 'B', url: 'https://b.test', snippet: 'Second', date: null },
      ],
    },
  }));
  const provider = createFreeProvider({
    engines: { search: ['anysearch'] },
    anysearch: { apiKey: ANYSEARCH_KEY, zone: 'us', language: 'en' },
  });
  const result = await provider.search(
    { query: 'hello world', maxResults: 1 },
    { signal: controller.signal },
  );

  assert.equal(calls[0][0], 'https://api.anysearch.com/v1/search');
  assert.equal(calls[0][1].method, 'POST');
  assert.equal(calls[0][1].headers.authorization, `Bearer ${ANYSEARCH_KEY}`);
  assert.equal(calls[0][1].headers['content-type'], 'application/json');
  assert.equal(calls[0][1].headers['x-anysearch-client'], 'skill/3.1.1');
  assert.equal(calls[0][1].signal, controller.signal);
  assert.deepEqual(JSON.parse(calls[0][1].body), {
    query: 'hello world', max_results: 1, zone: 'us', language: 'en',
  });
  assert.deepEqual(result.sources, [
    { title: 'A', url: 'https://a.test', snippet: 'First', publishedAt: 'today' },
  ]);
  assert.equal(result.engine, 'anysearch');
  assert.equal(result.engineFallback, false);
  assert.deepEqual(result.engineAttempts, [{ engine: 'anysearch', outcome: 'success' }]);
});

test('AnySearch fetch supports anonymous access and character truncation', async t => {
  const calls = mockFetch(t, async () => jsonResponse({
    code: 0,
    data: { title: 'A', url: 'https://a.test/final', content: 'abcdef' },
  }));
  const provider = createFreeProvider({ engines: { fetch: ['anysearch'] } });
  const result = await provider.fetch({ url: 'https://a.test', maxChars: 4 });

  assert.equal(calls[0][0], 'https://api.anysearch.com/v1/extract');
  assert.equal(calls[0][1].headers.authorization, undefined);
  assert.deepEqual(JSON.parse(calls[0][1].body), { url: 'https://a.test' });
  assert.deepEqual(result, {
    title: 'A',
    url: 'https://a.test/final',
    content: 'abcd',
    truncated: true,
    engine: 'anysearch',
    engineFallback: false,
    engineAttempts: [{ engine: 'anysearch', outcome: 'success' }],
  });
});

test('DuckDuckGo parses results and resolves only its redirect links', async t => {
  const calls = mockFetch(t, async () => new Response(ddgHtml(), {
    headers: { 'content-type': 'text/html' },
  }));
  const provider = createFreeProvider({
    engines: { search: ['duckduckgo'] },
    duckduckgo: { region: 'us-en' },
  });
  const result = await provider.search({ query: 'hello world', maxResults: 2 });

  const url = new URL(calls[0][0]);
  assert.equal(url.origin + url.pathname, 'https://html.duckduckgo.com/html/');
  assert.equal(url.searchParams.get('q'), 'hello world');
  assert.equal(url.searchParams.get('kl'), 'us-en');
  assert.match(calls[0][1].headers['user-agent'], /Mozilla/);
  assert.deepEqual(result.sources, [
    { title: 'First', url: 'https://a.test/page?x=1', snippet: 'First snippet', publishedAt: null },
    { title: 'Second', url: 'https://b.test/direct', snippet: 'Second snippet', publishedAt: null },
  ]);
  assert.equal(result.engine, 'duckduckgo');
});

test('DuckDuckGo challenge pages are retryable and fall back', async t => {
  const calls = mockFetch(t, async url => {
    if (String(url).includes('duckduckgo.com')) {
      return new Response('<html><form id="challenge-form"><div class="g-recaptcha"></div></form></html>');
    }
    return jsonResponse({ results: [] });
  });
  const provider = createFreeProvider({
    engines: { search: ['duckduckgo', 'searxng'] },
    searxng: { baseUrl: 'http://127.0.0.1:8080' },
  });
  const result = await provider.search({ query: 'test', maxResults: 3 });

  assert.equal(calls.length, 2);
  assert.deepEqual(result.sources, []);
  assert.equal(result.engine, 'searxng');
  assert.equal(result.engineFallback, true);
  assert.deepEqual(result.engineAttempts.map(attempt => [attempt.engine, attempt.outcome]), [
    ['duckduckgo', 'error'],
    ['searxng', 'empty'],
  ]);
});

test('DuckDuckGo explicit no-result pages are successful without fallback', async t => {
  const calls = mockFetch(t, async () => new Response('<html><body><div class="no-results">No results found.</div></body></html>'));
  const provider = createFreeProvider({ engines: { search: ['duckduckgo', 'bing'] } });
  const result = await provider.search({ query: 'none', maxResults: 3 });

  assert.equal(calls.length, 1);
  assert.deepEqual(result.sources, []);
  assert.equal(result.engine, 'duckduckgo');
  assert.deepEqual(result.engineAttempts, [{ engine: 'duckduckgo', outcome: 'empty' }]);
});

test('SearXNG maps local configured requests and JSON results', async t => {
  const calls = mockFetch(t, async () => jsonResponse({
    results: [{ title: 'A', url: 'https://a.test', content: 'Snippet', publishedDate: 'today' }],
  }));
  const provider = createFreeProvider({
    engines: { search: ['searxng'] },
    searxng: { baseUrl: 'http://127.0.0.1:8080/', language: 'en' },
  });
  const result = await provider.search({ query: 'hello', maxResults: 4 });

  const url = new URL(calls[0][0]);
  assert.equal(url.origin + url.pathname, 'http://127.0.0.1:8080/search');
  assert.equal(url.searchParams.get('q'), 'hello');
  assert.equal(url.searchParams.get('format'), 'json');
  assert.equal(url.searchParams.get('language'), 'en');
  assert.deepEqual(result.sources, [
    { title: 'A', url: 'https://a.test', snippet: 'Snippet', publishedAt: 'today' },
  ]);
  assert.equal(result.engine, 'searxng');
});

test('unconfigured SearXNG is skipped before the next search engine', async t => {
  const xml = '<rss><channel><item><title>Bing</title><link>https://bing.test</link><description>Result</description></item></channel></rss>';
  const calls = mockFetch(t, async () => new Response(xml));
  const provider = createFreeProvider({ engines: { search: ['searxng', 'bing'] } });
  const result = await provider.search({ query: 'test', maxResults: 4 });

  assert.equal(calls.length, 1);
  assert.equal(result.engine, 'bing');
  assert.equal(result.engineFallback, true);
  assert.deepEqual(result.engineAttempts[0], {
    engine: 'searxng', outcome: 'skipped', reason: 'unconfigured',
  });
  assert.equal(result.engineAttempts[1].outcome, 'success');
});

test('SearXNG HTTP 403 is retryable and falls back to Bing', async t => {
  const xml = '<rss><channel><item><title>Bing</title><link>https://bing.test</link><description>Result</description></item></channel></rss>';
  const calls = mockFetch(t, async url => (
    String(url).includes('127.0.0.1') ? jsonResponse({ error: 'JSON disabled' }, 403) : new Response(xml)
  ));
  const provider = createFreeProvider({
    engines: { search: ['searxng', 'bing'] },
    searxng: { baseUrl: 'http://127.0.0.1:8080' },
  });
  const result = await provider.search({ query: 'test', maxResults: 4 });

  assert.equal(calls.length, 2);
  assert.equal(result.engine, 'bing');
  assert.equal(result.engineFallback, true);
  assert.deepEqual(result.engineAttempts.map(attempt => [attempt.engine, attempt.outcome]), [
    ['searxng', 'error'],
    ['bing', 'success'],
  ]);
  assert.match(result.engineAttempts[0].error, /HTTP 403/);
  assert.equal(result.engineAttempts[0].error.includes('JSON disabled'), false);
});

test('Jina Reader uses the official prepend URL, optional auth, and truncation', async t => {
  const calls = mockFetch(t, async () => jsonResponse({
    code: 200,
    data: { title: 'A', url: 'https://a.test/final', content: 'abcdef' },
  }));
  const authenticated = createFreeProvider({
    engines: { fetch: ['jina'] },
    jina: { apiKey: JINA_KEY },
  });
  const result = await authenticated.fetch({ url: 'https://a.test/path?q=1', maxChars: 4 });

  assert.equal(calls[0][0], 'https://r.jina.ai/https://a.test/path?q=1');
  assert.equal(calls[0][1].method, 'GET');
  assert.equal(calls[0][1].headers.accept, 'application/json');
  assert.equal(calls[0][1].headers.authorization, `Bearer ${JINA_KEY}`);
  assert.equal(result.content, 'abcd');
  assert.equal(result.truncated, true);
  assert.equal(result.engine, 'jina');

  const anonymous = createFreeProvider({ engines: { fetch: ['jina'] } });
  await anonymous.fetch({ url: 'https://a.test', maxChars: 4 });
  assert.equal(calls[1][1].headers.authorization, undefined);
});

test('internal search fallback metadata survives the outer provider router', async t => {
  const secret = ANYSEARCH_KEY;
  mockFetch(t, async url => {
    if (String(url).includes('api.anysearch.com')) {
      return jsonResponse({ code: 0, data: { results: 'malformed', secret } });
    }
    return new Response(ddgHtml(), { headers: { 'content-type': 'text/html' } });
  });
  const config = validateConfig({
    routes: { search: ['free'], fetch: ['free'] },
    providers: { free: {
      engines: { search: ['anysearch', 'duckduckgo'] },
      anysearch: { apiKey: secret },
    } },
  });
  const router = createRouter(config, { free: createFreeProvider(config.providers.free) });
  const result = await router.search({ query: 'test', maxResults: 1 });

  assert.equal(result.provider, 'free');
  assert.equal(result.fallback, false);
  assert.deepEqual(result.attempts, [{ provider: 'free', outcome: 'success' }]);
  assert.equal(result.engine, 'duckduckgo');
  assert.equal(result.engineFallback, true);
  assert.deepEqual(result.engineAttempts.map(attempt => [attempt.engine, attempt.outcome]), [
    ['anysearch', 'error'],
    ['duckduckgo', 'success'],
  ]);
  assert.equal(JSON.stringify(result).includes(secret), false);
});

test('internal fetch fallback records direct and AnySearch attempts', async t => {
  const calls = mockFetch(t, async url => {
    if (String(url).includes('api.anysearch.com')) {
      return jsonResponse({
        code: 0,
        data: { title: 'Remote', url: 'https://a.test/final', content: 'abcdef' },
      });
    }
    return new Response('temporary failure', { status: 503 });
  });
  const provider = createFreeProvider({ engines: { fetch: ['direct', 'anysearch', 'jina'] } });
  const result = await provider.fetch({ url: PUBLIC_URL, maxChars: 4 });

  assert.equal(calls.length, 2);
  assert.equal(calls[1][0], 'https://api.anysearch.com/v1/extract');
  assert.equal(result.engine, 'anysearch');
  assert.equal(result.engineFallback, true);
  assert.equal(result.content, 'abcd');
  assert.equal(result.truncated, true);
  assert.deepEqual(result.engineAttempts.map(attempt => [attempt.engine, attempt.outcome]), [
    ['direct', 'error'],
    ['anysearch', 'success'],
  ]);
});

test('nonretryable engine errors stop internal fallback without exposing bodies or keys', async t => {
  const calls = mockFetch(t, async () => jsonResponse({
    error: `upstream secret ${ANYSEARCH_KEY}`,
  }, 400));
  const provider = createFreeProvider({
    engines: { search: ['anysearch', 'duckduckgo'] },
    anysearch: { apiKey: ANYSEARCH_KEY },
  });

  await assert.rejects(
    () => provider.search({ query: 'test', maxResults: 2 }),
    error => {
      assert.ok(error instanceof ProviderError);
      assert.equal(error.retryable, false);
      assert.equal(error.status, 400);
      assert.equal(error.message.includes(ANYSEARCH_KEY), false);
      assert.equal(error.message.includes('upstream secret'), false);
      return true;
    },
  );
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'https://api.anysearch.com/v1/search');
});

test('malformed and nonzero engine payloads are sanitized retryable failures', async t => {
  let payload;
  mockFetch(t, async () => jsonResponse(payload));
  const cases = [
    {
      config: { engines: { search: ['anysearch'] } }, method: 'search',
      args: { query: 'test', maxResults: 2 }, payload: { code: 0, data: { results: null } },
    },
    {
      config: { engines: { search: ['anysearch'] } }, method: 'search',
      args: { query: 'test', maxResults: 2 }, payload: { code: 7, error: 'private upstream detail' },
    },
    {
      config: { engines: { search: ['searxng'] }, searxng: { baseUrl: 'http://127.0.0.1:8080' } },
      method: 'search', args: { query: 'test', maxResults: 2 }, payload: { results: {} },
    },
    {
      config: { engines: { fetch: ['anysearch'] } }, method: 'fetch',
      args: { url: 'https://a.test', maxChars: 10 }, payload: { code: 0, data: { title: 'missing content' } },
    },
    {
      config: { engines: { fetch: ['jina'] } }, method: 'fetch',
      args: { url: 'https://a.test', maxChars: 10 }, payload: { code: 503, error: 'private upstream detail' },
    },
    {
      config: { engines: { fetch: ['jina'] } }, method: 'fetch',
      args: { url: 'https://a.test', maxChars: 10 }, payload: { code: 200, data: { content: 42 } },
    },
  ];

  for (const entry of cases) {
    payload = entry.payload;
    const provider = createFreeProvider(entry.config);
    await assert.rejects(
      () => provider[entry.method](entry.args),
      error => {
        assert.ok(error instanceof ProviderError);
        assert.equal(error.retryable, true);
        assert.equal(error.message.includes('private upstream detail'), false);
        return true;
      },
    );
  }
});

test('all new engines enforce the configured response byte limit', async t => {
  mockFetch(t, async () => new Response('x'.repeat(100), {
    headers: { 'content-type': 'application/json' },
  }));
  const cases = [
    [{ engines: { search: ['anysearch'] } }, 'search', { query: 'test', maxResults: 1 }],
    [{ engines: { search: ['duckduckgo'] } }, 'search', { query: 'test', maxResults: 1 }],
    [{ engines: { search: ['searxng'] }, searxng: { baseUrl: 'http://127.0.0.1:8080' } }, 'search', { query: 'test', maxResults: 1 }],
    [{ engines: { fetch: ['anysearch'] } }, 'fetch', { url: 'https://a.test', maxChars: 10 }],
    [{ engines: { fetch: ['jina'] } }, 'fetch', { url: 'https://a.test', maxChars: 10 }],
  ];

  for (const [config, method, args] of cases) {
    const provider = createFreeProvider({ ...config, maxResponseBytes: 16 });
    await assert.rejects(
      () => provider[method](args),
      error => error instanceof ProviderError && error.retryable && /exceeded 16 bytes/.test(error.message),
    );
  }
});

test('new-engine body reads preserve caller cancellation', async t => {
  const calls = mockFetch(t, async () => new Response(new ReadableStream({
    pull: () => new Promise(() => {}),
  }), { headers: { 'content-type': 'application/json' } }));
  const provider = createFreeProvider({ engines: { search: ['anysearch'] } });
  const controller = new AbortController();
  const reason = new DOMException('caller stopped', 'AbortError');
  const pending = provider.search(
    { query: 'test', maxResults: 1 },
    { signal: controller.signal },
  );
  const rejection = assert.rejects(pending, error => error === reason);
  await new Promise(resolve => setImmediate(resolve));
  controller.abort(reason);
  await rejection;
  assert.equal(calls[0][0], 'https://api.anysearch.com/v1/search');
});

test('direct fetch success includes engine metadata', async t => {
  mockFetch(t, async () => new Response('hello', { headers: { 'content-type': 'text/plain' } }));
  const provider = createFreeProvider({ engines: { fetch: ['direct'] } });
  const result = await provider.fetch({ url: PUBLIC_URL, maxChars: 10 });

  assert.equal(result.engine, 'direct');
  assert.equal(result.engineFallback, false);
  assert.deepEqual(result.engineAttempts, [{ engine: 'direct', outcome: 'success' }]);
});
