import test from 'node:test';
import assert from 'node:assert/strict';
import { Agent } from 'undici';
import { ProviderError, InputError } from '../src/errors.js';
import { assertPublicUrl, createPublicLookup } from '../src/http.js';
import { createFreeProvider } from '../src/providers/free.js';
import { createMiniMaxProvider, normalizeMiniMaxSearch } from '../src/providers/minimax.js';
import { createDeepSeekProvider, normalizeDeepSeekSearch } from '../src/providers/deepseek.js';

const PUBLIC_URL = 'https://93.184.216.34/page';
const DEEPSEEK_KEY = 'deepseek-test-key';
const MINIMAX_KEY = 'minimax-test-key';

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

function miniMaxClient(result, overrides = {}) {
  return {
    callTool: async () => result,
    close: async () => {},
    ...overrides,
  };
}

test('normalizes MiniMax organic results without mutating input', () => {
  const input = Object.freeze({
    organic: Object.freeze([Object.freeze({ title: 'A', link: 'https://a.test', snippet: 'B', date: '' })]),
  });
  assert.deepEqual(normalizeMiniMaxSearch(input).sources[0], {
    title: 'A', url: 'https://a.test', snippet: 'B', publishedAt: null,
  });
  assert.equal(input.organic[0].link, 'https://a.test');
});

test('normalizes MiniMax structured content and JSON text blocks', () => {
  const organic = [{ title: 'A', link: 'https://a.test', snippet: 'B', date: 'today' }];
  const structured = normalizeMiniMaxSearch({ structuredContent: { organic } });
  const text = normalizeMiniMaxSearch({ content: [{ type: 'text', text: JSON.stringify({ organic }) }] });
  assert.deepEqual(structured, text);
  assert.equal(text.sources[0].publishedAt, 'today');
});

test('MiniMax rejects missing or malformed organic search payloads', () => {
  for (const payload of [null, {}, { organic: null }, { organic: {} }, { organic: 'bad' }]) {
    assert.throws(
      () => normalizeMiniMaxSearch(payload),
      error => error instanceof ProviderError && error.provider === 'minimax' && error.retryable,
    );
  }
  assert.deepEqual(normalizeMiniMaxSearch({ organic: [] }), { sources: [] });
});

test('MiniMax connects lazily once for concurrent calls and closes idempotently', async () => {
  let connections = 0;
  let closes = 0;
  let transportOptions;
  const signals = [];
  const client = miniMaxClient(
    { content: [{ type: 'text', text: JSON.stringify({ organic: [] }) }] },
    { close: async () => { closes += 1; } },
  );
  client.callTool = async (params, options) => {
    signals.push(options.signal);
    assert.equal(params.name, 'web_search');
    assert.deepEqual(params.arguments, { query: 'test' });
    return { structuredContent: { organic: [] } };
  };
  const provider = createMiniMaxProvider(
    { command: 'dummy', args: ['server'], tools: ['web_search'], env: { MINIMAX_API_KEY: MINIMAX_KEY } },
    { clientFactory: async options => {
      connections += 1;
      transportOptions = options;
      await Promise.resolve();
      return client;
    } },
  );

  assert.equal(connections, 0);
  const controller = new AbortController();
  await Promise.all([
    provider.search({ query: 'test', maxResults: 2 }, { signal: controller.signal }),
    provider.search({ query: 'test', maxResults: 2 }, { signal: controller.signal }),
  ]);
  assert.equal(connections, 1);
  assert.equal(transportOptions.command, 'dummy');
  assert.deepEqual(transportOptions.args, ['server']);
  assert.equal(transportOptions.env.MINIMAX_API_KEY, MINIMAX_KEY);
  assert.equal(transportOptions.stderr, 'ignore');
  assert.notEqual(transportOptions.env, undefined);
  assert.ok(signals.every(signal => signal === controller.signal));
  await Promise.all([provider.close(), provider.close()]);
  assert.equal(closes, 1);
});

test('MiniMax resets a failed connection so a later call can retry without leaking keys', async () => {
  let connections = 0;
  const provider = createMiniMaxProvider(
    { tools: ['web_search'], env: { MINIMAX_API_KEY: MINIMAX_KEY } },
    { clientFactory: async () => {
      connections += 1;
      if (connections === 1) throw new Error(`failed with ${MINIMAX_KEY}`);
      return miniMaxClient({ organic: [] });
    } },
  );

  await assert.rejects(
    () => provider.search({ query: 'test', maxResults: 1 }),
    error => error instanceof ProviderError && !error.message.includes(MINIMAX_KEY),
  );
  assert.deepEqual(await provider.search({ query: 'test', maxResults: 1 }), { sources: [] });
  assert.equal(connections, 2);
  await provider.close();
});

test('MiniMax caller abort does not cancel shared connection establishment', async () => {
  let factorySignal;
  let releaseConnection;
  let markStarted;
  const started = new Promise(resolve => { markStarted = resolve; });
  const provider = createMiniMaxProvider(
    { tools: ['web_search'] },
    { clientFactory: (options, { signal }) => {
      factorySignal = signal;
      markStarted();
      return new Promise(resolve => { releaseConnection = resolve; });
    } },
  );
  const controller = new AbortController();
  const reason = new DOMException('one caller stopped', 'AbortError');
  const abortedCall = provider.search(
    { query: 'first', maxResults: 1 },
    { signal: controller.signal },
  );
  const sharedCall = provider.search({ query: 'second', maxResults: 1 });
  const rejection = assert.rejects(abortedCall, error => error === reason);
  await started;
  controller.abort(reason);
  assert.equal(factorySignal.aborted, false);

  releaseConnection(miniMaxClient({ structuredContent: { organic: [] } }));
  await rejection;
  assert.deepEqual(await sharedCall, { sources: [] });
  assert.equal(factorySignal.aborted, false);
  await provider.close();
});

test('MiniMax close aborts a never-settling connection and ignores new work', async () => {
  let factorySignal;
  let markStarted;
  let connections = 0;
  const started = new Promise(resolve => { markStarted = resolve; });
  const provider = createMiniMaxProvider(
    { tools: ['web_search'], closeTimeoutMs: 10 },
    { clientFactory: (options, { signal }) => {
      connections += 1;
      factorySignal = signal;
      markStarted();
      return new Promise(() => {});
    } },
  );

  const pending = assert.rejects(
    provider.search({ query: 'test', maxResults: 1 }),
    error => error instanceof ProviderError && /closed/.test(error.message),
  );
  await started;
  await provider.close();
  await pending;
  assert.equal(factorySignal.aborted, true);
  await assert.rejects(() => provider.search({ query: 'later', maxResults: 1 }), /closed/);
  assert.equal(connections, 1);
});

test('MiniMax closes a client that settles after close', async () => {
  let settleConnection;
  let markStarted;
  let closes = 0;
  const started = new Promise(resolve => { markStarted = resolve; });
  const provider = createMiniMaxProvider(
    { tools: ['web_search'] },
    { clientFactory: () => {
      markStarted();
      return new Promise(resolve => { settleConnection = resolve; });
    } },
  );

  const pending = assert.rejects(
    provider.search({ query: 'test', maxResults: 1 }),
    error => error instanceof ProviderError && /closed/.test(error.message),
  );
  await started;
  await provider.close();
  settleConnection(miniMaxClient(null, { close: async () => { closes += 1; } }));
  await new Promise(resolve => setImmediate(resolve));
  await pending;
  assert.equal(closes, 1);
});

test('MiniMax connection establishment has an independent timeout', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let factorySignal;
  const provider = createMiniMaxProvider(
    { tools: ['web_search'], connectTimeoutMs: 15_000 },
    { clientFactory: (options, { signal }) => {
      factorySignal = signal;
      return new Promise(() => {});
    } },
  );

  const pending = assert.rejects(
    provider.search({ query: 'test', maxResults: 1 }),
    error => error instanceof ProviderError && error.retryable && /timed out/.test(error.message),
  );
  await Promise.resolve();
  t.mock.timers.tick(15_000);
  await pending;
  assert.equal(factorySignal.aborted, true);
  await provider.close();
});

test('MiniMax close does not wait forever for a stuck client', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const provider = createMiniMaxProvider(
    { tools: ['web_search'], closeTimeoutMs: 5_000 },
    { clientFactory: async () => miniMaxClient(
      { structuredContent: { organic: [] } },
      { close: () => new Promise(() => {}) },
    ) },
  );
  await provider.search({ query: 'test', maxResults: 1 });
  const closing = provider.close();
  t.mock.timers.tick(5_000);
  await closing;
});

test('MiniMax selects configured fetch tools and omits unsupported capabilities', async () => {
  const searchOnly = createMiniMaxProvider({ tools: ['web_search'] }, {
    clientFactory: async () => miniMaxClient({ organic: [] }),
  });
  assert.equal(typeof searchOnly.search, 'function');
  assert.equal(searchOnly.fetch, undefined);
  await searchOnly.close();

  const calls = [];
  const provider = createMiniMaxProvider({ tools: ['web_fetch', 'read_url'] }, {
    clientFactory: async () => miniMaxClient(null, {
      callTool: async params => {
        calls.push(params);
        return { title: 'Title', url: 'https://a.test', content: 'abcdef' };
      },
    }),
  });
  const args = Object.freeze({ url: 'https://a.test', maxChars: 3 });
  const result = await provider.fetch(args);
  assert.equal(calls[0].name, 'web_fetch');
  assert.deepEqual(calls[0].arguments, { url: 'https://a.test' });
  assert.deepEqual(result, { title: 'Title', url: 'https://a.test', content: 'abc', truncated: true });
  assert.equal(args.maxChars, 3);
  await provider.close();
});

test('normalizes DeepSeek search results', () => {
  const result = normalizeDeepSeekSearch({ results: [{ title: 'A', url: 'https://a.test', summary: 'S', date: null }] });
  assert.deepEqual(result.sources[0], {
    title: 'A', url: 'https://a.test', snippet: 'S', publishedAt: null,
  });
  assert.deepEqual(normalizeDeepSeekSearch({ results: [] }), { sources: [] });
});

test('DeepSeek rejects missing or malformed search result payloads', () => {
  for (const payload of [null, {}, { results: null }, { results: {} }, { results: 'bad' }]) {
    assert.throws(
      () => normalizeDeepSeekSearch(payload),
      error => error instanceof ProviderError && error.provider === 'deepseek' && error.retryable,
    );
  }
  assert.deepEqual(normalizeDeepSeekSearch({ results: [] }), { sources: [] });
});

test('DeepSeek maps search URL, headers, body, results, and caller signal', async t => {
  const controller = new AbortController();
  const calls = mockFetch(t, async () => jsonResponse({
    results: [
      { title: 'A', url: 'https://a.test', summary: 'S', date: 'today' },
      { title: 'B', url: 'https://b.test', summary: 'T', date: null },
    ],
  }));
  const provider = createDeepSeekProvider({ baseUrl: 'https://api.deepseek.com/v1/', apiKey: DEEPSEEK_KEY });
  const args = Object.freeze({ query: 'hello', maxResults: 1 });
  const result = await provider.search(args, { signal: controller.signal });

  assert.equal(calls[0][0], 'https://api.deepseek.com/v1/tools/search');
  assert.equal(calls[0][1].method, 'POST');
  assert.equal(calls[0][1].headers.authorization, `Bearer ${DEEPSEEK_KEY}`);
  assert.equal(calls[0][1].headers['content-type'], 'application/json');
  assert.equal(calls[0][1].signal, controller.signal);
  assert.deepEqual(JSON.parse(calls[0][1].body), { query: 'hello', count: 1, need_content: false });
  assert.equal(result.sources.length, 1);
  assert.equal(result.sources[0].snippet, 'S');
  assert.equal(args.query, 'hello');
});

test('DeepSeek maps fetch and honors maxChars', async t => {
  const calls = mockFetch(t, async () => jsonResponse({ title: 'A', url: 'https://a.test', content: 'abcdef' }));
  const provider = createDeepSeekProvider({ baseUrl: 'https://api.deepseek.com/v1', apiKey: DEEPSEEK_KEY });
  const result = await provider.fetch({ url: 'https://a.test', maxChars: 4 });

  assert.equal(calls[0][0], 'https://api.deepseek.com/v1/tools/fetch');
  assert.deepEqual(JSON.parse(calls[0][1].body), { url: 'https://a.test' });
  assert.deepEqual(result, { title: 'A', url: 'https://a.test', content: 'abcd', truncated: true });
});

test('DeepSeek empty search results are successful', async t => {
  mockFetch(t, async () => jsonResponse({ results: [] }));
  const provider = createDeepSeekProvider({ apiKey: DEEPSEEK_KEY });
  assert.deepEqual(await provider.search({ query: 'none', maxResults: 5 }), { sources: [] });
});

test('DeepSeek rejects oversized responses instead of parsing them', async t => {
  mockFetch(t, async () => jsonResponse({ results: [{ title: 'a'.repeat(100) }] }));
  const provider = createDeepSeekProvider({ apiKey: DEEPSEEK_KEY, maxResponseBytes: 10 });
  await assert.rejects(
    () => provider.search({ query: 'test', maxResults: 1 }),
    error => error instanceof ProviderError && error.retryable && /exceeded 10 bytes/.test(error.message),
  );
});

test('DeepSeek body limits preserve caller abort', async t => {
  mockFetch(t, async () => new Response(new ReadableStream({
    pull: () => new Promise(() => {}),
  }), { headers: { 'content-type': 'application/json' } }));
  const provider = createDeepSeekProvider({ apiKey: DEEPSEEK_KEY });
  const controller = new AbortController();
  const reason = new DOMException('caller stopped', 'AbortError');
  const pending = provider.search({ query: 'test', maxResults: 1 }, { signal: controller.signal });
  const rejection = assert.rejects(pending, error => error === reason);
  await new Promise(resolve => setImmediate(resolve));
  controller.abort(reason);
  await rejection;
});

test('DeepSeek non-2xx errors preserve status and retryability without response bodies or keys', async t => {
  const provider = createDeepSeekProvider({ apiKey: DEEPSEEK_KEY });
  for (const [status, retryable] of [[429, true], [503, true], [400, false]]) {
    mockFetch(t, async () => jsonResponse({ error: `secret ${DEEPSEEK_KEY}` }, status));
    await assert.rejects(
      () => provider.search({ query: 'test', maxResults: 1 }),
      error => {
        assert.ok(error instanceof ProviderError);
        assert.equal(error.status, status);
        assert.equal(error.retryable, retryable);
        assert.equal(error.message.includes(DEEPSEEK_KEY), false);
        assert.equal(error.message.includes('secret'), false);
        return true;
      },
    );
  }
});

test('blocks local, private, credential-bearing, and non-HTTP fetch targets', async () => {
  for (const url of [
    'http://127.0.0.1/admin',
    'http://localhost/admin',
    'http://10.0.0.1/admin',
    'http://169.254.169.254/latest',
    'http://[::1]/admin',
    'http://[fec0::1]/admin',
    'https://user:pass@93.184.216.34/admin',
    'file:///etc/passwd',
  ]) {
    await assert.rejects(() => assertPublicUrl(url), InputError);
  }
  await assert.rejects(
    () => assertPublicUrl('https://public-name.test', { lookup: async () => [{ address: '192.168.1.2', family: 4 }] }),
    /private|local|public/i,
  );
  const result = await assertPublicUrl('https://public-name.test', {
    lookup: async () => [{ address: '93.184.216.34', family: 4 }],
  });
  assert.equal(result.hostname, 'public-name.test');
});

test('connection lookup validates every DNS answer and returns only validated addresses', async () => {
  const resolutions = [];
  const lookup = createPublicLookup({ lookup: async (hostname, options) => {
    resolutions.push({ hostname, options });
    return [
      { address: '93.184.216.34', family: 4 },
      { address: '2001:4860:4860::8888', family: 6 },
    ];
  } });
  const invoke = (options = {}) => new Promise((resolve, reject) => {
    lookup('public-name.test', options, (error, address, family) => {
      if (error) reject(error);
      else resolve({ address, family });
    });
  });

  assert.deepEqual(await invoke({ family: 0 }), {
    address: '93.184.216.34',
    family: 4,
  });
  assert.deepEqual((await invoke({ all: true })).address, [
    { address: '93.184.216.34', family: 4 },
    { address: '2001:4860:4860::8888', family: 6 },
  ]);
  assert.equal(resolutions[0].options.all, true);
  assert.equal(resolutions[0].options.verbatim, true);

  const rebinding = createPublicLookup({ lookup: async () => [
    { address: '93.184.216.34', family: 4 },
    { address: '127.0.0.1', family: 4 },
  ] });
  await assert.rejects(
    new Promise((resolve, reject) => {
      rebinding('public-name.test', {}, error => error ? reject(error) : resolve());
    }),
    InputError,
  );
});

test('normalizes multiple Bing RSS items and respects maxResults and signal', async t => {
  const xml = `<?xml version="1.0"?><rss><channel><item>
    <title>A</title><link>https://a.test</link><description>First</description><pubDate>today</pubDate>
    </item><item><title>B</title><link>https://b.test</link><description>Second</description></item></channel></rss>`;
  const controller = new AbortController();
  const calls = mockFetch(t, async () => new Response(xml, { headers: { 'content-type': 'application/rss+xml' } }));
  const provider = createFreeProvider({ engines: { search: ['bing'] } });
  const result = await provider.search({ query: 'hello world', maxResults: 1 }, { signal: controller.signal });

  const requestUrl = new URL(calls[0][0]);
  assert.equal(requestUrl.searchParams.get('q'), 'hello world');
  assert.equal(requestUrl.searchParams.get('format'), 'rss');
  assert.equal(calls[0][1].signal, controller.signal);
  assert.deepEqual(result.sources, [{ title: 'A', url: 'https://a.test', snippet: 'First', publishedAt: 'today' }]);
});

test('normalizes a single Bing RSS item as an array', async t => {
  const xml = '<rss><channel><item><title>Only</title><link>https://only.test</link><description>One</description></item></channel></rss>';
  mockFetch(t, async () => new Response(xml));
  const provider = createFreeProvider({ engines: { search: ['bing'] } });
  const result = await provider.search({ query: 'one', maxResults: 8 });
  assert.equal(result.sources.length, 1);
  assert.deepEqual(result.sources[0], {
    title: 'Only', url: 'https://only.test', snippet: 'One', publishedAt: null,
  });
});

test('free fetch cleans HTML, follows public redirects, and reports character truncation', async t => {
  const calls = mockFetch(t, async url => {
    if (calls.length === 1) {
      return new Response(null, { status: 302, headers: { location: '/final' } });
    }
    return new Response(`<!doctype html><html><head><title>Example</title><style>.x{}</style></head><body>
      <nav>navigation</nav><script>alert('bad')</script><main><p>Hello <strong>world</strong></p><p>More text</p></main>
      </body></html>`, { headers: { 'content-type': 'text/html; charset=utf-8' } });
  });
  const provider = createFreeProvider({ engines: { fetch: ['direct'] } });
  const result = await provider.fetch({ url: PUBLIC_URL, maxChars: 12 });

  assert.equal(calls.length, 2);
  assert.equal(calls[0][1].redirect, 'manual');
  assert.ok(calls[0][1].dispatcher instanceof Agent);
  assert.equal(calls[1][1].dispatcher, calls[0][1].dispatcher);
  assert.equal(calls[0][1].dispatcher.closed, true);
  assert.equal(result.title, 'Example');
  assert.equal(result.url, 'https://93.184.216.34/final');
  assert.equal(result.content.includes('alert'), false);
  assert.equal(result.content.includes('navigation'), false);
  assert.equal(result.content.length, 12);
  assert.equal(result.truncated, true);
});

test('free fetch revalidates redirect targets before requesting them', async t => {
  const calls = mockFetch(t, async () => new Response(null, {
    status: 302,
    headers: { location: 'http://127.0.0.1/admin' },
  }));
  const provider = createFreeProvider({ engines: { fetch: ['direct'] } });
  await assert.rejects(() => provider.fetch({ url: PUBLIC_URL, maxChars: 100 }), InputError);
  assert.equal(calls.length, 1);
});

test('free search rejects oversized responses instead of parsing them', async t => {
  mockFetch(t, async () => new Response('<rss><channel></channel></rss>', {
    headers: { 'content-type': 'application/rss+xml' },
  }));
  const provider = createFreeProvider({ maxResponseBytes: 10, engines: { search: ['bing'] } });
  await assert.rejects(
    () => provider.search({ query: 'test', maxResults: 1 }),
    error => error instanceof ProviderError && error.retryable && /exceeded 10 bytes/.test(error.message),
  );
});

test('free fetch rejects oversized responses instead of returning truncated content', async t => {
  mockFetch(t, async () => new Response('a'.repeat(100), { headers: { 'content-type': 'text/plain' } }));
  const provider = createFreeProvider({ maxResponseBytes: 10, engines: { fetch: ['direct'] } });
  await assert.rejects(
    () => provider.fetch({ url: PUBLIC_URL, maxChars: 100 }),
    error => error instanceof ProviderError && error.retryable && /exceeded 10 bytes/.test(error.message),
  );
});

test('free fetch rejects unsupported response content types', async t => {
  mockFetch(t, async () => new Response('not an image', { headers: { 'content-type': 'image/png' } }));
  const provider = createFreeProvider({ engines: { fetch: ['direct'] } });
  await assert.rejects(
    () => provider.fetch({ url: PUBLIC_URL, maxChars: 100 }),
    error => error instanceof ProviderError && error.retryable === false,
  );
});
