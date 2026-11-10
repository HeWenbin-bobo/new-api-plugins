// local-ocr: private PDF/image OCR tasks for MinerU and PaddleOCR-VL.
// Synchronous ECMAScript only. The host performs all HTTP and persistence.
export const meta = {
  apiVersion: 1,
  key: "local-ocr",
  name: "Local Document OCR",
  version: "0.1.6",
  author: { name: "Local OCR Stack contributors" },
  description: {
    en: "Private asynchronous PDF and image parsing through a self-hosted OCR task service.",
    zh: "通过自托管 OCR 任务服务异步解析 PDF 和图片，输出 Markdown、JSON 和 ZIP。",
  },
  icon: "text:OCR",
  baseUrl: "http://local-ocr.local:18082",
  models: ["mineru-pipeline-cpu", "paddleocr-vl-1.6-cpu"],
  fetchMode: "per_task",
  routes: [
    { method: "POST", path: "/local-ocr/v1/parse", type: "submit", decode: "parseDocument", render: "taskCreated" },
    { method: "GET", path: "/local-ocr/v1/tasks/:task_id", type: "query", render: "taskStatus" },
  ],
  usageSchema: {
    pages: { type: "number", unit: "count", description: { en: "Parsed pages unit price", zh: "解析页数单价" } },
  },
};

function bodyFile(ctx) {
  const body = ctx && ctx.body;
  if (!body || body.kind !== "multipart") return null;
  const files = body.files || [];
  if (files.length !== 1) throw new Error("Exactly one document file is required");
  const file = files[0];
  if (!file.ref || Number(file.size) <= 0) throw new Error("Document file is empty");
  return file;
}

function normalize(ctx) {
  // Native decoders receive {body:{kind,fields,files}}. The generic
  // /v1/tasks/:key driver receives {requestBody:{...},files:[...]}.
  const input = ctx.body ? ctx : { body: { kind: (ctx.files || []).length ? "multipart" : "json", value: ctx.requestBody, fields: { model: [ctx.requestBody && ctx.requestBody.model] }, files: ctx.files || [] } };
  const file = bodyFile(input);
  if (file) {
    const fields = input.body.fields || {};
    const models = fields.model || [];
    if (models.length !== 1) throw new Error("The model form field is required");
    const genericDriver = !ctx.body;
    const normalized = { model: models[0], file: genericDriver ? { __fileRef: file.ref, encoding: "base64", maxBytes: 52428800 } : file, filename: file.filename, mime_type: file.mimeType };
    if (!genericDriver) normalized.multipart = true;
    return normalized;
  }
  if (!input.body || input.body.kind !== "json" || !input.body.value || typeof input.body.value !== "object" || Array.isArray(input.body.value)) {
    throw new Error("JSON or multipart body required");
  }
  const body = input.body.value;
  if (typeof body.file_base64 !== "string" || !body.file_base64) throw new Error("file_base64 or a multipart file is required");
  if (typeof body.filename !== "string" || !/\.(pdf|png|jpe?g|webp)$/i.test(body.filename)) throw new Error("filename must end in .pdf, .png, .jpg, .jpeg or .webp");
  return { model: body.model, file_base64: body.file_base64, filename: body.filename, mime_type: body.mime_type || "application/octet-stream" };
}

export function decodeRequest(ctx) {
  const request = normalize(ctx);
  return { kind: "submit", model: request.model, requestBody: request };
}

export function buildSubmitRequest(ctx) {
  const request = ctx.requestBody;
  // Generic /v1/tasks/:key is a JSON submit surface in rc.49. Always send
  // JSON upstream here, even when the client used multipart for file upload.
  if (request.multipart && ctx.body && ctx.body.kind === "multipart") {
    return {
      url: ctx.baseUrl + "/v1/tasks",
      method: "POST",
      headers: { Authorization: "Bearer " + ctx.apiKey, Accept: "application/json" },
      bodyType: "multipart",
      parts: [
        { name: "model", value: request.model },
        { name: "file", fileRef: request.file.ref, filename: request.filename },
      ],
    };
  }
  return {
    url: ctx.baseUrl + "/v1/tasks",
    method: "POST",
    headers: { Authorization: "Bearer " + ctx.apiKey, "Content-Type": "application/json", Accept: "application/json" },
    body: request,
  };
}

function auth(ctx) {
  return { Authorization: "Bearer " + ctx.apiKey, Accept: "application/json" };
}

export function parseSubmitResponse(ctx, response) {
  const body = response.body || {};
  if (!body.id) throw new Error("OCR task service did not return a task id");
  return { taskId: body.id, taskData: body, state: { artifacts: body.artifacts || [], pages: Number(body.pages || 1) } };
}

export function buildQueryRequest(ctx) {
  return { url: ctx.baseUrl + "/v1/tasks/" + encodeURIComponent(ctx.taskId), method: "GET", headers: auth(ctx) };
}

export function parseTaskResult(ctx, body) {
  body = body || {};
  const states = { queued: "QUEUED", running: "IN_PROGRESS", success: "SUCCESS", failed: "FAILURE" };
  if (!states[body.status]) return { status: "UNKNOWN", state: ctx.state };
  return {
    status: states[body.status],
    progress: String(Number(body.progress || 0)) + "%",
    failReason: body.error || "",
    data: body,
    state: { artifacts: body.artifacts || [], pages: Number(body.pages || 0) },
  };
}

export function extractUsage(ctx) {
  // Images are one page. PDFs are counted by the task service during strict
  // signature validation and persisted in the submit response. No document
  // bytes are decoded by this plugin.
  if (ctx.usagePurpose === "billing_ratios") return { pages: 1 };
  const body = ctx.requestBody || {};
  if (body.pages !== undefined) {
    const pages = Number(body.pages);
    if (!Number.isInteger(pages) || pages < 1 || pages > 100) throw new Error("pages must be an integer from 1 to 100");
    return { pages: pages };
  }
  return { pages: 1 };
}

export function extractUsageOnComplete(ctx, result, body) {
  const data = (result && result.data) || {};
  body = body || {};
  const pages = Number(data.pages || body.pages || 0);
  return { pages: Math.min(100, Math.max(0, Number.isFinite(pages) ? pages : 0)) };
}

export function listArtifacts(task) {
  if (task.status !== "SUCCESS") return [];
  const artifacts = (task.data && task.data.artifacts) || [];
  return artifacts.filter(function (item) { return item && item.key; }).map(function (item) {
    return { key: item.key, type: "file", mimeType: item.mimeType || "application/octet-stream" };
  });
}

export function buildContentRequest(ctx) {
  const key = encodeURIComponent(ctx.artifactKey);
  const upstreamId = ctx.upstreamTaskId || (ctx.data && (ctx.data.id || ctx.data.task_id)) || ctx.taskId;
  if (!upstreamId) throw new Error("artifact_not_found");
  return { url: ctx.baseUrl + "/v1/tasks/" + encodeURIComponent(upstreamId) + "/artifacts/" + key + "/content", method: ctx.clientRequest.method, headers: auth(ctx) };
}

export const native = {
  parseDocument: function (ctx) {
    const request = normalize(ctx);
    return { kind: "submit", model: request.model, requestBody: request };
  },
  taskCreated: function (ctx, task) {
    return { task_id: task.task_id, status: "queued", model: task.model, created_at: task.created_at };
  },
  taskStatus: function (ctx, task) {
    const result = Object.assign({}, task.data || {}, { task_id: task.task_id });
    if (task.status === "SUCCESS") {
      const artifacts = listArtifacts(task).map(function (item) {
        const hosted = (ctx.artifacts || {})[item.key];
        return Object.assign({}, item, { content_url: hosted ? hosted.url : undefined });
      });
      result.artifacts = artifacts;
    }
    return result;
  },
  error: function (ctx, error) { return { error: { code: error.code, message: error.message } }; },
};
