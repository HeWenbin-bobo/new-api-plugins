import { readFileSync } from 'node:fs';
import { basename } from 'node:path';
import { spawnSync } from 'node:child_process';

const ZERO = '0'.repeat(40);
const LIMIT = 5 * 1024 * 1024;
const args = process.argv.slice(2);
const findings = new Set();

function git(commandArgs, input) {
  const result = spawnSync('git', commandArgs, {
    input,
    encoding: null,
    maxBuffer: 64 * 1024 * 1024,
    timeout: 30000,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`Git inspection failed (${commandArgs[0]}); refusing to push`);
  }
  return result.stdout;
}

function text(value) {
  return value.toString('utf8');
}

function credentialValues(buffer) {
  const values = [];
  const source = text(buffer);
  if (source.length > 1024 * 1024) return values;
  try {
    const pending = [JSON.parse(source)];
    while (pending.length) {
      const value = pending.pop();
      if (Array.isArray(value)) {
        pending.push(...value);
      } else if (value && typeof value === 'object') {
        for (const [key, child] of Object.entries(value)) {
          if (typeof child === 'string' && /api.?key|token|secret|password|credential|authorization/i.test(key) && child.trim().length >= 8) {
            values.push(child.trim());
          } else if (child && typeof child === 'object') {
            pending.push(child);
          }
        }
      }
    }
  } catch {
    for (const match of source.matchAll(/^\s*(?:export\s+)?([^#\s=]+)\s*=\s*(.*?)\s*$/gm)) {
      if (/api.?key|token|secret|password|credential|authorization/i.test(match[1])) {
        const value = match[2].replace(/^(['"])(.*)\1$/, '$2').trim();
        if (value.length >= 8) values.push(value);
      }
    }
  }
  return values;
}

function localSecrets() {
  const secrets = [];
  const paths = new Set();
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === '--local-config') paths.add(args[++index]);
  }
  if (!args.includes('--no-local-config')) {
    const ignored = text(git(['ls-files', '--others', '--ignored', '--exclude-standard', '-z']));
    for (const path of ignored.split('\0').filter(Boolean)) {
      const name = basename(path);
      if (/^(?:config(?:\.local)?\.json|\.env(?:\..+)?)$/.test(name) && name !== '.env.example') paths.add(path);
    }
  }
  for (const path of paths) {
    try {
      secrets.push(...credentialValues(readFileSync(path)));
    } catch (error) {
      if (error?.code !== 'ENOENT') throw new Error(`Cannot inspect local configuration: ${path}`);
    }
  }
  return [...new Set(secrets)].filter((value) => value.length <= 4096);
}

function inspect(path, data, secrets) {
  if (findings.size >= 30 || data.length > LIMIT) {
    if (data.length > LIMIT) findings.add(`${path}: file exceeds the 5 MB scan limit`);
    return;
  }
  const lower = path.toLowerCase();
  if (/(?:^|\/)(?:config(?:\.local)?\.json|\.env(?:\..+)?)$/.test(lower) && !lower.endsWith('/.env.example') && lower !== '.env.example') {
    findings.add(`${path}: private local configuration`);
  }
  if (/\.(?:zip|7z|rar|tar|tgz)$/i.test(path)) findings.add(`${path}: generated archive; use a Release asset`);
  if (/(?:^|\/)(?:node_modules|__pycache__|\.idea|\.vscode|\.omc|\.remember)\//.test(lower)) findings.add(`${path}: local dependency or tool state`);
  if (data.includes(0)) return;
  const source = text(data);
  if (/(?:^|\/)config\.example\.json$/.test(lower)) {
    try {
      const pending = [JSON.parse(source)];
      while (pending.length) {
        const value = pending.pop();
        if (Array.isArray(value)) pending.push(...value);
        else if (value && typeof value === 'object') {
          for (const [key, child] of Object.entries(value)) {
            if (/api.?key|token|secret|password|credential|authorization/i.test(key) && typeof child === 'string' && child.trim()) {
              findings.add(`${path}: non-empty credential in example configuration`);
            } else if (child && typeof child === 'object') pending.push(child);
          }
        }
      }
    } catch {
      findings.add(`${path}: invalid example JSON`);
    }
  }
  const patterns = [
    ['OpenAI-style key', /\bsk-[A-Za-z0-9_-]{20,}\b/],
    ['GitHub token', /\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b/],
    ['GitLab token', /\bglpat-[A-Za-z0-9_-]{20,}\b/],
    ['Slack token', /\bxox[baprs]-[A-Za-z0-9-]{20,}\b/],
    ['AWS access key', /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/],
    ['JWT', /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/],
    ['private key', /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/],
    ['Bearer credential', /Bearer\s+[A-Za-z0-9._~+/-]{16,}={0,2}/],
  ];
  for (const [label, pattern] of patterns) {
    if (pattern.test(source)) findings.add(`${path}: ${label}`);
  }
  for (const secret of secrets) {
    if (source.includes(secret)) findings.add(`${path}: exact local credential value`);
  }
}

function objectsForRange(range) {
  const commits = text(git(['rev-list', range])).trim().split('\n').filter(Boolean);
  const blobs = new Map();
  for (const commit of commits) {
    const rows = git(['ls-tree', '-r', '-z', commit]);
    for (const row of rows.toString('utf8').split('\0').filter(Boolean)) {
      const tab = row.indexOf('\t');
      const [mode, type, id] = row.slice(0, tab).split(' ');
      if (type !== 'blob' || mode === '120000') continue;
      if (!blobs.has(id)) blobs.set(id, new Set());
      blobs.get(id).add(row.slice(tab + 1));
    }
  }
  return blobs;
}

function stdinObjects() {
  const blobs = new Map();
  for (const line of text(readFileSync(0)).split('\n').filter(Boolean)) {
    const [, localId, , remoteId] = line.trim().split(/\s+/);
    if (!localId || localId === ZERO) continue;
    const range = remoteId && remoteId !== ZERO ? `${remoteId}..${localId}` : localId;
    for (const [id, paths] of objectsForRange(range)) {
      if (!blobs.has(id)) blobs.set(id, new Set());
      for (const path of paths) blobs.get(id).add(path);
    }
  }
  return blobs;
}

function indexObjects() {
  const blobs = new Map();
  for (const row of text(git(['ls-files', '--stage', '-z'])).split('\0').filter(Boolean)) {
    const tab = row.indexOf('\t');
    const [mode, id] = row.slice(0, tab).split(' ');
    if (mode === '120000') continue;
    if (!blobs.has(id)) blobs.set(id, new Set());
    blobs.get(id).add(row.slice(tab + 1));
  }
  return blobs;
}

try {
  const rangeIndex = args.indexOf('--range');
  let blobs;
  if (rangeIndex >= 0) blobs = objectsForRange(args[rangeIndex + 1]);
  else if (args.includes('--all')) {
    blobs = indexObjects();
    const head = spawnSync('git', ['rev-parse', '--verify', 'HEAD'], { encoding: 'utf8' });
    if (head.status === 0) {
      for (const [id, paths] of objectsForRange('HEAD')) {
        if (!blobs.has(id)) blobs.set(id, new Set());
        for (const path of paths) blobs.get(id).add(path);
      }
    }
  } else blobs = stdinObjects();
  const secrets = localSecrets();
  for (const [id, paths] of blobs) {
    const data = git(['cat-file', 'blob', id]);
    for (const path of paths) inspect(path, data, secrets);
  }
  if (findings.size) {
    console.error('Push blocked by the local public-repository safety check:');
    for (const finding of [...findings].sort().slice(0, 30)) console.error(`- ${finding}`);
    console.error('No secret values are displayed. Remove the content from every outgoing commit; do not bypass this check for real credentials.');
    process.exitCode = 1;
  } else {
    console.error(`Pre-push safety check passed (${blobs.size} unique blobs; no secret values displayed).`);
  }
} catch (error) {
  console.error(`Push blocked: ${error instanceof Error ? error.message : 'local safety inspection failed'}`);
  process.exitCode = 1;
}
