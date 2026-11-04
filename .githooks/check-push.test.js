import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const checker = fileURLToPath(new URL('./check-push.js', import.meta.url));
const fakeSecret = `fixture-${'x'.repeat(32)}-not-a-real-credential`;

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
