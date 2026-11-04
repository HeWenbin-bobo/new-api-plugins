import { ProviderError } from '../errors.js';
import { readBoundedResponseText } from '../http.js';

const RETRYABLE_STATUSES = new Set([401, 402, 403, 408, 413, 429]);

function text(value) {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

export function normalizeDeepSeekSearch(payload) {
  if (!Array.isArray(payload?.results)) {
    throw new ProviderError('DeepSeek search returned a malformed response', {
      provider: 'deepseek',
      retryable: true,
    });
  }
  return {
    sources: payload.results.map(entry => ({
      title: text(entry?.title),
      url: text(entry?.url),
      snippet: text(entry?.summary),
      publishedAt: text(entry?.date) || null,
    })),
  };
}

export function createDeepSeekProvider(config = {}) {
  const baseUrl = (config.baseUrl ?? 'https://api.deepseek.com/v1').replace(/\/+$/, '');
  const maxResponseBytes = config.maxResponseBytes ?? 1_000_000;

  async function request(operation, path, body, signal) {
    if (!config.apiKey) {
      throw new ProviderError('DeepSeek API key is not configured', {
        provider: 'deepseek',
        retryable: false,
      });
    }
    try {
      signal?.throwIfAborted();
      const response = await fetch(`${baseUrl}${path}`, {
        method: 'POST',
        headers: {
          authorization: `Bearer ${config.apiKey}`,
          'content-type': 'application/json',
        },
        body: JSON.stringify(body),
        signal,
      });
      if (!response.ok) {
        throw new ProviderError(`DeepSeek ${operation} failed with HTTP ${response.status}`, {
          provider: 'deepseek',
          retryable: RETRYABLE_STATUSES.has(response.status) || response.status >= 500,
          status: response.status,
        });
      }
      const responseBody = await readBoundedResponseText(response, {
        maxBytes: maxResponseBytes,
        provider: 'deepseek',
        operation: `DeepSeek ${operation}`,
        signal,
      });
      return JSON.parse(responseBody);
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      if (signal?.aborted) throw signal.reason;
      throw new ProviderError(`DeepSeek ${operation} request failed`, { provider: 'deepseek' });
    }
  }

  return {
    async search(args, { signal } = {}) {
      const maxResults = args.maxResults ?? 8;
      const payload = await request('search', '/tools/search', {
        query: args.query,
        count: maxResults,
        need_content: false,
      }, signal);
      return {
        sources: normalizeDeepSeekSearch(payload).sources.slice(0, maxResults),
      };
    },

    async fetch(args, { signal } = {}) {
      const maxChars = args.maxChars ?? 20_000;
      const payload = await request('fetch', '/tools/fetch', { url: args.url }, signal);
      const content = text(payload?.content);
      return {
        title: text(payload?.title),
        url: text(payload?.url) || args.url,
        content: content.slice(0, maxChars),
        truncated: payload?.truncated === true || content.length > maxChars,
      };
    },
  };
}
