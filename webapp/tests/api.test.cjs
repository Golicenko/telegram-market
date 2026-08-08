const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "js", "api.js"), "utf8");

function loadApi(fetchImpl, initData = "") {
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
  const context = {
    window,
    document: { baseURI: "https://autoflow.example/" },
    fetch: fetchImpl,
    performance,
    URL,
    URLSearchParams,
    AbortController,
    FormData,
    CustomEvent: class CustomEvent { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
    console: { warn: (...args) => warnings.push(args), error() {}, log() {} },
    JSON,
    Date,
    Promise,
    Error,
  };
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
  const { api, warnings } = loadApi(async () => { throw new Error("offline"); }, "user=%7B%22id%22%3A99%7D&hash=do-not-log");
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
  const { api } = loadApi(async () => { calls += 1; throw new Error("offline"); });
  await assert.rejects(api.request("/listings", { method: "POST", body: "{}", timeoutMs: 20 }), (error) => error.errorType === "network");
  assert.equal(calls, 1);
});

test("a cart timeout is bounded and reported without exposing secrets", async () => {
  const { api, warnings } = loadApi((_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  }), "auth_date=1&user=%7B%22id%22%3A7%7D&hash=private-value");
  await assert.rejects(api.request("/cart", { timeoutMs: 8, retries: 0 }), (error) => error.errorType === "timeout");
  assert.equal(warnings.length, 1);
  assert.equal(JSON.stringify(warnings).includes("private-value"), false);
});
