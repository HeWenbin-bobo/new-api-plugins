import { loadConfig } from '../src/config.js';
import { createGateway, DEFAULT_CONFIG_PATH } from '../src/index.js';

async function main() {
  const [operation, value] = process.argv.slice(2);
  if (!['search', 'fetch'].includes(operation) || !value) {
    process.stderr.write('Usage: node scripts/smoke.js search "query" | fetch "https://example.com"\n');
    process.exitCode = 1;
    return;
  }

  const config = await loadConfig(process.env.UNIFIED_WEB_MCP_CONFIG || DEFAULT_CONFIG_PATH);
  const gateway = createGateway(config);
  try {
    const result = operation === 'search'
      ? await gateway.router.search({ query: value })
      : await gateway.router.fetch({ url: value });
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } finally {
    await gateway.close();
  }
}

main().catch(error => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`Smoke check failed: ${message}\n`);
  process.exitCode = 1;
});
