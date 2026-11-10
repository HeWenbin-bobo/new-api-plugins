import { readFileSync } from 'node:fs';
import { basename } from 'node:path';
import { spawnSync } from 'node:child_process';
import { inflateRawSync } from 'node:zlib';

const ZERO = '0'.repeat(40);
const LIMIT = 5 * 1024 * 1024;
const ARCHIVE = /\.(?:zip|7z|rar|tar|tgz|gz|bz2|xz|zst|lz4|lz|lzma|jar|war|apk|iso|cab|cpio|arj|lzh|ace)$/i;
const RELEASE_ZIPS = new Set([
  'video_wb2api_hub_newapi/video_wb2api_hub_newapi.zip',
  'video_wb2api_panel_newapi/video_wb2api_panel_newapi.zip',
  'jihuarst-image/jihuarst-image.zip',
  'jihuarst-video/jihuarst-video.zip',
  'zaiwen-image-generation/zaiwen-image-generation.zip',
  'unified-web-mcp/unified-web-mcp-package/unified-web-mcp-0.1.0.zip',
  'local-ocr-task-plugin/local-ocr-task-plugin.zip',
  'local-document-ocr/local-document-ocr.zip',
]);
const MAX_ZIP_ENTRIES = 2048;
const MAX_ZIP_ENTRY_BYTES = 16 * 1024 * 1024;
const MAX_ZIP_TOTAL_BYTES = 64 * 1024 * 1024;
const args = process.argv.slice(2);
const findings = new Set();

class ZipError extends Error {}

const crcTable = Array.from({ length: 256 }, (_, index) => {
  let value = index;
  for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  return value >>> 0;
});

function crc32(data) {
  let crc = 0xffffffff;
  for (const byte of data) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function git(commandArgs, input) {
  const result = spawnSync('git', commandArgs, {
    input,
    encoding: null,
    maxBuffer: 160 * 1024 * 1024,
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
  if (source.length > 1024 * 1024) {
    // An uninspectable local config must not silently yield "no secrets".
    throw new Error('Local configuration is too large to audit');
  }
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

function zipEnd(data) {
  if (data.length < 22) throw new ZipError('malformed ZIP archive');
  const earliest = Math.max(0, data.length - 22 - 65535);
  for (let offset = data.length - 22; offset >= earliest; offset -= 1) {
    if (data.readUInt32LE(offset) !== 0x06054b50) continue;
    if (offset + 22 + data.readUInt16LE(offset + 20) !== data.length) continue;
    return offset;
  }
  throw new ZipError('malformed ZIP archive');
}

// Windows drops trailing dots and spaces from every path segment and aliases
// reserved device names, so `config.json.` extracts as `config.json` there.
// Normalize before the private-config and archive-extension checks, and reject
// such ZIP entry names outright rather than trusting a single spelling.
function normalizedPath(path) {
  return path.split('/').map((part) => part.replace(/[. ]+$/g, '')).join('/');
}

function zipEntryPath(name) {
  if (!name || name.includes('\0') || name.includes('\\')) throw new ZipError('unsafe ZIP entry path');
  if (name.startsWith('/') || /^[a-z]:/i.test(name)) throw new ZipError('unsafe ZIP entry path');
  const parts = name.split('/');
  if (parts.some((part) => part === '..')) throw new ZipError('unsafe ZIP entry path');
  for (const part of parts) {
    if (normalizedPath(part) !== part) throw new ZipError(`unsafe ZIP entry path (Windows alias): ${name}`);
    if (/^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part)) throw new ZipError(`unsafe ZIP device name: ${name}`);
  }
  return name;
}

function inspectZip(path, data, secrets) {
  try {
    const end = zipEnd(data);
    const count = data.readUInt16LE(end + 10);
    const directorySize = data.readUInt32LE(end + 12);
    const directoryOffset = data.readUInt32LE(end + 16);
    if (data.readUInt16LE(end + 4) !== 0 || data.readUInt16LE(end + 6) !== 0 || data.readUInt16LE(end + 8) !== count) {
      throw new ZipError('unsupported multi-disk ZIP archive');
    }
    if (count === 0xffff || directorySize === 0xffffffff || directoryOffset === 0xffffffff) {
      throw new ZipError('unsupported ZIP64 archive');
    }
    if (count > MAX_ZIP_ENTRIES) throw new ZipError(`too many ZIP entries (limit ${MAX_ZIP_ENTRIES})`);
    // The EOCD count is attacker-controlled: walk the real central directory
    // instead, so surplus records cannot hide behind a truncated count.
    const directoryEnd = directoryOffset + directorySize;
    if (directoryEnd !== end) throw new ZipError('malformed ZIP central directory');
    let cursor = directoryOffset;
    let totalSize = 0;
    let records = 0;
    while (cursor < directoryEnd) {
      if (cursor + 46 > directoryEnd || data.readUInt32LE(cursor) !== 0x02014b50) throw new ZipError('malformed ZIP central directory');
      const flags = data.readUInt16LE(cursor + 8);
      const method = data.readUInt16LE(cursor + 10);
      const checksum = data.readUInt32LE(cursor + 16);
      const compressedSize = data.readUInt32LE(cursor + 20);
      const size = data.readUInt32LE(cursor + 24);
      const nameLength = data.readUInt16LE(cursor + 28);
      const extraLength = data.readUInt16LE(cursor + 30);
      const commentLength = data.readUInt16LE(cursor + 32);
      const localOffset = data.readUInt32LE(cursor + 42);
      if (cursor + 46 + nameLength + extraLength + commentLength > directoryEnd) throw new ZipError('malformed ZIP central directory');
      const centralName = data.subarray(cursor + 46, cursor + 46 + nameLength);
      const name = zipEntryPath(text(centralName));
      cursor += 46 + nameLength + extraLength + commentLength;
      records += 1;
      if (records > MAX_ZIP_ENTRIES) throw new ZipError(`too many ZIP entries (limit ${MAX_ZIP_ENTRIES})`);
      if (flags & 0x2041) throw new ZipError(`encrypted ZIP entry: ${name}`);
      if (method !== 0 && method !== 8) throw new ZipError(`unsupported ZIP compression method: ${name}`);
      if ([compressedSize, size, localOffset].includes(0xffffffff)) throw new ZipError('unsupported ZIP64 archive');
      totalSize += size;
      if (size > MAX_ZIP_ENTRY_BYTES || totalSize > MAX_ZIP_TOTAL_BYTES) throw new ZipError('ZIP expansion limit exceeded');
      if (ARCHIVE.test(normalizedPath(name))) {
        findings.add(`${path}!/${name}: nested archive`);
        continue;
      }
      if (name.endsWith('/')) continue;
      if (localOffset + 30 > data.length || data.readUInt32LE(localOffset) !== 0x04034b50) throw new ZipError(`malformed ZIP local header: ${name}`);
      if (data.readUInt16LE(localOffset + 8) !== method) throw new ZipError(`malformed ZIP local header: ${name}`);
      const localNameLength = data.readUInt16LE(localOffset + 26);
      const start = localOffset + 30 + localNameLength + data.readUInt16LE(localOffset + 28);
      if (start + compressedSize > data.length) throw new ZipError(`truncated ZIP entry: ${name}`);
      // Extractors may follow the local header name, so both spellings must agree.
      if (!data.subarray(localOffset + 30, localOffset + 30 + localNameLength).equals(centralName)) {
        throw new ZipError(`ZIP local header name mismatch: ${name}`);
      }
      const compressed = data.subarray(start, start + compressedSize);
      let content;
      try {
        content = method === 0 ? compressed : inflateRawSync(compressed, { maxOutputLength: MAX_ZIP_ENTRY_BYTES + 1 });
      } catch {
        throw new ZipError(`malformed ZIP entry data: ${name}`);
      }
      if (content.length !== size || (method === 0 && compressedSize !== size)) throw new ZipError(`malformed ZIP entry size: ${name}`);
      if (crc32(content) !== checksum) throw new ZipError(`ZIP entry checksum mismatch: ${name}`);
      inspect(`${path}!/${name}`, content, secrets);
    }
    if (cursor !== directoryEnd) throw new ZipError('malformed ZIP central directory');
    if (records !== count) throw new ZipError(`ZIP entry count mismatch (declared ${count}, found ${records})`);
  } catch (error) {
    findings.add(`${path}: ${error instanceof ZipError ? error.message : 'malformed ZIP archive'}`);
  }
}

function inspect(path, data, secrets) {
  if (findings.size >= 30) return;
  if (RELEASE_ZIPS.has(path)) {
    if (data.length > MAX_ZIP_TOTAL_BYTES) findings.add(`${path}: ZIP exceeds the 64 MB archive limit`);
    else inspectZip(path, data, secrets);
    return;
  }
  const isArchiveEntry = path.includes('!/');
  const limit = isArchiveEntry ? MAX_ZIP_ENTRY_BYTES : LIMIT;
  if (data.length > limit) {
    findings.add(`${path}: file exceeds the ${limit / (1024 * 1024)} MB scan limit`);
    return;
  }
  const lower = normalizedPath(path).toLowerCase();
  if (/(?:^|\/)(?:config(?:\.local)?\.json|\.env(?:\..+)?)$/.test(lower) && !lower.endsWith('/.env.example') && lower !== '.env.example') {
    findings.add(`${path}: private local configuration`);
  }
  if (ARCHIVE.test(lower)) findings.add(`${path}: generated archive; use a Release asset`);
  if (/(?:^|\/)(?:node_modules|__pycache__|\.idea|\.vscode|\.omc|\.remember)\//.test(lower)) findings.add(`${path}: local dependency or tool state`);
  // NUL bytes mark binary content, but they must not disable the credential
  // scans: a binary blob can carry the same token. Scan a NUL-stripped view.
  const source = text(data).replace(/\0/g, '');
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
  const commits = text(git(['rev-list', ...(Array.isArray(range) ? range : [range])])).trim().split('\n').filter(Boolean);
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

function addObjects(blobs, range) {
  for (const [id, paths] of objectsForRange(range)) {
    if (!blobs.has(id)) blobs.set(id, new Set());
    for (const path of paths) blobs.get(id).add(path);
  }
}

function stdinObjects() {
  const blobs = new Map();
  const newRemoteIds = [];
  for (const line of text(readFileSync(0)).split('\n').filter(Boolean)) {
    const [, localId, , remoteId] = line.trim().split(/\s+/);
    if (!localId || localId === ZERO) continue;
    if (remoteId && remoteId !== ZERO) addObjects(blobs, `${remoteId}..${localId}`);
    else newRemoteIds.push(localId);
  }
  // A new remote ref has no exclusion base. Its genuinely outgoing commits are
  // the ones absent from every other remote-tracking ref, including remote/HEAD.
  const exclusions = text(git(['for-each-ref', '--format=%(objectname)', 'refs/remotes']))
    .trim().split('\n').filter(Boolean);
  for (const localId of newRemoteIds) addObjects(blobs, [localId, '--not', ...exclusions]);
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
