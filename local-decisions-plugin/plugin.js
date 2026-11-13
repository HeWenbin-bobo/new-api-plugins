// Piccolo + Jev-Omni native decision adapter for isolated, compatible llama.cpp runtimes.
const MODELS = ["Piccolo-4B-Q4_K_M", "Piccolo-9B-Q8_0", "Jev-Omni-12B-Q4_K_M"];
const MODEL_BASE_URLS = {
  "Piccolo-4B-Q4_K_M": "http://127.0.0.1:18083",
  "Piccolo-9B-Q8_0": "http://127.0.0.1:18083",
  "Jev-Omni-12B-Q4_K_M": "http://127.0.0.1:18503",
};
const MAX_INPUT_TOKENS = 8192;

export const meta = {
  apiVersion: 1,
  key: "local-decisions",
  name: "Local Decisions (Piccolo + Jev-Omni)",
  version: "0.4.0",
  author: { name: "QwenPaw Local" },
  icon: "text:LD",
  description: {
    en: "Piccolo and Jev-Omni native decisions through compatible llama.cpp /v1/systemone runtimes",
    zh: "通过兼容 llama.cpp 的 /v1/systemone 提供 Piccolo 与 Jev-Omni 原生决策",
  },
  baseUrl: "http://127.0.0.1:18083",
  allowedHosts: ["127.0.0.1:18503"],
  auth: "none",
  models: MODELS,
  upstreams: ["vendor"],
  fetchMode: "per_task",
  routes: [{
    method: "POST",
    path: "/v1/systemone",
    type: "submit",
    decode: "decodeSystemOne",
    render: "renderSystemOne",
    models: MODELS,
    retainResult: false,
  }],
  usageSchema: {
    input_tokens: { type: "number", unit: "token", description: { en: "Input token unit price", zh: "输入 token 单价" } },
    output_tokens: { type: "number", unit: "token", description: { en: "Output token unit price", zh: "输出 token 单价" } },
  },
  usageExamples: [{ label: "Decisions", facts: { input_tokens: 1000, output_tokens: 0 } }],
};

const object = value => value !== null && typeof value === "object" && !Array.isArray(value);

function validate(body) {
  if (!object(body)) throw new Error("SystemOne request must be a JSON object");
  if (typeof body.model !== "string" || !MODELS.includes(body.model)) throw new Error("model must be Piccolo-4B-Q4_K_M, Piccolo-9B-Q8_0, or Jev-Omni-12B-Q4_K_M");
  if (!(typeof body.state === "string" || Array.isArray(body.state))) throw new Error("state must be text or an array");
  if (!object(body.questions) || Object.keys(body.questions).length < 1) throw new Error("questions must be a non-empty object");
  for (const [name, question] of Object.entries(body.questions)) {
    if (!name.trim() || !object(question)) throw new Error("Invalid question name or value");
    if (!["choice", "noul"].includes(question.type)) throw new Error("This adapter supports choice and noul questions");
    if (typeof question.instructions !== "string" || !question.instructions.trim()) throw new Error("Question instructions are required");
    if (question.type === "choice") {
      if (!object(question.criteria) || Object.keys(question.criteria).length < 2 || Object.keys(question.criteria).length > 256) {
        throw new Error("choice requires 2 to 256 criteria");
      }
      for (const value of Object.values(question.criteria)) {
        if (typeof value !== "string") throw new Error("Every criterion must be a string");
      }
    }
  }
  return body;
}

function base(ctx) {
  if (typeof ctx.baseUrl !== "string" || !/^https?:\/\/[^\s/?#@]+(?:\/[^\s?#@]*)?$/.test(ctx.baseUrl)) {
    throw new Error("Invalid administrator upstream base URL");
  }
  let value = ctx.baseUrl.replace(/\/+$/, "");
  if (value.endsWith("/v1")) value = value.slice(0, -3);
  return value;
}

function baseFor(ctx) {
  const model = ctx.upstreamModel || ctx.model;
  const configured = MODEL_BASE_URLS[model];
  if (configured) return configured.replace(/\/+$/, "");
  return base(ctx);
}

export function buildSubmitRequest(ctx) {
  const body = validate(ctx.requestBody);
  return {
    url: baseFor(ctx) + "/v1/systemone",
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: Object.assign({}, body, { model: ctx.upstreamModel || ctx.model }),
  };
}

export function parseSubmitResponse(ctx, response) {
  if (response.statusCode < 200 || response.statusCode >= 300) throw new Error("Decision upstream HTTP " + response.statusCode);
  const body = response.body;
  if (!object(body) || typeof body.model !== "string" || !object(body.answers)) throw new Error("Invalid decision response envelope");
  for (const [name, question] of Object.entries(ctx.requestBody.questions)) {
    const answer = body.answers[name];
    if (!object(answer) || answer.type !== question.type) throw new Error("Invalid decision answer for " + name);
    if (question.type === "choice") {
      if (!object(answer.probabilities)) throw new Error("Missing choice probabilities for " + name);
      const keys = Object.keys(answer.probabilities);
      if (keys.length !== Object.keys(question.criteria).length) throw new Error("Probability count mismatch for " + name);
      const sum = keys.reduce((total, key) => total + answer.probabilities[key], 0);
      if (Math.abs(sum - 1) > 0.001) throw new Error("Probabilities are not normalized for " + name);
    }
  }
  if (!object(body.usage) || !Number.isInteger(body.usage.output_tokens) || body.usage.output_tokens !== 0) {
    throw new Error("Decision adapter must not generate answer tokens");
  }
  return { taskId: ctx.publicTaskId, taskData: body, immediate: { status: "SUCCESS", progress: "100%" } };
}

export function extractUsage(ctx) {
  validate(ctx.requestBody);
  if (ctx.usagePurpose === "billing_ratios") return null;
  return { input_tokens: MAX_INPUT_TOKENS, output_tokens: 0 };
}

export function extractUsageOnComplete(ctx, result, body) {
  const input = body && body.usage && body.usage.input_tokens;
  const output = body && body.usage && body.usage.output_tokens;
  if (!Number.isInteger(input) || input < 0 || input > MAX_INPUT_TOKENS) throw new Error("Invalid decision input token usage");
  if (output !== 0) throw new Error("Decision output token usage must be zero");
  return { input_tokens: input, output_tokens: 0 };
}

export function buildQueryRequest() { throw new Error("Decision requests are synchronous; no task retrieval endpoint"); }
export function parseTaskResult() { return { status: "UNKNOWN", reason: "No asynchronous decision task" }; }

export const native = {
  decodeSystemOne(ctx) {
    if (!ctx.body || ctx.body.kind !== "json") throw new Error("JSON body required");
    const body = validate(ctx.body.value);
    return { kind: "submit", model: body.model, action: "systemone", requestBody: body };
  },
  renderSystemOne(ctx, task) { return task.data; },
  error(ctx, error) {
    return { error: { message: "Decision request failed", type: "api_error", param: null, code: error.code || "piccolo_gateway_error" } };
  },
};

