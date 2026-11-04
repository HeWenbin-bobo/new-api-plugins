import { load } from 'cheerio';
import { XMLParser } from 'fast-xml-parser';
import { FREE_PROVIDER_DEFAULTS } from '../config.js';
import { InputError, ProviderError } from '../errors.js';
import { assertPublicUrl, createPublicDispatcher, readBoundedResponseText } from '../http.js';

const USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36';
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);
const RETRYABLE_STATUSES = new Set([401, 402, 403, 408, 413, 429]);

function text(value) {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isRetryableStatus(status) {
  return RETRYABLE_STATUSES.has(status) || status >= 500;
}

function httpError(operation, status) {
  return new ProviderError(`Free ${operation} failed with HTTP ${status}`, {
    provider: 'free',
    retryable: isRetryableStatus(status),
    status,
  });
}

function malformed(engine, operation) {
  return new ProviderError(`Free ${engine} ${operation} returned a malformed response`, {
    provider: 'free',
    retryable: true,
  });
}

function parseJson(body, engine, operation) {
  try {
    return JSON.parse(body);
  } catch {
    throw malformed(engine, operation);
  }
}

function endpoint(baseUrl, path) {
  return `${baseUrl.replace(/\/+$/, '')}${path}`;
}

function publishedAt(entry) {
  for (const field of ['publishedAt', 'published_at', 'publishedDate', 'published_date', 'date']) {
    const value = text(entry[field]);
    if (value) return value;
  }
  return null;
}

async function guard(operation, signal, action) {
  try {
    signal?.throwIfAborted();
    return await action();
  } catch (error) {
    if (error instanceof InputError || error instanceof ProviderError) throw error;
    if (signal?.aborted) throw signal.reason;
    throw new ProviderError(`Free ${operation} request failed`, { provider: 'free' });
  }
}

function normalizeBingSearch(xml, maxResults) {
  const document = new XMLParser({ ignoreAttributes: true }).parse(xml);
  const item = document?.rss?.channel?.item;
  const items = item === undefined ? [] : Array.isArray(item) ? item : [item];
  return {
    sources: items.slice(0, maxResults).map(entry => ({
      title: text(entry?.title),
      url: text(entry?.link),
      snippet: text(entry?.description),
      publishedAt: text(entry?.pubDate) || null,
    })),
  };
}

function normalizeAnySearch(payload, maxResults) {
  if (!isRecord(payload) || payload.code !== 0) {
    throw new ProviderError('Free anysearch search returned an error response', {
      provider: 'free', retryable: true,
    });
  }
  if (!isRecord(payload.data) || !Array.isArray(payload.data.results)) {
    throw malformed('anysearch', 'search');
  }
  return {
    sources: payload.data.results.slice(0, maxResults).map(entry => {
      if (!isRecord(entry)) throw malformed('anysearch', 'search');
      return {
        title: text(entry.title),
        url: text(entry.url),
        snippet: text(entry.content ?? entry.snippet),
        publishedAt: publishedAt(entry),
      };
    }),
  };
}

function duckDuckGoTarget(href) {
  try {
    const url = new URL(href, 'https://duckduckgo.com');
    const hostname = url.hostname.toLowerCase();
    if (hostname === 'duckduckgo.com' || hostname.endsWith('.duckduckgo.com')) {
      const target = url.searchParams.get('uddg');
      if (target) return target;
    }
    return url.href;
  } catch {
    return href;
  }
}

function normalizeDuckDuckGo(html, maxResults) {
  const $ = load(html);
  const resultElements = $('.result');
  const challenge = $('.anomaly-modal, #anomaly-modal, .challenge-form, #challenge-form, .g-recaptcha, #captcha, .captcha').length > 0
    || (resultElements.length === 0 && /anomaly|captcha|challenge/i.test(html));
  if (challenge) {
    throw new ProviderError('Free duckduckgo search received a challenge page', {
      provider: 'free', retryable: true,
    });
  }

  const sources = [];
  resultElements.each((_, element) => {
    const link = $(element).find('.result__a').first();
    const href = link.attr('href');
    if (!href) return;
    sources.push({
      title: link.text().trim(),
      url: duckDuckGoTarget(href),
      snippet: $(element).find('.result__snippet').first().text().trim(),
      publishedAt: null,
    });
  });
  return { sources: sources.slice(0, maxResults) };
}

function normalizeSearXNG(payload, maxResults) {
  if (!isRecord(payload) || !Array.isArray(payload.results)) {
    throw malformed('searxng', 'search');
  }
  return {
    sources: payload.results.slice(0, maxResults).map(entry => {
      if (!isRecord(entry)) throw malformed('searxng', 'search');
      return {
        title: text(entry.title),
        url: text(entry.url),
        snippet: text(entry.content),
        publishedAt: text(entry.publishedDate) || null,
      };
    }),
  };
}

function normalizeRemoteFetch(payload, engine, originalUrl, maxChars) {
  if (!isRecord(payload) || (engine === 'anysearch' ? payload.code !== 0 : payload.code !== 200)) {
    throw new ProviderError(`Free ${engine} fetch returned an error response`, {
      provider: 'free', retryable: true,
    });
  }
  if (!isRecord(payload.data) || typeof payload.data.content !== 'string') {
    throw malformed(engine, 'fetch');
  }
  return {
    title: text(payload.data.title),
    url: text(payload.data.url) || originalUrl,
    content: payload.data.content.slice(0, maxChars),
    truncated: payload.data.content.length > maxChars,
  };
}

function htmlText(html) {
  const $ = load(html);
  const title = $('title').first().text().trim();
  $('script, style, noscript, template, iframe, object, embed, svg, canvas, form, nav, footer').remove();
  $('br').replaceWith('\n');
  $('p, div, article, section, li, h1, h2, h3, h4, h5, h6, tr').each((_, element) => {
    $(element).append('\n');
  });
  const content = ($('body').text() || $.root().text())
    .replace(/\r/g, '')
    .replace(/[\t\f\v ]+/g, ' ')
    .replace(/ *\n */g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  return { title, content };
}

function assertTextContentType(response) {
  const contentType = response.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase() ?? '';
  const supported = contentType.startsWith('text/')
    || contentType === 'application/json'
    || contentType.endsWith('+json')
    || contentType === 'application/xml'
    || contentType.endsWith('+xml')
    || contentType === 'application/xhtml+xml';
  if (!supported) {
    throw new ProviderError('Free fetch received an unsupported content type', {
      provider: 'free',
      retryable: false,
      status: 415,
    });
  }
  return contentType;
}

function validateRemoteUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new InputError('Fetch URL must be a valid HTTP(S) URL');
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new InputError('Fetch URL must use HTTP(S)');
  }
}

export function createFreeProvider(config = {}) {
  const allowPrivate = config.allowPrivate === true;
  const maxResponseBytes = config.maxResponseBytes ?? 1_000_000;
  const engineRoutes = {
    search: config.engines?.search ?? FREE_PROVIDER_DEFAULTS.engines.search,
    fetch: config.engines?.fetch ?? FREE_PROVIDER_DEFAULTS.engines.fetch,
  };
  const anysearch = { ...FREE_PROVIDER_DEFAULTS.anysearch, ...config.anysearch };
  const duckduckgo = { ...FREE_PROVIDER_DEFAULTS.duckduckgo, ...config.duckduckgo };
  const searxng = { ...FREE_PROVIDER_DEFAULTS.searxng, ...config.searxng };
  const jina = { ...FREE_PROVIDER_DEFAULTS.jina, ...config.jina };

  async function requestText(engine, operation, url, options, signal) {
    signal?.throwIfAborted();
    const response = await fetch(url, { ...options, signal });
    if (!response.ok) {
      await response.body?.cancel().catch(() => {});
      throw httpError(`${engine} ${operation}`, response.status);
    }
    return readBoundedResponseText(response, {
      maxBytes: maxResponseBytes,
      provider: 'free',
      operation: `Free ${engine} ${operation}`,
      signal,
    });
  }

  async function requestJson(engine, operation, url, options, signal) {
    const body = await requestText(engine, operation, url, options, signal);
    return parseJson(body, engine, operation);
  }

  async function bingSearch(args, signal) {
    const url = new URL('https://www.bing.com/search');
    url.searchParams.set('q', args.query);
    url.searchParams.set('format', 'rss');
    url.searchParams.set('count', String(args.maxResults));
    const body = await requestText('bing', 'search', url, {
      method: 'GET',
      headers: { accept: 'application/rss+xml, application/xml, text/xml', 'user-agent': USER_AGENT },
    }, signal);
    return normalizeBingSearch(body, args.maxResults);
  }

  async function anySearchSearch(args, signal) {
    const payload = await requestJson('anysearch', 'search', endpoint(anysearch.baseUrl, '/v1/search'), {
      method: 'POST',
      headers: {
        accept: 'application/json',
        'content-type': 'application/json',
        'x-anysearch-client': 'skill/3.1.1',
        ...(anysearch.apiKey?.trim() ? { authorization: `Bearer ${anysearch.apiKey}` } : {}),
      },
      body: JSON.stringify({
        query: args.query,
        max_results: args.maxResults,
        ...(anysearch.zone?.trim() ? { zone: anysearch.zone } : {}),
        ...(anysearch.language?.trim() ? { language: anysearch.language } : {}),
      }),
    }, signal);
    return normalizeAnySearch(payload, args.maxResults);
  }

  async function duckDuckGoSearch(args, signal) {
    const url = new URL(duckduckgo.baseUrl);
    url.searchParams.set('q', args.query);
    if (duckduckgo.region?.trim()) url.searchParams.set('kl', duckduckgo.region);
    const body = await requestText('duckduckgo', 'search', url, {
      method: 'GET',
      headers: { accept: 'text/html', 'user-agent': USER_AGENT },
    }, signal);
    return normalizeDuckDuckGo(body, args.maxResults);
  }

  async function searXNGSearch(args, signal) {
    const url = new URL(endpoint(searxng.baseUrl, '/search'));
    url.searchParams.set('q', args.query);
    url.searchParams.set('format', 'json');
    if (searxng.language?.trim()) url.searchParams.set('language', searxng.language);
    const payload = await requestJson('searxng', 'search', url, {
      method: 'GET',
      headers: { accept: 'application/json', 'user-agent': USER_AGENT },
    }, signal);
    return normalizeSearXNG(payload, args.maxResults);
  }

  async function directFetch(args, signal) {
    const dispatcher = allowPrivate ? undefined : createPublicDispatcher();
    try {
      let current = new URL(args.url);
      for (let redirects = 0; redirects <= 5; redirects += 1) {
        current = await assertPublicUrl(current, { allowPrivate });
        signal?.throwIfAborted();
        const response = await fetch(current, {
          signal,
          dispatcher,
          redirect: 'manual',
          headers: { accept: 'text/html, text/plain, application/json, application/xml', 'user-agent': USER_AGENT },
        });
        if (REDIRECT_STATUSES.has(response.status)) {
          const location = response.headers.get('location');
          await response.body?.cancel().catch(() => {});
          if (!location) throw new ProviderError('Free fetch received a redirect without a location', { provider: 'free' });
          if (redirects === 5) {
            throw new ProviderError('Free fetch exceeded the redirect limit', { provider: 'free', retryable: false });
          }
          current = new URL(location, current);
          continue;
        }
        if (!response.ok) {
          await response.body?.cancel().catch(() => {});
          throw httpError('fetch', response.status);
        }
        let contentType;
        try {
          contentType = assertTextContentType(response);
        } catch (error) {
          await response.body?.cancel().catch(() => {});
          throw error;
        }
        const body = await readBoundedResponseText(response, {
          maxBytes: maxResponseBytes,
          provider: 'free',
          operation: 'Free fetch',
          signal,
        });
        const extracted = contentType === 'text/html' || contentType === 'application/xhtml+xml'
          ? htmlText(body)
          : { title: '', content: body };
        return {
          title: extracted.title,
          url: current.href,
          content: extracted.content.slice(0, args.maxChars),
          truncated: extracted.content.length > args.maxChars,
        };
      }
      throw new ProviderError('Free fetch exceeded the redirect limit', { provider: 'free', retryable: false });
    } finally {
      await dispatcher?.close();
    }
  }

  async function anySearchFetch(args, signal) {
    validateRemoteUrl(args.url);
    const payload = await requestJson('anysearch', 'fetch', endpoint(anysearch.baseUrl, '/v1/extract'), {
      method: 'POST',
      headers: {
        accept: 'application/json',
        'content-type': 'application/json',
        'x-anysearch-client': 'skill/3.1.1',
        ...(anysearch.apiKey?.trim() ? { authorization: `Bearer ${anysearch.apiKey}` } : {}),
      },
      body: JSON.stringify({ url: args.url }),
    }, signal);
    return normalizeRemoteFetch(payload, 'anysearch', args.url, args.maxChars);
  }

  async function jinaFetch(args, signal) {
    validateRemoteUrl(args.url);
    const payload = await requestJson('jina', 'fetch', endpoint(jina.baseUrl, `/${args.url}`), {
      method: 'GET',
      headers: {
        accept: 'application/json',
        ...(jina.apiKey?.trim() ? { authorization: `Bearer ${jina.apiKey}` } : {}),
      },
    }, signal);
    return normalizeRemoteFetch(payload, 'jina', args.url, args.maxChars);
  }

  const handlers = {
    search: {
      anysearch: anySearchSearch,
      bing: bingSearch,
      duckduckgo: duckDuckGoSearch,
      searxng: searXNGSearch,
    },
    fetch: {
      direct: directFetch,
      anysearch: anySearchFetch,
      jina: jinaFetch,
    },
  };

  async function runRoute(operation, args, signal) {
    const attempts = [];
    const route = engineRoutes[operation];
    for (let index = 0; index < route.length; index += 1) {
      const engine = route[index];
      if (engine === 'searxng' && searxng.baseUrl.trim() === '') {
        attempts.push({ engine, outcome: 'skipped', reason: 'unconfigured' });
        continue;
      }
      try {
        signal?.throwIfAborted();
        const result = await handlers[operation][engine](args, signal);
        const isEmpty = operation === 'search' && result.sources.length === 0;
        attempts.push({ engine, outcome: isEmpty ? 'empty' : 'success' });
        return {
          ...result,
          engine,
          engineFallback: index > 0,
          engineAttempts: attempts,
        };
      } catch (error) {
        if (signal?.aborted) throw signal.reason;
        if (error instanceof InputError) throw error;
        const failure = error instanceof ProviderError ? error : new ProviderError(
          `Free ${engine} ${operation} request failed`,
          { provider: 'free', retryable: true },
        );
        const attempt = { engine, outcome: 'error', error: failure.message };
        if (failure.retryable === false) {
          const finalError = new ProviderError(failure.message, {
            provider: 'free', retryable: false, status: failure.status,
          });
          finalError.engineAttempts = [...attempts, attempt];
          throw finalError;
        }
        attempts.push(attempt);
      }
    }

    const detail = attempts
      .filter(attempt => attempt.outcome === 'error')
      .map(attempt => `${attempt.engine}: ${attempt.error}`)
      .join('; ');
    const finalError = new ProviderError(
      detail ? `All free ${operation} engines failed: ${detail}` : `No free ${operation} engines configured`,
      { provider: 'free', retryable: true },
    );
    finalError.engineAttempts = attempts;
    throw finalError;
  }

  async function search(args, { signal } = {}) {
    return guard('search', signal, () => runRoute('search', args, signal));
  }

  async function fetchPage(args, { signal } = {}) {
    return guard('fetch', signal, () => runRoute('fetch', args, signal));
  }

  return { search, fetch: fetchPage };
}
