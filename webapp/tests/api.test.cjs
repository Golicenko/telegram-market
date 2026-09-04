const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "js", "api.js"), "utf8");

function loadApi(fetchImpl, initData = "", options = {}) {
  const warnings = [];
  const window = {
    AUTO_FLOW_API_BASE: undefined,
    location: { origin: "https://autoflow.example", protocol: "https:", href: "https://autoflow.example/" },
    Telegram: { WebApp: { initData, platform: "android" } },
    AutoFlowStartupStage: "auth_started",
    navigator: { userAgent: "Telegram Android WebView" },
    setTimeout,
    clearTimeout,
    dispatchEvent() {},
  };
  if (options.XMLHttpRequest) window.XMLHttpRequest = options.XMLHttpRequest;
  const context = {
    window,
    document: { baseURI: "https://autoflow.example/" },
    fetch: fetchImpl,
    performance,
    URL,
    URLSearchParams,
    FormData,
    CustomEvent: class CustomEvent { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
    console: { warn: (...args) => warnings.push(args), error() {}, log() {} },
    JSON,
    Date,
    Promise,
    Error,
  };
  if (options.abortController !== false) context.AbortController = AbortController;
  vm.runInNewContext(source, context, { filename: "api.js" });
  return { api: window.AutoFlowApi, warnings };
}

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 500 ? "Server Error" : "OK",
    json: async () => payload,
  };
}

test("uses the public same-origin API and sends Telegram auth without logging initData", async () => {
  const initData = "auth_date=1&user=%7B%22id%22%3A42%7D&hash=secret";
  let captured;
  const { api, warnings } = loadApi(async (url, options) => { captured = { url, options }; return jsonResponse({ ok: true }); }, initData);
  assert.deepEqual(await api.request("/me", { retries: 0 }), { ok: true });
  assert.equal(captured.url, "https://autoflow.example/api/me");
  assert.equal(captured.options.headers["X-Telegram-Init-Data"], initData);
  assert.equal(captured.options.headers["X-Telegram-Platform"], "android");
  assert.equal(captured.options.headers["X-AutoFlow-Startup-Stage"], "auth_started");
  assert.equal(warnings.length, 0);
});

test("diagnostics include safe startup context but never full initData", async () => {
  const { api, warnings } = loadApi(async () => { throw new TypeError("offline"); }, "user=%7B%22id%22%3A99%7D&hash=do-not-log");
  await assert.rejects(api.request("/me", { retries: 0, timeoutMs: 20 }));
  const diagnostic = warnings[0][1];
  assert.equal(diagnostic.startup_stage, "auth_started");
  assert.equal(diagnostic.telegram_user_id, 99);
  assert.equal(diagnostic.user_agent, "Telegram Android WebView");
  assert.equal(JSON.stringify(warnings).includes("do-not-log"), false);
});

test("retries one temporary 500 and recovers", async () => {
  let calls = 0;
  const { api } = loadApi(async () => {
    calls += 1;
    return calls === 1 ? jsonResponse({ detail: "temporary" }, 500) : jsonResponse([{ id: 1 }]);
  });
  assert.deepEqual(await api.request("/listings?type=regular", { retries: 1, retryDelayMs: 1 }), [{ id: 1 }]);
  assert.equal(calls, 2);
});

test("aborts a hanging request after timeout and limits retries", async () => {
  let calls = 0;
  const { api, warnings } = loadApi((_url, options) => {
    calls += 1;
    return new Promise((_resolve, reject) => options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
  });
  const started = Date.now();
  await assert.rejects(api.request("/advertisement", { timeoutMs: 8, retries: 1, retryDelayMs: 1 }), (error) => error.errorType === "timeout");
  assert.equal(calls, 2);
  assert.ok(Date.now() - started < 250);
  assert.equal(warnings.length, 2);
  assert.equal(JSON.stringify(warnings).includes("hash=secret"), false);
});

test("does not automatically retry non-idempotent POST requests", async () => {
  let calls = 0;
  const { api } = loadApi(async () => { calls += 1; throw new TypeError("offline"); });
  await assert.rejects(api.request("/listings", { method: "POST", body: "{}", timeoutMs: 20 }), (error) => error.errorType === "network");
  assert.equal(calls, 1);
});

test("a secondary request timeout is bounded and reported without exposing secrets", async () => {
  const { api, warnings } = loadApi((_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  }), "auth_date=1&user=%7B%22id%22%3A7%7D&hash=private-value");
  await assert.rejects(api.request("/profile", { timeoutMs: 8, retries: 0 }), (error) => error.errorType === "timeout");
  assert.equal(warnings.length, 1);
  assert.equal(JSON.stringify(warnings).includes("private-value"), false);
});

test("works in an older Android WebView without AbortController", async () => {
  const { api } = loadApi(async () => jsonResponse({ ok: true }), "", { abortController: false });
  assert.deepEqual(await api.request("/health", { retries: 0, timeoutMs: 50 }), { ok: true });
});

test("timeout remains bounded without AbortController", async () => {
  const { api } = loadApi(() => new Promise(() => {}), "", { abortController: false });
  await assert.rejects(
    api.request("/health", { retries: 0, timeoutMs: 8 }),
    (error) => error.errorType === "timeout",
  );
});

test("429 is retried once and respects a bounded Retry-After", async () => {
  let calls = 0;
  const { api } = loadApi(async () => {
    calls += 1;
    if (calls > 1) return jsonResponse({ ok: true });
    return {
      ...jsonResponse({ detail: "slow down" }, 429),
      headers: { get: (name) => name === "Retry-After" ? "0.001" : null },
    };
  });
  assert.deepEqual(await api.request("/health", { retries: 1, retryDelayMs: 1 }), { ok: true });
  assert.equal(calls, 2);
});

test("invalid JSON is reported once and is not retried", async () => {
  let calls = 0;
  const { api } = loadApi(async () => {
    calls += 1;
    return { ok: true, status: 200, json: async () => { throw new Error("html response"); } };
  });
  await assert.rejects(api.request("/health", { retries: 2, retryDelayMs: 1 }), (error) => error.errorType === "invalid_json");
  assert.equal(calls, 1);
});

test("every request carries a short diagnostic id without exposing auth", async () => {
  let captured;
  const { api } = loadApi(async (_url, options) => { captured = options; return jsonResponse({ ok: true }); });
  await api.request("/health", { retries: 0 });
  assert.match(captured.headers["X-AutoFlow-Error-ID"], /^AF-[A-Z0-9]{5,10}$/);
});

test("photo upload distinguishes network, size, format, auth, rate and timeout failures", () => {
  for (const message of [
    "Не удалось установить соединение с сервером. Проверьте интернет.",
    "Фотография слишком большая.",
    "Формат фотографии не поддерживается.",
    "Сессия Telegram истекла. Откройте Market заново.",
    "Слишком много запросов. Попробуйте через несколько секунд.",
    "Сервер не ответил вовремя при загрузке фотографии. Попробуйте снова.",
  ]) assert.match(source, new RegExp(message.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(source, /prepareImage/);
  assert.match(source, /2560/);
  assert.match(source, /retries: 0/);
  assert.match(source, /upload_stage/);
  assert.match(source, /prepared_size/);
});

test("non-network client failures are not mislabeled as offline", async () => {
  const { api } = loadApi(async () => { throw new Error("formdata failed"); });
  await assert.rejects(api.request("/uploads", { method: "POST", body: "{}", retries: 0 }), (error) => {
    assert.equal(error.errorType, "client_request");
    assert.notEqual(error.message, "Нет соединения с сервером");
    return true;
  });
});

test("upload preserves the AF error id, stage and HTTP status for support", async () => {
  const { api } = loadApi(async () => jsonResponse({ detail: "temporarily unavailable" }, 503));
  const file = new Blob(["image-bytes"], { type: "image/jpeg" });
  Object.defineProperty(file, "name", { value: "mobile.jpg" });
  await assert.rejects(api.upload(file), (error) => {
    assert.equal(error.status, 503);
    assert.match(error.message, /503/);
    assert.match(error.autoflowErrorId, /^AF-/);
    assert.equal(error.upload_stage, "fetch");
    assert.equal(error.file_mime, "image/jpeg");
    return true;
  });
});

test("training upload reports real transport progress and keeps the backend response authoritative", async () => {
  const progress = [];
  class FakeXMLHttpRequest {
    constructor() { this.upload = {}; this.status = 201; this.responseText = JSON.stringify({ delivery_reference: "telegram-file-id", material_type: "video", file_size: 8 }); this.headers = {}; }
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader(name, value) { this.headers[name] = value; }
    send() {
      this.upload.onprogress({ lengthComputable: true, loaded: 4, total: 8 });
      this.onload();
    }
  }
  const { api } = loadApi(async () => { throw new Error("fetch must not be used"); }, "", { XMLHttpRequest: FakeXMLHttpRequest });
  const file = new Blob(["12345678"], { type: "video/mp4" });
  Object.defineProperty(file, "name", { value: "lesson.mp4" });
  const response = await api.upload(file, "/admin/training/materials/upload?material_type=file", {
    kind: "training",
    prepareImage: false,
    onProgress: (value) => progress.push(value),
  });
  assert.deepEqual(progress, [50, 100]);
  assert.equal(response.delivery_reference, "telegram-file-id");
  assert.equal(response.material_type, "video");
});
