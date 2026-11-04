import { InputError, ProviderError } from './errors.js';

function validateArgs(operation, args, server) {
  if (!args || typeof args !== 'object') {
    throw new InputError(`${operation} arguments must be an object`);
  }

  if (operation === 'search') {
    if (typeof args.query !== 'string' || args.query.trim().length === 0) {
      throw new InputError('Search query must be a non-empty string');
    }
    const maxResults = args.maxResults ?? server.maxSearchResults;
    if (!Number.isInteger(maxResults) || maxResults <= 0) {
      throw new InputError('maxResults must be a positive integer');
    }
    return { query: args.query, maxResults: Math.min(maxResults, server.maxSearchResults) };
  }

  let url;
  try {
    url = new URL(args.url);
  } catch {
    throw new InputError('Fetch URL must be a valid HTTP(S) URL');
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new InputError('Fetch URL must use HTTP(S)');
  }
  const maxChars = args.maxChars ?? server.maxFetchChars;
  if (!Number.isInteger(maxChars) || maxChars <= 0) {
    throw new InputError('maxChars must be a positive integer');
  }
  return { url: args.url, maxChars: Math.min(maxChars, server.maxFetchChars) };
}

function collectSecrets(providerConfig) {
  const secrets = [];
  const sensitiveName = /key|token|secret|password|credential|authorization/i;
  function visit(value, parent = '') {
    if (!value || typeof value !== 'object') return;
    for (const [key, child] of Object.entries(value)) {
      if (typeof child === 'string' && child && (parent === 'env' || sensitiveName.test(key))) {
        secrets.push(child);
      } else if (child && typeof child === 'object') {
        visit(child, key);
      }
    }
  }
  visit(providerConfig);
  return secrets.sort((a, b) => b.length - a.length);
}

function sanitizeMessage(error, secrets) {
  let message = error instanceof Error ? error.message : String(error);
  for (const secret of secrets) {
    message = message.replaceAll(secret, '[redacted]');
  }
  return message.replace(/Bearer\s+\S+/gi, 'Bearer [redacted]');
}

function abortReason(signal) {
  return signal.reason ?? new DOMException('The operation was aborted', 'AbortError');
}

async function callProvider(adapter, operation, args, provider, timeoutMs, callerSignal) {
  const controller = new AbortController();
  const onCallerAbort = () => controller.abort(abortReason(callerSignal));
  if (callerSignal) {
    if (callerSignal.aborted) throw abortReason(callerSignal);
    callerSignal.addEventListener('abort', onCallerAbort, { once: true });
  }

  const timer = setTimeout(() => {
    controller.abort(new ProviderError(`${operation} attempt timed out`, {
      provider,
      retryable: true,
    }));
  }, timeoutMs);

  const aborted = new Promise((resolve, reject) => {
    if (controller.signal.aborted) {
      reject(controller.signal.reason);
    } else {
      controller.signal.addEventListener('abort', () => reject(controller.signal.reason), { once: true });
    }
  });

  try {
    return await Promise.race([
      Promise.resolve().then(() => adapter[operation](args, { signal: controller.signal })),
      aborted,
    ]);
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener('abort', onCallerAbort);
  }
}

export function createRouter(config, providers) {
  const cooldowns = new Map();
  const secrets = collectSecrets(config.providers);
  let closePromise;

  function cooldownKey(operation, provider) {
    return `${operation}:${provider}`;
  }

  function isCoolingDown(operation, provider, now = Date.now()) {
    const key = cooldownKey(operation, provider);
    const until = cooldowns.get(key) ?? 0;
    if (until <= now) {
      cooldowns.delete(key);
      return false;
    }
    return true;
  }

  async function execute(operation, input, context = {}) {
    const args = validateArgs(operation, input, config.server);
    const callerSignal = context?.signal;
    if (callerSignal?.aborted) throw abortReason(callerSignal);

    const deadline = Date.now() + config.server.requestTimeoutMs;
    const attempts = [];
    let lastError;
    let lastEmpty;

    for (let index = 0; index < config.routes[operation].length; index += 1) {
      const name = config.routes[operation][index];
      const adapter = providers[name];
      if (typeof adapter?.[operation] !== 'function') {
        attempts.push({ provider: name, outcome: 'skipped', reason: 'unsupported' });
        continue;
      }
      if (isCoolingDown(operation, name)) {
        attempts.push({ provider: name, outcome: 'skipped', reason: 'cooldown' });
        continue;
      }

      const remaining = deadline - Date.now();
      if (remaining <= 0) {
        lastError = new ProviderError(`${operation} total deadline exceeded`, {
          provider: name,
          retryable: true,
        });
        break;
      }

      try {
        const result = await callProvider(
          adapter,
          operation,
          args,
          name,
          Math.min(config.server.providerTimeoutMs, remaining),
          callerSignal,
        );
        const isEmpty = operation === 'search' && Array.isArray(result?.sources) && result.sources.length === 0;
        attempts.push({ provider: name, outcome: isEmpty ? 'empty' : 'success' });

        if (isEmpty && config.server.fallbackOnEmptySearch) {
          lastEmpty = { result, name, index };
          continue;
        }
        return { ...result, provider: name, fallback: index > 0, attempts };
      } catch (error) {
        if (callerSignal?.aborted) throw abortReason(callerSignal);
        if (error instanceof InputError) {
          throw new InputError(sanitizeMessage(error, secrets));
        }
        if (error instanceof ProviderError && error.retryable === false) {
          const message = sanitizeMessage(error, secrets);
          const finalError = new ProviderError(message, {
            provider: error.provider ?? name,
            retryable: false,
            status: error.status,
          });
          finalError.attempts = [
            ...attempts,
            { provider: name, outcome: 'error', error: message },
          ];
          throw finalError;
        }

        lastError = error;
        cooldowns.set(cooldownKey(operation, name), Date.now() + config.server.cooldownMs);
        attempts.push({
          provider: name,
          outcome: 'error',
          error: sanitizeMessage(error, secrets),
        });
        if (Date.now() >= deadline) break;
      }
    }

    if (lastEmpty && !lastError) {
      return {
        ...lastEmpty.result,
        provider: lastEmpty.name,
        fallback: lastEmpty.index > 0,
        attempts,
      };
    }

    const detail = attempts
      .filter(attempt => attempt.outcome === 'error')
      .map(attempt => `${attempt.provider}: ${attempt.error}`)
      .join('; ');
    const message = detail || lastError
      ? `All ${operation} providers failed${detail ? `: ${detail}` : `: ${sanitizeMessage(lastError, secrets)}`}`
      : `No ${operation} providers available`;
    const finalError = new ProviderError(message, {
      provider: lastError?.provider,
      retryable: true,
    });
    finalError.attempts = attempts;
    throw finalError;
  }

  function status() {
    const names = [...new Set([
      ...Object.keys(providers),
      ...config.routes.search,
      ...config.routes.fetch,
    ])];
    return {
      providers: names.map(name => ({
        name,
        configured: typeof providers[name] === 'object' && providers[name] !== null,
        capabilities: {
          search: typeof providers[name]?.search === 'function',
          fetch: typeof providers[name]?.fetch === 'function',
        },
        cooldown: {
          search: isCoolingDown('search', name),
          fetch: isCoolingDown('fetch', name),
        },
      })),
    };
  }

  function close() {
    if (!closePromise) {
      const adapters = [...new Set(Object.values(providers))];
      closePromise = Promise.all(adapters.map(adapter => (
        Promise.resolve().then(() => adapter.close?.())
      ))).then(() => undefined);
    }
    return closePromise;
  }

  return {
    search: (args, context) => execute('search', args, context),
    fetch: (args, context) => execute('fetch', args, context),
    status,
    close,
  };
}
