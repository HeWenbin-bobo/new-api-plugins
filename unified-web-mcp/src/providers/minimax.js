import { Client } from '@modelcontextprotocol/client';
import { StdioClientTransport, getDefaultEnvironment } from '@modelcontextprotocol/client/stdio';
import { ProviderError } from '../errors.js';

function text(value) {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

function unwrapResult(result) {
  if (result?.structuredContent && typeof result.structuredContent === 'object') {
    return result.structuredContent;
  }
  if (result && typeof result === 'object' && !Array.isArray(result.content)) return result;
  const block = result?.content?.find(entry => entry?.type === 'text' && typeof entry.text === 'string');
  if (!block) return result;
  return unwrapResult(JSON.parse(block.text));
}

export function normalizeMiniMaxSearch(payload) {
  const source = unwrapResult(payload);
  if (!Array.isArray(source?.organic)) {
    throw new ProviderError('MiniMax search returned a malformed response', {
      provider: 'minimax',
      retryable: true,
    });
  }
  return {
    sources: source.organic.map(entry => ({
      title: text(entry?.title),
      url: text(entry?.link),
      snippet: text(entry?.snippet),
      publishedAt: text(entry?.date) || null,
    })),
  };
}

function normalizeMiniMaxFetch(payload, requestedUrl, maxChars) {
  const content = text(payload?.content);
  return {
    title: text(payload?.title),
    url: text(payload?.url) || requestedUrl,
    content: content.slice(0, maxChars),
    truncated: payload?.truncated === true || content.length > maxChars,
  };
}

async function defaultClientFactory(options, { signal } = {}) {
  const client = new Client({ name: 'unified-web-mcp', version: '0.1.0' });
  const transport = new StdioClientTransport(options);
  try {
    await client.connect(transport, { signal });
    return client;
  } catch (error) {
    await client.close().catch(() => {});
    throw error;
  }
}

export function createMiniMaxProvider(config = {}, { clientFactory = defaultClientFactory } = {}) {
  const tools = Array.isArray(config.tools) ? config.tools : ['web_search'];
  const searchTool = tools.includes('web_search') ? 'web_search' : null;
  const fetchTool = tools.includes('web_fetch') ? 'web_fetch' : tools.includes('read_url') ? 'read_url' : null;
  const connectTimeoutMs = config.connectTimeoutMs ?? 15_000;
  const closeTimeoutMs = config.closeTimeoutMs ?? 5_000;
  let client;
  let connectionPromise;
  let connectionController;
  let closePromise;
  let closed = false;

  function closedError() {
    return new ProviderError('MiniMax provider is closed', {
      provider: 'minimax',
      retryable: false,
    });
  }

  async function closeClient(connected) {
    if (!connected) return;
    let timer;
    const closing = Promise.resolve().then(() => connected.close()).catch(() => {});
    await Promise.race([
      closing,
      new Promise(resolve => {
        timer = setTimeout(resolve, closeTimeoutMs);
      }),
    ]).finally(() => clearTimeout(timer));
  }

  function getClient() {
    if (closed) throw closedError();
    if (client) return Promise.resolve(client);
    if (!connectionPromise) {
      const controller = new AbortController();
      connectionController = controller;
      let expired = false;
      let onAbort;
      const aborted = new Promise((_, reject) => {
        onAbort = () => reject(controller.signal.reason);
        controller.signal.addEventListener('abort', onAbort, { once: true });
      });
      const options = {
        command: config.command ?? 'uvx',
        args: [...(config.args ?? ['minimax-coding-plan-mcp', '-y'])],
        env: { ...getDefaultEnvironment(), ...config.env },
        stderr: 'ignore',
      };
      const connectedAttempt = Promise.resolve()
        .then(() => clientFactory(options, { signal: controller.signal }))
        .then(async connected => {
          if (closed || expired) {
            await closeClient(connected);
            throw closed ? closedError() : controller.signal.reason;
          }
          client = connected;
          return connected;
        });
      const timer = setTimeout(() => {
        expired = true;
        controller.abort(new ProviderError('MiniMax connection timed out', {
          provider: 'minimax',
          retryable: true,
        }));
      }, connectTimeoutMs);
      const attempt = Promise.race([connectedAttempt, aborted]).finally(() => {
        clearTimeout(timer);
        controller.signal.removeEventListener('abort', onAbort);
      });
      connectionPromise = attempt;
      attempt.catch(() => {
        if (connectionPromise === attempt) connectionPromise = undefined;
      });
    }
    return connectionPromise;
  }

  async function call(operation, name, args, signal, normalize) {
    try {
      signal?.throwIfAborted();
      const connected = await getClient();
      signal?.throwIfAborted();
      const result = await connected.callTool({ name, arguments: args }, { signal });
      if (result?.isError) {
        throw new ProviderError(`MiniMax ${operation} failed`, { provider: 'minimax' });
      }
      return normalize(unwrapResult(result));
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      if (signal?.aborted) throw signal.reason;
      throw new ProviderError(`MiniMax ${operation} failed`, { provider: 'minimax' });
    }
  }

  const adapter = {
    close() {
      if (!closePromise) {
        closed = true;
        connectionController?.abort(closedError());
        closePromise = (async () => {
          let connected = client;
          const pending = connectionPromise;
          if (!connected && pending) {
            try {
              connected = await pending;
            } catch {
              // Late-settling connections are closed by connectedAttempt.
            }
          }
          client = undefined;
          connectionPromise = undefined;
          connectionController = undefined;
          await closeClient(connected);
        })();
      }
      return closePromise;
    },
  };

  if (searchTool) {
    adapter.search = (args, { signal } = {}) => call(
      'search',
      searchTool,
      { query: args.query },
      signal,
      payload => ({
        sources: normalizeMiniMaxSearch(payload).sources.slice(0, args.maxResults ?? 8),
      }),
    );
  }
  if (fetchTool) {
    adapter.fetch = (args, { signal } = {}) => call(
      'fetch',
      fetchTool,
      { url: args.url },
      signal,
      payload => normalizeMiniMaxFetch(payload, args.url, args.maxChars ?? 20_000),
    );
  }
  return adapter;
}
