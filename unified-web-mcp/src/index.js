import { pathToFileURL, fileURLToPath } from 'node:url';
import { McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import { z } from 'zod';
import { loadConfig } from './config.js';
import { createRouter } from './router.js';
import { createFreeProvider } from './providers/free.js';
import { createMiniMaxProvider } from './providers/minimax.js';
import { createDeepSeekProvider } from './providers/deepseek.js';

export const DEFAULT_CONFIG_PATH = fileURLToPath(new URL('../config.json', import.meta.url));

function isNonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function diagnostic(error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`unified-web-mcp: ${message}\n`);
}

export function createGateway(config) {
  const minimax = config.providers.minimax ?? {};
  const deepseek = config.providers.deepseek ?? {};
  const providers = { free: createFreeProvider(config.providers.free) };

  if (isNonEmptyString(minimax.command) && isNonEmptyString(minimax.env?.MINIMAX_API_KEY)) {
    providers.minimax = createMiniMaxProvider(minimax);
  }
  if (isNonEmptyString(deepseek.apiKey)) {
    providers.deepseek = createDeepSeekProvider(deepseek);
  }

  const router = createRouter(config, providers);
  const secrets = [
    ...Object.values(minimax.env ?? {}),
    deepseek.apiKey,
  ].filter(isNonEmptyString).sort((a, b) => b.length - a.length);

  function jsonResult(value) {
    return { content: [{ type: 'text', text: JSON.stringify(value, null, 2) }] };
  }

  async function toolResult(action) {
    try {
      return jsonResult(await action());
    } catch (error) {
      let message = error instanceof Error ? error.message : String(error);
      for (const secret of secrets) message = message.replaceAll(secret, '[redacted]');
      message = message.replace(/Bearer\s+\S+/gi, 'Bearer [redacted]');
      return { ...jsonResult({ error: message }), isError: true };
    }
  }

  function createServer() {
    const server = new McpServer({ name: 'unified-web-mcp', version: '0.1.0' });

    server.registerTool('unified_web_search', {
      title: 'Unified web search',
      description: 'Search the web through the configured provider route.',
      inputSchema: z.object({
        query: z.string().trim().min(1),
        max_results: z.number().int().positive().optional(),
      }),
    }, ({ query, max_results }, context) => toolResult(() => router.search(
      { query, maxResults: max_results },
      { signal: context.mcpReq.signal },
    )));

    server.registerTool('unified_web_fetch', {
      title: 'Unified web fetch',
      description: 'Fetch and normalize a public web page through the configured provider route.',
      inputSchema: z.object({
        url: z.string().trim().min(1),
        max_chars: z.number().int().positive().optional(),
      }),
    }, ({ url, max_chars }, context) => toolResult(() => router.fetch(
      { url, maxChars: max_chars },
      { signal: context.mcpReq.signal },
    )));

    server.registerTool('unified_web_status', {
      title: 'Unified web status',
      description: 'Report provider configuration, capabilities, and cooldown state without credentials.',
      inputSchema: z.object({}),
    }, () => toolResult(async () => router.status()));

    return server;
  }

  return { router, createServer, close: () => router.close() };
}

async function main() {
  const config = await loadConfig(process.env.UNIFIED_WEB_MCP_CONFIG || DEFAULT_CONFIG_PATH);
  const gateway = createGateway(config);
  let handle;
  let shutdownPromise;

  function shutdown() {
    if (!shutdownPromise) {
      shutdownPromise = (async () => {
        if (handle) await handle.close().catch(diagnostic);
        await gateway.close();
      })();
    }
    return shutdownPromise;
  }

  handle = serveStdio(() => gateway.createServer(), { onerror: diagnostic });
  process.stdin.once('end', shutdown);
  process.stdin.once('close', shutdown);

  const onSignal = signal => {
    shutdown().then(() => {
      process.exitCode = signal === 'SIGINT' ? 130 : 143;
      process.exit();
    }, error => {
      diagnostic(error);
      process.exitCode = 1;
      process.exit();
    });
  };
  process.once('SIGINT', onSignal);
  process.once('SIGTERM', onSignal);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => {
    diagnostic(error);
    process.exitCode = 1;
  });
}
