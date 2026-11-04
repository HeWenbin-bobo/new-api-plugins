import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { deflateRawSync } from 'node:zlib';
import test from 'node:test';

const checker = fileURLToPath(new URL('./check-push.js', import.meta.url));
const fakeSecret = `fixture-${'x'.repeat(32)}-not-a-real-credential`;
const releaseZips = [
  'kling_wb2api_newapi/kling_wb2api_newapi.zip',
  'jihuarst-image/jihuarst-image.zip',
  'jihuarst-video/jihuarst-video.zip',
  'zaiwen-image-generation/zaiwen-image-generation.zip',
  'unified-web-mcp/unified-web-mcp-package/unified-web-mcp-0.1.0.zip',
];

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

function makeZip(entries) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const { name, data, method = 0, flags = 0, declaredSize } of entries) {
    const raw = Buffer.isBuffer(data) ? data : Buffer.from(data ?? '');
    const nameBuffer = Buffer.from(name);
    const compressed = method === 8 ? deflateRawSync(raw) : raw;
    const crc = crc32(raw);
    const size = declaredSize ?? raw.length;
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(flags, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(size, 22);
    local.writeUInt16LE(nameBuffer.length, 26);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(flags, 8);
    central.writeUInt16LE(method, 10);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(compressed.length, 20);
    central.writeUInt32LE(size, 24);
    central.writeUInt16LE(nameBuffer.length, 28);
    central.writeUInt32LE(offset, 42);
    locals.push(local, nameBuffer, compressed);
    centrals.push(central, nameBuffer);
    offset += local.length + nameBuffer.length + compressed.length;
  }
  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

function writeZip(cwd, path, buffer) {
  const target = join(cwd, path);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, buffer);
}

function git(cwd, args) {
  const result = spawnSync('git', args, { cwd, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
}

function fixture(t) {
  const cwd = mkdtempSync(join(tmpdir(), 'push-check-'));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  git(cwd, ['init', '-q']);
  git(cwd, ['config', 'user.name', 'Offline Test']);
  git(cwd, ['config', 'user.email', 'offline@example.invalid']);
  mkdirSync(join(cwd, 'nested'));
  writeFileSync(join(cwd, 'README.md'), 'safe\n');
  git(cwd, ['add', 'README.md']);
  git(cwd, ['commit', '-qm', 'initial']);
  return cwd;
}

function check(cwd, range, ...extraArgs) {
  const mode = range === null ? ['--all'] : ['--range', range];
  const result = spawnSync(process.execPath, [checker, ...mode, ...extraArgs], {
    cwd,
    input: '',
    encoding: 'utf8',
    timeout: 10000,
  });
  assert.ok(!result.stderr.includes(fakeSecret), 'diagnostics leaked the fixture secret');
  assert.ok(!result.stdout.includes(fakeSecret), 'diagnostics leaked the fixture secret');
  return result;
}

test('accepts a safe commit and scans an unborn branch', (t) => {
  const cwd = mkdtempSync(join(tmpdir(), 'push-check-unborn-'));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  git(cwd, ['init', '-q']);
  assert.equal(check(cwd, null, '--all').status, 0);
  writeFileSync(join(cwd, 'safe.txt'), 'safe\n');
  git(cwd, ['add', 'safe.txt']);
  assert.equal(check(cwd, null, '--all').status, 0);
});

test('rejects private config even when force-added, without printing its contents', (t) => {
  const cwd = fixture(t);
  writeFileSync(join(cwd, 'nested', 'config.local.json'), `{"api_key":"${fakeSecret}"}`);
  git(cwd, ['add', '-f', 'nested/config.local.json']);
  const result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /private local configuration/);
});

test('rejects a credential in an earlier outgoing commit even if later deleted', (t) => {
  const cwd = fixture(t);
  const config = join(cwd, 'local-private.json');
  writeFileSync(config, `{"api_key":"${fakeSecret}"}`);
  writeFileSync(join(cwd, 'nested', 'data.txt'), fakeSecret);
  const base = git(cwd, ['rev-parse', 'HEAD']);
  git(cwd, ['add', 'nested/data.txt']);
  git(cwd, ['commit', '-qm', 'unsafe']);
  git(cwd, ['rm', '-q', 'nested/data.txt']);
  git(cwd, ['commit', '-qm', 'delete']);
  const result = check(cwd, `${base}..HEAD`, '--local-config', config);
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /local credential value/);
});

test('accepts public examples with empty credentials', (t) => {
  const cwd = fixture(t);
  writeFileSync(join(cwd, 'config.example.json'), '{"api_key":"","base_url":"https://example.invalid"}');
  git(cwd, ['add', 'config.example.json']);
  const result = check(cwd, null, '--all');
  assert.equal(result.status, 0, result.stderr);
});

test('rejects non-empty credentials in public examples', (t) => {
  const cwd = fixture(t);
  writeFileSync(join(cwd, 'config.example.json'), `{"api_key":"${fakeSecret}"}`);
  git(cwd, ['add', 'config.example.json']);
  const result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /non-empty credential in example/);
});

test('detects common provider tokens but not prose about them', (t) => {
  const cwd = fixture(t);
  writeFileSync(join(cwd, 'nested', 'notes.txt'), 'Never commit an OpenAI API key or GitHub token.\n');
  git(cwd, ['add', 'nested/notes.txt']);
  assert.equal(check(cwd, null, '--all').status, 0);
  writeFileSync(join(cwd, 'nested', 'notes.txt'), `sk-${'a'.repeat(32)}\n`);
  git(cwd, ['add', 'nested/notes.txt']);
  const result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /OpenAI-style key/);
});

test('rejects generated archives and editor state', (t) => {
  const cwd = fixture(t);
  writeFileSync(join(cwd, 'bundle.zip'), 'offline archive fixture');
  git(cwd, ['add', 'bundle.zip']);
  const result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /generated archive/);
});

test('checks private and archive paths before skipping binary content', (t) => {
  const cwd = fixture(t);
  writeFileSync(join(cwd, 'nested', 'config.json'), Buffer.from([0, 1, 2]));
  writeFileSync(join(cwd, 'bundle.zip'), Buffer.from([0, 1, 2]));
  git(cwd, ['add', '-f', 'nested/config.json', 'bundle.zip']);
  const result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /private local configuration/);
  assert.match(result.stderr, /generated archive/);
});

test('matches exact local credential values without exposing them', (t) => {
  const cwd = fixture(t);
  const config = join(cwd, 'local-private.json');
  writeFileSync(config, `{"api_key":"${fakeSecret}"}`);
  writeFileSync(join(cwd, 'nested', 'notes.txt'), `prefix ${fakeSecret} suffix\n`);
  git(cwd, ['add', 'nested/notes.txt']);
  const result = check(cwd, null, '--all', '--local-config', config);
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /local credential value/);
});

test('checks every path when identical blobs have safe and private names', (t) => {
  const cwd = fixture(t);
  writeFileSync(join(cwd, 'nested', 'config.local.json'), 'same\n');
  writeFileSync(join(cwd, 'safe.txt'), 'same\n');
  git(cwd, ['add', 'nested/config.local.json', 'safe.txt']);
  const result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /private local configuration/);
});

test('accepts dummy assignments without weakening exact local credential matching', (t) => {
  const cwd = fixture(t);
  writeFileSync(join(cwd, 'nested', 'notes.txt'), `const secret = "router-test-secret";\nconst DUMMY_KEY = "dummy-not-a-real-key";\n`);
  git(cwd, ['add', 'nested/notes.txt']);
  assert.equal(check(cwd, null).status, 0);
  const config = join(cwd, 'local-private.json');
  writeFileSync(config, `{"api_key":"${fakeSecret}"}`);
  writeFileSync(join(cwd, 'nested', 'notes.txt'), `const DUMMY_KEY = "${fakeSecret}";\n`);
  git(cwd, ['add', 'nested/notes.txt']);
  const result = check(cwd, null, '--local-config', config);
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /local credential value/);
});

test('accepts the five audited release ZIPs with stored and deflated entries', (t) => {
  const cwd = fixture(t);
  for (const path of releaseZips) {
    writeZip(cwd, path, makeZip([
      { name: 'README.md', data: 'safe\n' },
      { name: 'config.example.json', data: '{"api_key":"","base_url":"https://example.invalid"}', method: 8 },
      { name: 'src/index.js', data: 'export const ok = true;\n', method: 8 },
      { name: 'assets/', data: '' },
    ]));
    git(cwd, ['add', '-f', path]);
  }
  const result = check(cwd, null, '--all');
  assert.equal(result.status, 0, result.stderr);
});

test('rejects archives outside the exact release allowlist', (t) => {
  const cwd = fixture(t);
  for (const path of ['jihuarst-image/other.zip', 'unified-web-mcp/unified-web-mcp-package/unified-web-mcp-0.2.0.zip', 'bundle.7z']) {
    writeZip(cwd, path, makeZip([{ name: 'README.md', data: 'safe\n' }]));
    git(cwd, ['add', '-f', path]);
  }
  const result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /generated archive/);
});

test('rejects exact local credentials inside a release ZIP without printing them', (t) => {
  const cwd = fixture(t);
  const config = join(cwd, 'local-private.json');
  writeFileSync(config, `{"api_key":"${fakeSecret}"}`);
  writeZip(cwd, releaseZips[1], makeZip([{ name: 'notes.txt', data: `prefix ${fakeSecret} suffix\n`, method: 8 }]));
  git(cwd, ['add', '-f', releaseZips[1]]);
  const result = check(cwd, null, '--all', '--local-config', config);
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /local credential value/);
});

test('rejects provider tokens inside deflated release ZIP entries', (t) => {
  const cwd = fixture(t);
  writeZip(cwd, releaseZips[2], makeZip([{ name: 'src/config.js', data: `const key = "sk-${'a'.repeat(32)}";\n`, method: 8 }]));
  git(cwd, ['add', '-f', releaseZips[2]]);
  const result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /OpenAI-style key/);
});

test('rejects private configuration and tool state inside a release ZIP', (t) => {
  const cwd = fixture(t);
  writeZip(cwd, releaseZips[0], makeZip([
    { name: 'config.json', data: '{}' },
    { name: 'nested/.env.local', data: 'A=b\n', method: 8 },
    { name: 'node_modules/pkg/index.js', data: 'safe\n' },
  ]));
  git(cwd, ['add', '-f', releaseZips[0]]);
  const result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /private local configuration/);
  assert.match(result.stderr, /local dependency or tool state/);
});

test('rejects nested archives inside a release ZIP', (t) => {
  const cwd = fixture(t);
  writeZip(cwd, releaseZips[3], makeZip([{ name: 'nested/inner.zip', data: makeZip([{ name: 'a.txt', data: 'a' }]) }]));
  git(cwd, ['add', '-f', releaseZips[3]]);
  const result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /nested archive/);
});

test('fails closed on path traversal entries in a release ZIP', (t) => {
  const cwd = fixture(t);
  for (const name of ['../escape.txt', '/absolute.txt', 'C:\\escape.txt', 'safe/../../escape.txt']) {
    writeZip(cwd, releaseZips[4], makeZip([{ name, data: 'safe\n' }]));
    git(cwd, ['add', '-f', releaseZips[4]]);
    const result = check(cwd, null, '--all');
    assert.notEqual(result.status, 0, name);
    assert.match(result.stderr, /unsafe ZIP entry path/);
  }
});

test('fails closed on malformed, encrypted, unsupported, and corrupt release ZIPs', async (t) => {
  const cwd = fixture(t);
  const valid = makeZip([{ name: 'README.md', data: 'safe\n' }]);
  const corruptCrc = Buffer.from(valid);
  corruptCrc[30 + 'README.md'.length] ^= 0xff;
  const cases = [
    ['truncated', valid.subarray(0, 20), /malformed ZIP/],
    ['encrypted', makeZip([{ name: 'README.md', data: 'safe\n', flags: 1 }]), /encrypted ZIP/],
    ['unsupported method', makeZip([{ name: 'README.md', data: 'safe\n', method: 99 }]), /unsupported ZIP compression/],
    ['crc mismatch', corruptCrc, /ZIP entry checksum mismatch/],
  ];
  for (const [name, buffer, pattern] of cases) {
    await t.test(name, () => {
      writeZip(cwd, releaseZips[0], buffer);
      git(cwd, ['add', '-f', releaseZips[0]]);
      const result = check(cwd, null, '--all');
      assert.notEqual(result.status, 0, result.stderr);
      assert.match(result.stderr, pattern);
    });
  }
});

test('enforces release ZIP entry count and expansion limits', (t) => {
  const cwd = fixture(t);
  const tooMany = Array.from({ length: 2100 }, (_, index) => ({ name: `f${index}.txt`, data: '' }));
  writeZip(cwd, releaseZips[1], makeZip(tooMany));
  git(cwd, ['add', '-f', releaseZips[1]]);
  let result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /too many ZIP entries/);
  writeZip(cwd, releaseZips[1], makeZip([{ name: 'bomb.txt', data: 'tiny', declaredSize: 0x7fffffff }]));
  git(cwd, ['add', '-f', releaseZips[1]]);
  result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /ZIP expansion limit/);
});

test('audits release ZIPs in earlier outgoing commits even if later deleted', (t) => {
  const cwd = fixture(t);
  const config = join(cwd, 'local-private.json');
  writeFileSync(config, `{"api_key":"${fakeSecret}"}`);
  writeZip(cwd, releaseZips[2], makeZip([{ name: 'notes.txt', data: fakeSecret, method: 8 }]));
  const base = git(cwd, ['rev-parse', 'HEAD']);
  git(cwd, ['add', '-f', releaseZips[2]]);
  git(cwd, ['commit', '-qm', 'unsafe archive']);
  git(cwd, ['rm', '-q', releaseZips[2]]);
  git(cwd, ['commit', '-qm', 'delete archive']);
  const result = check(cwd, `${base}..HEAD`, '--local-config', config);
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /local credential value/);
});

test('audits staged release ZIPs on an unborn branch', (t) => {
  const cwd = mkdtempSync(join(tmpdir(), 'push-check-unborn-zip-'));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  git(cwd, ['init', '-q']);
  writeZip(cwd, releaseZips[3], makeZip([{ name: 'README.md', data: 'safe\n', method: 8 }]));
  git(cwd, ['add', '-f', releaseZips[3]]);
  assert.equal(check(cwd, null, '--all').status, 0);
  writeZip(cwd, releaseZips[3], makeZip([{ name: 'config.local.json', data: '{}' }]));
  git(cwd, ['add', '-f', releaseZips[3]]);
  const result = check(cwd, null, '--all');
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /private local configuration/);
});

test('the real pre-push wrapper blocks a dangerous outgoing commit', (t) => {
  const root = fileURLToPath(new URL('..', import.meta.url));
  const cwd = fixture(t);
  const remote = join(cwd, 'remote.git');
  const source = join(cwd, 'source');
  git(cwd, ['init', '-q', '--bare', remote]);
  git(cwd, ['clone', '-q', remote, source]);
  git(source, ['config', 'user.name', 'Offline Test']);
  git(source, ['config', 'user.email', 'offline@example.invalid']);
  git(source, ['config', 'core.hooksPath', '.githooks']);
  const hooks = join(source, '.githooks');
  mkdirSync(hooks, { recursive: true });
  for (const name of ['pre-push', 'check-push.js']) {
    const file = join(hooks, name);
    const content = readFileSync(join(root, '.githooks', name));
    writeFileSync(file, content, { mode: name === 'pre-push' ? 0o755 : 0o644 });
  }
  git(source, ['add', '.githooks']);
  writeFileSync(join(source, 'safe.txt'), 'safe\n');
  git(source, ['add', 'safe.txt']);
  git(source, ['commit', '-qm', 'initial']);
  let result = spawnSync('git', ['push', '--dry-run', 'origin', 'HEAD:main'], { cwd: source, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  writeFileSync(join(source, 'config.local.json'), `{"api_key":"${fakeSecret}"}`);
  git(source, ['add', '-f', 'config.local.json']);
  git(source, ['commit', '-qm', 'unsafe']);
  result = spawnSync('git', ['push', '--dry-run', 'origin', 'HEAD:main'], { cwd: source, encoding: 'utf8' });
  assert.notEqual(result.status, 0, result.stderr);
  assert.match(result.stderr, /private local configuration/);
  assert.ok(!result.stderr.includes(fakeSecret), 'wrapper diagnostics leaked the fixture secret');
});

test('the checked-in pre-push wrapper invokes the checker', () => {
  const wrapper = readFileSync(fileURLToPath(new URL('./pre-push', import.meta.url)), 'utf8');
  assert.match(wrapper, /check-push\.js/);
  assert.doesNotMatch(wrapper, /TODO|FIXME/);
});
