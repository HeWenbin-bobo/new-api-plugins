// WorkBuddy's resolution ladder. Usage is only reported for these values so an
// unexpected upstream string can never invalidate the seconds/credit facts.
const USAGE_RESOLUTIONS = ["720P", "768P", "1080P", "2K", "1440P", "4K"];
const RESOLUTION_SET = new Set(USAGE_RESOLUTIONS);

const CONTENT_HOSTS = new Set([
  "aigc-output-video-1326893053.cos.ap-guangzhou.myqcloud.com",
]);

export const meta = {
  apiVersion: 1,
  key: "workbuddy-panel-video",
  name: "WorkBuddy Panel Video",
  icon: "Kling.Color",
  description: {
    en: "Video generation through a workbuddy2api-panel gateway",
    zh: "通过 workbuddy2api-panel 网关生成视频",
  },
  version: "1.1.2",
  author: { name: "Local" },
  baseUrl: "http://127.0.0.1:7863",
  allowedHosts: [...CONTENT_HOSTS],
  models: ["minimax-video-h3", "kling-video-v3"],
  fetchMode: "per_task",
  protocols: ["openai_video"],
  usageSchema: {
    seconds: {
      type: "number",
      unit: "second",
      description: { en: "Video generation unit price", zh: "视频生成单价" },
    },
    resolution: {
      enum: USAGE_RESOLUTIONS,
      description: { en: "Output video resolution", zh: "输出视频分辨率" },
    },
    credit: {
      type: "number",
      unit: "credit",
      description: { en: "WorkBuddy credit unit price", zh: "WorkBuddy 积分单价" },
    },
  },
  usageExamples: [
    { label: "720P · 5s", facts: { seconds: 5, resolution: "720P", credit: 1 } },
    { label: "1080P · 10s", facts: { seconds: 10, resolution: "1080P", credit: 1 } },
  ],
};

const MAX_INPUT_IMAGE_BYTES = 8 * 1024 * 1024;
const CONTENT_HEADERS = [
  "range", "if-range", "if-match", "if-none-match",
  "if-modified-since", "if-unmodified-since",
];

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}

function object(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}

function positiveSeconds(value) {
  if (value === undefined || value === null || value === "") return undefined;
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    throw new Error("seconds must be a positive number");
  }
  return seconds;
}

function decodeVideoRequest(ctx) {
  const body = ctx.body;
  if (!body || (body.kind !== "json" && body.kind !== "multipart")) {
    throw new Error("JSON or multipart body required");
  }

  let req;
  let file;
  if (body.kind === "json") {
    req = object(body.value);
    if (!req) throw new Error("JSON object required");
  } else {
    req = {};
    for (const name of Object.keys(body.fields || {})) {
      const values = body.fields[name];
      if (values.length !== 1) throw new Error(name + " must be provided once");
      req[name] = values[0];
    }
    for (const item of body.files || []) {
      if (item.field !== "input_reference") {
        throw new Error("unexpected file field: " + item.field);
      }
      if (file) throw new Error("input_reference must be provided once");
      file = item;
    }
  }

  if (!text(req.prompt)) throw new Error("prompt is required");
  const seconds = positiveSeconds(req.seconds === undefined ? req.duration : req.seconds);
  const normalized = { ...req, model: ctx.model };
  delete normalized.duration;
  delete normalized.wait;
  if (seconds !== undefined) normalized.seconds = seconds;

  if (file) {
    if (text(req.input_reference) || text(req.image)) {
      throw new Error("input_reference file and image URL are mutually exclusive");
    }
    normalized.input_reference = {
      __fileRef: file.ref,
      encoding: "dataUrl",
      maxBytes: MAX_INPUT_IMAGE_BYTES,
    };
    delete normalized.image;
  }
  const action = normalized.input_reference || normalized.image || normalized.reference_images
    ? "image_to_video" : "text_to_video";
  return { kind: "submit", model: ctx.model, action, requestBody: normalized };
}

function findResultUrl(data, ctx = {}) {
  const videos = Array.isArray(data.videos) ? data.videos : [];
  const results = Array.isArray(data.data) ? data.data : [];
  return text(ctx.url) || text(ctx.resultUrl) || text(data.url) ||
    text(object(videos[0]) && videos[0].url) ||
    text(object(results[0]) && results[0].url);
}

function contentUrl(ctx) {
  // Panel returns a signed COS URL; do not use the Hub-only /content route.
  // Parse and enforce the allowlist here without moejs-unsupported URL globals.
  const data = object(ctx.data) || {};
  const resultUrl = findResultUrl(data, ctx);
  if (!resultUrl) throw new Error("panel video result url is empty");
  const match = /^https:\/\/([^/?#]+)(\/[^?#]*)?(\?[^#]*)?$/.exec(resultUrl);
  if (!match || (match[2] || "").includes("//")) throw new Error("panel video result url must be an absolute HTTPS URL");
  const authority = match[1];
  if (authority.includes("@") || !/^[A-Za-z0-9.-]+(?::\d+)?$/.test(authority)) {
    throw new Error("panel video result url host is not allowed");
  }
  const colon = authority.lastIndexOf(":");
  const hostname = (colon < 0 ? authority : authority.slice(0, colon)).toLowerCase();
  const port = colon < 0 ? "" : authority.slice(colon + 1);
  if ((port && port !== "443") || !CONTENT_HOSTS.has(hostname)) {
    throw new Error("panel video result url host is not allowed");
  }
  return resultUrl;
}

function failureReason(data) {
  const error = object(data.error);
  const reason = text(error && error.message) || text(data.error) || "video generation failed";
  return reason
    .replace(/https?:\/\/[^\s<>"']+/gi, "[URL]")
    .replace(/\b(authorization\s*:\s*(?:bearer|basic)\s+|api[_-]?key\s*[:=]\s*|token\s*[:=]\s*)[^\s,;]+/gi, "$1[REDACTED]")
    .replace(/[\x00-\x20\x7f]+/g, " ").trim().slice(0, 300);
}

function validIpv6(host) {
  if (!/^\[[0-9A-Fa-f:.]+\]$/.test(host)) return false;
  let address = host.slice(1, -1);
  if (address.includes(".")) {
    const colon = address.lastIndexOf(":");
    const parts = address.slice(colon + 1).split(".");
    if (parts.length !== 4 || parts.some((part) =>
      !/^\d{1,3}$/.test(part) || Number(part) > 255 || (part.length > 1 && part.startsWith("0")))) {
      return false;
    }
    address = address.slice(0, colon + 1) + "0:0";
  }
  const halves = address.split("::");
  if (halves.length > 2) return false;
  const groups = halves.flatMap((half) => half ? half.split(":") : []);
  if (groups.some((group) => !/^[0-9A-Fa-f]{1,4}$/.test(group))) return false;
  return halves.length === 2 ? groups.length < 8 : groups.length === 8;
}

function gatewayUrl(baseUrl, path) {
  // moejs has no browser URL constructor; use deliberately restricted parsing.
  const raw = text(baseUrl);
  const match = /^(https?):\/\/([^/?#]+)([/?#].*)?$/.exec(raw);
  if (!match) throw new Error("panel base url must be an absolute HTTP(S) URL");
  const scheme = match[1], authority = match[2], suffix = match[3] || "";
  const parsedAuthority = /^(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::(\d+))?$/.exec(authority);
  const port = parsedAuthority && parsedAuthority[2];
  if (authority.includes("@") || !parsedAuthority ||
      (parsedAuthority[1].startsWith("[") && !validIpv6(parsedAuthority[1])) ||
      (port && (Number(port) < 1 || Number(port) > 65535)) ||
      suffix.includes("?") || suffix.includes("#")) {
    throw new Error("panel base url must be an absolute HTTP(S) URL without credentials");
  }
  return scheme + "://" + authority + suffix.replace(/\/+$/, "") + path;
}

function panelSubmitBody(ctx, requestBody) {
  const model = text(ctx.upstreamModel) || text(ctx.model);
  if (!model) throw new Error("model is required");
  return {
    ...requestBody,
    model: model.startsWith("cn:") ? model : "cn:" + model,
    wait: false,
  };
}

/** @param {object} ctx new-api DriverContext. @returns {object} request descriptor. */
export function buildSubmitRequest(ctx) {
  const requestBody = object(ctx.requestBody);
  if (!requestBody || !text(requestBody.prompt)) throw new Error("prompt is required");
  return {
    url: gatewayUrl(ctx.baseUrl, "/v1/videos/generations"),
    method: "POST",
    headers: {
      Authorization: "Bearer " + ctx.apiKey,
      "Content-Type": "application/json",
    },
    body: panelSubmitBody(ctx, requestBody),
    action: ctx.action,
  };
}

/** @param {object} ctx new-api DriverContext. @param {object} resp upstream response. */
export function parseSubmitResponse(ctx, resp) {
  const body = object(resp.body);
  const taskId = body && text(body.id);
  if (!taskId) throw new Error("upstream task id is empty");
  return { taskId, taskData: body };
}

/** @param {object} ctx new-api TaskQueryContext. @returns {object} request descriptor. */
export function buildQueryRequest(ctx) {
  return {
    url: gatewayUrl(ctx.baseUrl, "/v1/videos/" + encodeURIComponent(ctx.taskId)),
    method: "GET",
    headers: { Authorization: "Bearer " + ctx.apiKey },
  };
}

/** @param {object} ctx new-api TaskQueryContext. @param {object} body decoded upstream body. */
export function parseTaskResult(ctx, body) {
  const data = object(body);
  if (!data) return { status: "UNKNOWN", reason: "upstream response must be a JSON object" };
  const statuses = {
    queued: "QUEUED",
    pending: "QUEUED",
    submitted: "SUBMITTED",
    processing: "IN_PROGRESS",
    in_progress: "IN_PROGRESS",
    running: "IN_PROGRESS",
    completed: "SUCCESS",
    succeeded: "SUCCESS",
    failed: "FAILURE",
    rejected: "FAILURE",
    cancelled: "FAILURE",
    lost: "FAILURE",
  };
  const status = statuses[data.status];
  if (!status) {
    return { status: "UNKNOWN", reason: "unrecognized status: " + String(data.status || "") };
  }
  const result = { status };
  if (status === "SUCCESS") {
    const url = findResultUrl(data);
    if (url) result.url = url;
  }
  const progress = Number(data.progress);
  if (status !== "SUCCESS" && Number.isFinite(progress) && progress > 0 && progress < 100) {
    result.progress = String(progress) + "%";
  }
  if (status === "FAILURE") result.reason = failureReason(data);
  return result;
}

export function listArtifacts(task) {
  return task.status === "SUCCESS"
    ? [{ key: "video", type: "video", mimeType: "video/mp4" }] : [];
}

export function buildContentRequest(ctx) {
  if (ctx.artifactKey !== "video") throw new Error("artifact_not_found");
  const headers = {};
  for (const name of CONTENT_HEADERS) {
    for (const key of Object.keys((ctx.clientRequest && ctx.clientRequest.headers) || {})) {
      if (key.toLowerCase() === name) headers[key] = ctx.clientRequest.headers[key];
    }
  }
  const data = object(ctx.data) || {};
  return {
    url: contentUrl(ctx),
    method: (ctx.clientRequest && ctx.clientRequest.method) || "GET",
    // panel 成品是第三方 COS 签名直链，不转发 panel API key。
    headers,
  };
}

export function extractUsage(ctx) {
  const req = object(ctx.requestBody) || {};
  const usage = {};
  const seconds = positiveSeconds(req.seconds);
  if (seconds !== undefined) usage.seconds = seconds;
  const resolution = text(req.resolution).toUpperCase();
  if (RESOLUTION_SET.has(resolution)) usage.resolution = resolution;
  return usage;
}

export function extractUsageOnComplete(ctx, result, body) {
  const data = object(body) || {};
  const usage = {};
  const seconds = Number(data.seconds);
  if (Number.isFinite(seconds) && seconds > 0) usage.seconds = seconds;
  const resolution = text(data.resolution).toUpperCase();
  if (RESOLUTION_SET.has(resolution)) usage.resolution = resolution;
  const credit = Number(data.credit);
  if (Number.isFinite(credit) && credit >= 0) usage.credit = credit;
  return usage;
}

export const protocols = {
  openai_video: {
    decodeRequest: decodeVideoRequest,
    render: function (ctx, task) {
      const data = object(task.data) || {};
      // Do not expose the upstream task id or expiring signed COS URL to clients.
      // Clients download through GET /v1/videos/{public-id}/content, whose target
      // is restricted to the configured COS hosts by contentUrl().
      const { id, task_id, poll, url, ...extensions } = data;
      return { ...extensions, id: task.task_id };
    },
  },
};
