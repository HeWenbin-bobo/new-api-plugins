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

const driverContext = (requestBody) => ({
  requestBody,
  action: requestBody.image || requestBody.input_reference ? 'image_to_video' : 'text_to_video',
  model: 'kling-video-v3',
  upstreamModel: 'kling-video-v3',
  baseUrl: 'http://127.0.0.1:8788',
  apiKey: 'test-key',
  files: [],
});

test('manifest declares the OpenAI video protocol without a channel override', () => {
  assert.equal(meta.apiVersion, 1);
  assert.equal(meta.key, 'workbuddy-video');
  assert.equal(meta.name, 'WorkBuddy Video');
  assert.equal(meta.version, '1.1.0');
  assert.equal(meta.baseUrl, 'http://127.0.0.1:8788');
  assert.deepEqual(meta.models, ['minimax-video-h3', 'kling-video-v3']);
  assert.equal(meta.fetchMode, 'per_task');
  assert.deepEqual(meta.protocols, ['openai_video']);
  assert.equal(meta.channelTypes, undefined);
});

test('usage examples include numeric credit facts', () => {
  assert.ok(meta.usageExamples.length > 0);
  for (const example of meta.usageExamples) {
    assert.equal(typeof example.facts.credit, 'number');
  }
});

test('decodes JSON text-to-video and builds an authenticated submission', () => {
  const decoded = protocols.openai_video.decodeRequest({
    body: { kind: 'json', value: { prompt: 'A cat', seconds: '5', size: '1280x720' } },
    model: 'kling-video-v3',
  });
  assert.equal(decoded.kind, 'submit');
  assert.equal(decoded.action, 'text_to_video');
  assert.equal(decoded.requestBody.model, 'kling-video-v3');

  const request = buildSubmitRequest(driverContext(decoded.requestBody));
  assert.equal(request.url, 'http://127.0.0.1:8788/v1/videos');
  assert.equal(request.method, 'POST');
  assert.equal(request.headers.Authorization, 'Bearer test-key');
  assert.equal(request.headers['Content-Type'], 'application/json');
  assert.deepEqual(request.body, {
    model: 'kling-video-v3', prompt: 'A cat', seconds: 5, size: '1280x720',
  });
  assert.equal(request.action, 'text_to_video');
});

test('forwards minimax-video-h3 to the upstream gateway', async (t) => {
  let upstreamBody;
  const server = createServer((req, res) => {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      upstreamBody = JSON.parse(body);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ id: 'wb-minimax', status: 'queued' }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const decoded = protocols.openai_video.decodeRequest({
    body: { kind: 'json', value: { prompt: 'A cat' } },
    model: meta.models[0],
  });
  const request = buildSubmitRequest({
    ...driverContext(decoded.requestBody),
    model: decoded.model,
    upstreamModel: decoded.model,
    baseUrl: `http://127.0.0.1:${server.address().port}`,
  });
  const response = await fetch(request.url, {
    method: request.method,
    headers: request.headers,
    body: JSON.stringify(request.body),
  });
  assert.equal(response.status, 200);
  assert.equal(upstreamBody.model, 'minimax-video-h3');
});

test('accepts a JSON image URL as image-to-video', () => {
  const decoded = protocols.openai_video.decodeRequest({
    body: { kind: 'json', value: { prompt: 'Move', input_reference: 'https://example.com/a.png' } },
    model: 'kling-video-v3',
  });
  assert.equal(decoded.action, 'image_to_video');
  assert.equal(buildSubmitRequest(driverContext(decoded.requestBody)).body.input_reference, 'https://example.com/a.png');
});

test('converts a multipart input file to a bounded data URL placeholder', () => {
  const decoded = protocols.openai_video.decodeRequest({
    body: {
      kind: 'multipart',
      fields: { prompt: ['Move'], seconds: ['5'] },
      files: [{ field: 'input_reference', ref: 'file-1', filename: 'a.png', mimeType: 'image/png', size: 100 }],
    },
    model: 'kling-video-v3',
  });
  assert.equal(decoded.action, 'image_to_video');
  assert.deepEqual(decoded.requestBody.input_reference, {
    __fileRef: 'file-1', encoding: 'dataUrl', maxBytes: 8388608,
  });
  assert.equal(decoded.requestBody.seconds, 5);
  const request = buildSubmitRequest(driverContext(decoded.requestBody));
  assert.equal(request.bodyType, undefined);
  assert.deepEqual(request.body.input_reference, decoded.requestBody.input_reference);
});

test('rejects malformed input before submission', () => {
  assert.throws(() => protocols.openai_video.decodeRequest({ body: { kind: 'json', value: { seconds: 5 } }, model: meta.models[0] }), /prompt is required/);
  assert.throws(() => protocols.openai_video.decodeRequest({ body: { kind: 'json', value: { prompt: 'x', seconds: 0 } }, model: meta.models[0] }), /seconds must be a positive number/);
  assert.throws(() => protocols.openai_video.decodeRequest({
    body: { kind: 'multipart', fields: { prompt: ['x'] }, files: [{ field: 'other', ref: 'x' }] }, model: meta.models[0],
  }), /unexpected file field/);
});

test('extracts the upstream task id and rejects an empty response', () => {
  const body = { id: 'wb-123', status: 'queued' };
  assert.deepEqual(parseSubmitResponse({}, { body }), { taskId: 'wb-123', taskData: body });
  assert.throws(() => parseSubmitResponse({}, { body: {} }), /task id is empty/);
});

test('polls the upstream task with the channel credential', () => {
  assert.deepEqual(buildQueryRequest({ baseUrl: meta.baseUrl, apiKey: 'test-key', taskId: 'wb/a' }), {
    url: 'http://127.0.0.1:8788/v1/videos/wb%2Fa', method: 'GET', headers: { Authorization: 'Bearer test-key' },
  });
});

test('maps pending, success, failure, and unknown statuses', () => {
  assert.deepEqual(parseTaskResult({}, { status: 'queued', progress: 0 }), { status: 'QUEUED' });
  assert.deepEqual(parseTaskResult({}, { status: 'in_progress', progress: 42 }), { status: 'IN_PROGRESS', progress: '42%' });
  assert.deepEqual(parseTaskResult({}, { status: 'completed', url: '/v1/videos/wb-123/content?i=0&t=signed' }), {
    status: 'SUCCESS', url: '/v1/videos/wb-123/content?i=0&t=signed',
  });
  assert.deepEqual(parseTaskResult({}, { status: 'failed', error: { message: 'denied' } }), { status: 'FAILURE', reason: 'denied' });
  assert.deepEqual(parseTaskResult({}, { status: 'mystery' }), { status: 'UNKNOWN', reason: 'unrecognized status: mystery' });
});

test('exposes only successful videos and downloads via authenticated upstream content URL', () => {
  assert.deepEqual(listArtifacts({ status: 'IN_PROGRESS' }), []);
  assert.deepEqual(listArtifacts({ status: 'SUCCESS' }), [{ key: 'video', type: 'video', mimeType: 'video/mp4' }]);
  const request = buildContentRequest({
    artifactKey: 'video', baseUrl: meta.baseUrl, apiKey: 'test-key', upstreamTaskId: 'wb-123',
    data: { url: '/v1/videos/wb-123/content?i=0&t=expired-signed' },
    clientRequest: { method: 'GET', headers: {} },
  });
  // Rebuilds the content URL from the task id (survives expired signed URLs) and
  // uses the channel key so WorkBuddy's API-key fallback authorizes the download.
  assert.deepEqual(request, {
    url: 'http://127.0.0.1:8788/v1/videos/wb-123/content',
    method: 'GET', headers: { Authorization: 'Bearer test-key' },
  });
  assert.throws(() => buildContentRequest({ artifactKey: 'video', baseUrl: meta.baseUrl, apiKey: 'k', upstreamTaskId: '', data: {} }), /upstream task id is empty/);
});

test('forwards Range alongside the channel credential (no credentialless)', () => {
  const request = buildContentRequest({
    artifactKey: 'video', baseUrl: meta.baseUrl, apiKey: 'test-key', upstreamTaskId: 'wb-123',
    data: { url: '/v1/videos/wb-123/content?i=0&t=signed' },
    clientRequest: { method: 'GET', headers: { Range: 'bytes=0-99', Authorization: 'Bearer client-key' } },
  });
  assert.deepEqual(request, {
    url: 'http://127.0.0.1:8788/v1/videos/wb-123/content',
    method: 'GET', headers: { Range: 'bytes=0-99', Authorization: 'Bearer test-key' },
  });
  assert.equal(request.credentialless, undefined);
});

test('returns duration and resolution usage without setting prices', () => {
  assert.deepEqual(extractUsage(driverContext({ seconds: '5', resolution: '720P' })), { seconds: 5, resolution: '720P' });
  assert.deepEqual(extractUsageOnComplete({}, {}, { seconds: '4', resolution: '1080P', credit: 102.84 }), {
    seconds: 4, resolution: '1080P', credit: 102.84,
  });
  // 4K must survive schema validation; unknown resolutions must not poison seconds/credit.
  assert.deepEqual(extractUsageOnComplete({}, {}, { seconds: '5', resolution: '4K' }), { seconds: 5, resolution: '4K' });
  assert.deepEqual(extractUsageOnComplete({}, {}, { seconds: '5', resolution: '8K', credit: 1 }), { seconds: 5, credit: 1 });
});

test('renders an OpenAI video response while replacing its private id and url', () => {
  const rendered = protocols.openai_video.render({}, {
    task_id: 'public-id', status: 'SUCCESS', progress: '100%', created_at: 123,
    data: { id: 'wb-private', status: 'completed', url: '/signed', seconds: '5' },
  });
  assert.equal(rendered.id, 'public-id');
  assert.equal(rendered.status, 'completed');
  assert.equal(rendered.url, undefined);
  assert.equal(rendered.poll, undefined);
});
