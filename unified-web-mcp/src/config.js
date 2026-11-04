import { readFile } from 'node:fs/promises';

const PROVIDER_NAMES = ['free', 'minimax', 'deepseek'];
const DEFAULT_ROUTE = ['free', 'minimax', 'deepseek'];
const FREE_SEARCH_ENGINES = ['anysearch', 'bing', 'duckduckgo', 'searxng'];
const FREE_FETCH_ENGINES = ['direct', 'anysearch', 'jina'];

export const FREE_PROVIDER_DEFAULTS = {
  engines: {
    search: FREE_SEARCH_ENGINES,
    fetch: FREE_FETCH_ENGINES,
  },
  anysearch: {
    baseUrl: 'https://api.anysearch.com',
    apiKey: '',
    zone: '',
    language: '',
  },
  duckduckgo: {
    baseUrl: 'https://html.duckduckgo.com/html/',
    region: '',
  },
  searxng: { baseUrl: '', language: '' },
  jina: { baseUrl: 'https://r.jina.ai', apiKey: '' },
};

const SERVER_DEFAULTS = {
  providerTimeoutMs: 12000,
  requestTimeoutMs: 40000,
  cooldownMs: 30000,
  maxSearchResults: 8,
  maxFetchChars: 20000,
  fallbackOnEmptySearch: false,
};

const POSITIVE_INT_FIELDS = [
  'providerTimeoutMs',
  'requestTimeoutMs',
  'cooldownMs',
  'maxSearchResults',
  'maxFetchChars',
];

function assertObject(value, field) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(`Invalid config: ${field} must be an object`);
  }
}

function assertPositiveInt(value, field) {
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`Invalid config: server.${field} must be a positive integer (got ${value})`);
  }
}

function assertRoute(name, value) {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`Invalid config: routes.${name} must be a non-empty array`);
  }
  for (const provider of value) {
    if (!PROVIDER_NAMES.includes(provider)) {
      throw new Error(`Unknown provider: ${provider} in routes.${name}`);
    }
  }
}

function assertNonEmptyTrimmedString(value, field) {
  if (typeof value !== 'string') {
    throw new Error(`Invalid config: ${field} must be a string`);
  }
  if (value.trim().length === 0) {
    throw new Error(`Invalid config: ${field} must be a non-empty string`);
  }
}

function assertMiniMax(minimax) {
  if (minimax.command !== undefined) {
    assertNonEmptyTrimmedString(minimax.command, 'providers.minimax.command');
  }
  if (minimax.args !== undefined) {
    if (!Array.isArray(minimax.args)) {
      throw new Error('Invalid config: providers.minimax.args must be an array of strings');
    }
    for (const arg of minimax.args) {
      if (typeof arg !== 'string') {
        throw new Error('Invalid config: providers.minimax.args must be an array of strings');
      }
    }
  }
  if (minimax.tools !== undefined) {
    if (!Array.isArray(minimax.tools)) {
      throw new Error('Invalid config: providers.minimax.tools must be an array of non-empty strings');
    }
    for (const tool of minimax.tools) {
      assertNonEmptyTrimmedString(tool, 'providers.minimax.tools[]');
    }
  }
  if (minimax.env !== undefined) {
    if (typeof minimax.env !== 'object' || minimax.env === null || Array.isArray(minimax.env)) {
      throw new Error('Invalid config: providers.minimax.env must be an object');
    }
    for (const [key, value] of Object.entries(minimax.env)) {
      if (typeof key !== 'string' || key.trim().length === 0) {
        throw new Error('Invalid config: providers.minimax.env keys must be non-empty strings');
      }
      if (typeof value !== 'string') {
        throw new Error(`Invalid config: providers.minimax.env["${key}"] must be a string`);
      }
    }
  }
}

function assertDeepSeek(deepseek) {
  if (deepseek.baseUrl === undefined) return;
  if (typeof deepseek.baseUrl !== 'string') {
    throw new Error('Invalid config: providers.deepseek.baseUrl must be a string');
  }
  let url;
  try {
    url = new URL(deepseek.baseUrl);
  } catch {
    throw new Error(`Invalid config: providers.deepseek.baseUrl is not a valid URL: ${deepseek.baseUrl}`);
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new Error(`Invalid config: providers.deepseek.baseUrl must be http(s): ${deepseek.baseUrl}`);
  }
}

function assertOptionalString(value, field) {
  if (value !== undefined && typeof value !== 'string') {
    throw new Error(`Invalid config: ${field} must be a string`);
  }
}

function assertFreeBaseUrl(value, field, allowEmpty = false) {
  if (typeof value !== 'string') {
    throw new Error(`Invalid config: ${field} must be a string`);
  }
  if (allowEmpty && value.trim() === '') return;
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`Invalid config: ${field} must be a valid HTTP(S) URL`);
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new Error(`Invalid config: ${field} must be an HTTP(S) URL`);
  }
}

function normalizeFree(free) {
  if (free.engines !== undefined) assertObject(free.engines, 'providers.free.engines');
  for (const operation of ['search', 'fetch']) {
    const route = free.engines?.[operation];
    if (route !== undefined && (!Array.isArray(route) || route.length === 0)) {
      throw new Error(`Invalid config: providers.free.engines.${operation} must be a non-empty array`);
    }
  }
  for (const engine of ['anysearch', 'duckduckgo', 'searxng', 'jina']) {
    if (free[engine] !== undefined) assertObject(free[engine], `providers.free.${engine}`);
  }

  const normalized = {
    ...free,
    engines: {
      search: [...(free.engines?.search ?? FREE_PROVIDER_DEFAULTS.engines.search)],
      fetch: [...(free.engines?.fetch ?? FREE_PROVIDER_DEFAULTS.engines.fetch)],
    },
    anysearch: { ...FREE_PROVIDER_DEFAULTS.anysearch, ...free.anysearch },
    duckduckgo: { ...FREE_PROVIDER_DEFAULTS.duckduckgo, ...free.duckduckgo },
    searxng: { ...FREE_PROVIDER_DEFAULTS.searxng, ...free.searxng },
    jina: { ...FREE_PROVIDER_DEFAULTS.jina, ...free.jina },
  };

  for (const [operation, allowed] of [['search', FREE_SEARCH_ENGINES], ['fetch', FREE_FETCH_ENGINES]]) {
    const route = normalized.engines[operation];
    if (!Array.isArray(route) || route.length === 0) {
      throw new Error(`Invalid config: providers.free.engines.${operation} must be a non-empty array`);
    }
    for (const engine of route) {
      if (!allowed.includes(engine)) {
        throw new Error(`Invalid config: unknown ${engine} in providers.free.engines.${operation}`);
      }
    }
  }

  for (const engine of ['anysearch', 'duckduckgo', 'jina']) {
    assertFreeBaseUrl(normalized[engine].baseUrl, `providers.free.${engine}.baseUrl`);
  }
  assertFreeBaseUrl(normalized.searxng.baseUrl, 'providers.free.searxng.baseUrl', true);
  for (const [engine, fields] of [
    ['anysearch', ['apiKey', 'zone', 'language']],
    ['duckduckgo', ['region']],
    ['searxng', ['language']],
    ['jina', ['apiKey']],
  ]) {
    for (const field of fields) {
      assertOptionalString(normalized[engine][field], `providers.free.${engine}.${field}`);
    }
  }
  return normalized;
}

export function validateConfig(input = {}) {
  assertObject(input, 'config');
  const config = structuredClone(input);
  for (const section of ['server', 'routes', 'providers']) {
    if (config[section] !== undefined) assertObject(config[section], section);
  }

  config.server = { ...SERVER_DEFAULTS, ...config.server };
  config.routes = {
    search: [...DEFAULT_ROUTE],
    fetch: [...DEFAULT_ROUTE],
    ...config.routes,
  };
  config.providers = { free: {}, minimax: {}, deepseek: {}, ...config.providers };

  for (const field of POSITIVE_INT_FIELDS) {
    assertPositiveInt(config.server[field], field);
  }
  if (typeof config.server.fallbackOnEmptySearch !== 'boolean') {
    throw new Error('Invalid config: server.fallbackOnEmptySearch must be a boolean');
  }

  assertRoute('search', config.routes.search);
  assertRoute('fetch', config.routes.fetch);

  for (const name of PROVIDER_NAMES) {
    if (config.providers[name] !== undefined) {
      assertObject(config.providers[name], `providers.${name}`);
    }
  }
  config.providers.free = normalizeFree(config.providers.free);
  assertMiniMax(config.providers.minimax);
  assertDeepSeek(config.providers.deepseek);

  return config;
}

export async function loadConfig(path) {
  const raw = await readFile(path, 'utf8');
  const parsed = JSON.parse(raw);
  return validateConfig(parsed);
}
