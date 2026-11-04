import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/client';
import { StdioClientTransport, getDefaultEnvironment } from '@modelcontextprotocol/client/stdio';
import { validateConfig } from '../src/config.js';
import { createGateway } from '../src/index.js';

const ENTRYPOINT = fileURLToPath(new URL('../src/index.js', import.meta.url));
const DUMMY_MINIMAX_SECRET = 'dummy-minimax-secret-not-a-real-key';

function textContent(result) {
  const block = result.content?.find(entry => entry?.type === 'text');
  assert.ok(block, 'tool result contains a text block');
  return block.text;
}

function configuredProviders(status) {
  return Object.fromEntries(status.providers.map(provider => [provider.name, provider.configured]));
}

for (const [label, options] of [
  ['default legacy handshake', undefined],
  ['modern auto negotiation', { versionNegotiation: { mode: 'auto' } }],
]) {
  test(`stdio MCP tools and sanitized status work with ${label}`, { timeout: 30000 }, async () => {
    const directory = mkdtempSync(join(tmpdir(), 'unified-web-mcp-test-'));
    const configPath = join(directory, 'config.json');
    writeFileSync(configPath, JSON.stringify({
      routes: { search: ['free'], fetch: ['free'] },
      providers: {
        free: {},
        minimax: { env: { MINIMAX_API_KEY: DUMMY_MINIMAX_SECRET } },
        deepseek: { apiKey: '' },
      },
    }), 'utf8');

    const transport = new StdioClientTransport({
      command: process.execPath,
      args: [ENTRYPOINT],
      cwd: directory,
      env: { ...getDefaultEnvironment(), UNIFIED_WEB_MCP_CONFIG: configPath },
      stderr: 'pipe',
    });
    transport.stderr?.resume();
    const client = new Client({ name: 'unified-web-mcp-test', version: '0.1.0' }, options);

    try {
      await client.connect(transport);
      const { tools } = await client.listTools();
      assert.deepEqual(
        tools.map(tool => tool.name).sort(),
        ['unified_web_fetch', 'unified_web_search', 'unified_web_status'],
      );
      assert.deepEqual(
        Object.keys(tools.find(tool => tool.name === 'unified_web_search').inputSchema.properties).sort(),
        ['max_results', 'query'],
      );
      assert.deepEqual(
        Object.keys(tools.find(tool => tool.name === 'unified_web_fetch').inputSchema.properties).sort(),
        ['max_chars', 'url'],
      );

      const result = await client.callTool({ name: 'unified_web_status', arguments: {} });
      assert.notEqual(result.isError, true);
      const text = textContent(result);
      assert.equal(text.includes(DUMMY_MINIMAX_SECRET), false);
      assert.equal(text.includes('MINIMAX_API_KEY'), false);
      const status = JSON.parse(text);
      assert.deepEqual(configuredProviders(status), { free: true });
    } finally {
      await client.close().catch(() => {});
      await transport.close().catch(() => {});
      rmSync(directory, { recursive: true, force: true });
    }
  });
}

test('createGateway does not enable incomplete paid-provider configs', async () => {
  const gateway = createGateway(validateConfig({
    providers: {
      minimax: { env: { MINIMAX_API_KEY: DUMMY_MINIMAX_SECRET } },
      deepseek: { apiKey: '' },
    },
  }));
  try {
    assert.deepEqual(configuredProviders(gateway.router.status()), {
      free: true,
      minimax: false,
      deepseek: false,
    });
  } finally {
    await gateway.close();
  }
});

test('createGateway enables complete dummy paid-provider configs without connecting them', async () => {
  const gateway = createGateway(validateConfig({
    providers: {
      minimax: {
        command: 'node',
        args: ['dummy-minimax-server.js'],
        env: { MINIMAX_API_KEY: DUMMY_MINIMAX_SECRET },
      },
      deepseek: { apiKey: 'dummy-deepseek-secret-not-a-real-key' },
    },
  }));
  try {
    assert.deepEqual(configuredProviders(gateway.router.status()), {
      free: true,
      minimax: true,
      deepseek: true,
    });
  } finally {
    await gateway.close();
  }
});
