import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import test from 'node:test';
import {
  buildContentRequest,
  buildQueryRequest,
  buildSubmitRequest,
  extractUsage,
  extractUsageOnComplete,
  listArtifacts,
  meta,
  parseSubmitResponse,
  parseTaskResult,
  protocols,
} from '../plugin.js';

const COS_HOST = 'aigc-output-video-1326893053.cos.ap-guangzhou.myqcloud.com';
const COS_URL = `https://${COS_HOST}/outputs/example.mp4?sign=fixture`;
const driverContext = (requestBody) => ({
  requestBody,
  action: 'text_to_video',
  model: 'minimax-video-h3',
  upstreamModel: 'minimax-video-h3',
  baseUrl: 'http://127.0.0.1:7863',
  apiKey: 'test-key',
});

test('manifest declares Panel identity, models, protocol, and COS hosts', () => {
  assert.equal(meta.apiVersion, 1);
  assert.equal(meta.key, 'workbuddy-panel-video');
  assert.equal(meta.name, 'WorkBuddy Panel Video');
  assert.equal(meta.version, '1.1.1');
  assert.equal(meta.baseUrl, 'http://127.0.0.1:7863');
  assert.deepEqual(meta.allowedHosts, [COS_HOST]);
  assert.deepEqual(meta.models, ['minimax-video-h3', 'kling-video-v3']);
  assert.equal(meta.fetchMode, 'per_task');
  assert.deepEqual(meta.protocols, ['openai_video']);
});

test('decodes JSON and submits to Panel with a cn-prefixed model and wait=false', () => {
  const decoded = protocols.openai_video.decodeRequest({
    body: { kind: 'json', value: { prompt: 'A bird', seconds: '5', duration: 10 } },
    model: 'minimax-video-h3',
  });
  assert.equal(decoded.requestBody.seconds, 5);
  assert.equal(decoded.requestBody.duration, undefined);
  const request = buildSubmitRequest(driverContext(decoded.requestBody));
  assert.equal(request.url, 'http://127.0.0.1:7863/v1/videos/generations');
  assert.equal(request.method, 'POST');
  assert.equal(request.headers.Authorization, 'Bearer test-key');
  assert.deepEqual(request.body, {
    model: 'cn:minimax-video-h3', prompt: 'A bird', seconds: 5, wait: false,
  });
});

test('forwards the actual MiniMax request to Panel and preserves the task response', async (t) => {
  let upstream;
  const server = createServer((req, res) => {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      upstream = { url: req.url, authorization: req.headers.authorization, body: JSON.parse(body) };
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ id: 'panel-fixture-id', status: 'queued' }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const decoded = protocols.openai_video.decodeRequest({
    body: { kind: 'json', value: { prompt: 'A bird' } }, model: meta.models[0],
  });
  const request = buildSubmitRequest({
    ...driverContext(decoded.requestBody), baseUrl: `http://127.0.0.1:${server.address().port}`,
  });
  const response = await fetch(request.url, {
    method: request.method, headers: request.headers, body: JSON.stringify(request.body),
  });
  assert.equal(response.status, 200);
  assert.equal(upstream.url, '/v1/videos/generations');
  assert.equal(upstream.authorization, 'Bearer test-key');
  assert.deepEqual(upstream.body, { model: 'cn:minimax-video-h3', prompt: 'A bird', wait: false });
  const body = await response.json();
  assert.equal(parseSubmitResponse({}, { body }).taskId, 'panel-fixture-id');
});

test('preserves an existing cn prefix and applies it to Kling as declared', () => {
  const existing = buildSubmitRequest({ ...driverContext({ prompt: 'A bird' }), upstreamModel: 'cn:kling-video-v3' });
  assert.equal(existing.body.model, 'cn:kling-video-v3');
  const bare = buildSubmitRequest({ ...driverContext({ prompt: 'A bird' }), upstreamModel: 'kling-video-v3' });
  assert.equal(bare.body.model, 'cn:kling-video-v3');
});

test('uses the redirected upstream model exactly once and falls back without a redirect', () => {
  const context = driverContext({ prompt: 'A bird', model: 'minimax-video-h3', seconds: 5 });
  const redirected = buildSubmitRequest({ ...context, upstreamModel: 'kling-video-v3' });
  assert.equal(redirected.body.model, 'cn:kling-video-v3');
  assert.equal(extractUsage({ ...context, requestBody: redirected.body }).seconds, 5);
  assert.equal(buildSubmitRequest({ ...context, upstreamModel: 'cn:kling-video-v3' }).body.model, 'cn:kling-video-v3');
  assert.equal(buildSubmitRequest({ ...context, upstreamModel: '' }).body.model, 'cn:minimax-video-h3');
});

test('converts multipart input and rejects malformed input', () => {
  const decoded = protocols.openai_video.decodeRequest({
    body: {
      kind: 'multipart', fields: { prompt: ['Move'], seconds: ['5'] },
      files: [{ field: 'input_reference', ref: 'file-1', filename: 'a.png', size: 100 }],
    }, model: 'kling-video-v3',
  });
  assert.equal(decoded.action, 'image_to_video');
  assert.deepEqual(decoded.requestBody.input_reference, {
    __fileRef: 'file-1', encoding: 'dataUrl', maxBytes: 8388608,
  });
  assert.throws(() => protocols.openai_video.decodeRequest({
    body: { kind: 'json', value: { seconds: 5 } }, model: meta.models[0],
  }), /prompt is required/);
  assert.throws(() => protocols.openai_video.decodeRequest({
    body: { kind: 'json', value: { prompt: 'x', seconds: 0 } }, model: meta.models[0],
  }), /seconds must be a positive number/);
});

test('parses the task id and queries the Panel task endpoint', () => {
  const body = { id: 'panel-fixture-id', status: 'queued' };
  assert.deepEqual(parseSubmitResponse({}, { body }), { taskId: 'panel-fixture-id', taskData: body });
  assert.throws(() => parseSubmitResponse({}, { body: {} }), /task id is empty/);
  assert.deepEqual(buildQueryRequest({ baseUrl: meta.baseUrl, apiKey: 'test-key', taskId: 'panel/a' }), {
    url: 'http://127.0.0.1:7863/v1/videos/panel%2Fa', method: 'GET',
    headers: { Authorization: 'Bearer test-key' },
  });
});

test('rejects malformed channel base URLs and missing models before submission', () => {
  for (const baseUrl of ['not-a-url', 'file:///tmp/panel', 'https://user:pass@panel.invalid', 'http://panel.invalid?x=1']) {
    assert.throws(() => buildSubmitRequest({ ...driverContext({ prompt: 'A bird' }), baseUrl }), /base url/);
    assert.throws(() => buildQueryRequest({ baseUrl, apiKey: 'test-key', taskId: 'task' }), /base url/);
  }
  assert.throws(() => buildSubmitRequest({ ...driverContext({ prompt: 'A bird' }), model: '', upstreamModel: '' }), /model is required/);
});

test('maps task statuses and extracts nested COS result URLs', () => {
  assert.deepEqual(parseTaskResult({}, { status: 'queued' }), { status: 'QUEUED' });
  assert.deepEqual(parseTaskResult({}, { status: 'processing', progress: 42 }), {
    status: 'IN_PROGRESS', progress: '42%',
  });
  assert.deepEqual(parseTaskResult({}, { status: 'completed', url: COS_URL }), {
    status: 'SUCCESS', url: COS_URL,
  });
  assert.deepEqual(parseTaskResult({}, { status: 'succeeded', data: [{ url: COS_URL }] }), {
    status: 'SUCCESS', url: COS_URL,
  });
  assert.deepEqual(parseTaskResult({}, { status: 'completed', videos: [{ url: COS_URL }] }), {
    status: 'SUCCESS', url: COS_URL,
  });
  assert.deepEqual(parseTaskResult({}, { status: 'failed', error: { message: 'denied' } }), {
    status: 'FAILURE', reason: 'denied',
  });
  assert.equal(parseTaskResult({}, { status: 'mystery' }).status, 'UNKNOWN');
});

test('redacts credentials and signed URLs from bounded failure reasons', () => {
  const result = parseTaskResult({}, {
    status: 'failed',
    error: { message: 'request https://example.com/video?token=fixture-secret failed\nAuthorization: Bearer fixture-secret ' + 'x'.repeat(400) },
  });
  assert.equal(result.status, 'FAILURE');
  assert.ok(result.reason.length <= 300);
  assert.ok(!result.reason.includes('fixture-secret'));
  assert.ok(result.reason.includes('[URL]'));
  assert.ok(result.reason.includes('[REDACTED]'));
});

test('extracts COS URLs from top-level, videos, and data result shapes', () => {
  for (const data of [
    { url: COS_URL }, { videos: [{ url: COS_URL }] }, { data: [{ url: COS_URL }] },
  ]) {
    const request = buildContentRequest({
      artifactKey: 'video', apiKey: 'test-key', data, clientRequest: { method: 'GET', headers: {} },
    });
    assert.equal(request.url, COS_URL);
    assert.deepEqual(request.headers, {});
    assert.equal(request.credentialless, undefined);
  }
  assert.equal(buildContentRequest({ artifactKey: 'video', data: {}, url: COS_URL }).url, COS_URL);
});

test('rejects untrusted, non-HTTPS, credentialed, and malformed result URLs', () => {
  for (const url of [
    `http://${COS_HOST}/video.mp4`,
    'https://127.0.0.1/video.mp4',
    `https://${COS_HOST}:8443/video.mp4`,
    `https://${COS_HOST}.attacker.invalid/video.mp4`,
    `https://user:pass@${COS_HOST}/video.mp4`,
    '/relative/video.mp4',
  ]) {
    assert.throws(() => buildContentRequest({ artifactKey: 'video', data: { url } }), /not allowed|absolute HTTPS/, url);
  }
  assert.deepEqual(buildContentRequest({ artifactKey: 'video', data: { url: `https://${COS_HOST}:443/video.mp4` } }).headers, {});
  assert.throws(() => buildContentRequest({ artifactKey: 'video', data: {} }), /url is empty/);
});

test('forwards Range to COS but never forwards the Panel credential', () => {
  const request = buildContentRequest({
    artifactKey: 'video', apiKey: 'test-key', data: { url: COS_URL },
    clientRequest: { method: 'GET', headers: { Range: 'bytes=0-99', Authorization: 'Bearer client-key' } },
  });
  assert.deepEqual(request, { url: COS_URL, method: 'GET', headers: { Range: 'bytes=0-99' } });
  assert.throws(() => buildContentRequest({ artifactKey: 'other', data: { url: COS_URL } }), /artifact_not_found/);
});

test('projects successful videos and usage without setting prices', () => {
  assert.deepEqual(listArtifacts({ status: 'IN_PROGRESS' }), []);
  assert.deepEqual(listArtifacts({ status: 'SUCCESS' }), [{ key: 'video', type: 'video', mimeType: 'video/mp4' }]);
  assert.deepEqual(extractUsage(driverContext({ seconds: '5', resolution: '768P' })), {
    seconds: 5, resolution: '768P',
  });
  assert.deepEqual(extractUsageOnComplete({}, {}, { seconds: '5', resolution: '2K', credit: 1 }), {
    seconds: 5, resolution: '2K', credit: 1,
  });
});

test('renders a public task id without exposing a signed COS URL', () => {
  const rendered = protocols.openai_video.render({}, {
    task_id: 'public-id', data: { id: 'private-id', url: COS_URL, status: 'completed' },
  });
  assert.equal(rendered.id, 'public-id');
  assert.equal(rendered.status, 'completed');
  assert.equal(rendered.url, undefined);
});
