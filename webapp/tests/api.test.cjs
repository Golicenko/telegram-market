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
    setTimeout: options.setTimeout || setTimeout,
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
  Object.assign(context, options.globals || {});
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

for (const status of [400, 401, 402, 403, 404, 409, 413, 415, 422, 429, 500, 502, 503, 504]) {
  test(`HTTP ${status} has actionable Russian text and retains diagnostic status without leaking internals`, async () => {
    const {api} = loadApi(async () => jsonResponse({detail: 'Traceback SQLAlchemy SELECT * FROM users secret'}, status));
    await assert.rejects(api.request('/listings', {method: 'POST', body: '{}'}), e => {
      assert.equal(e.status, status); assert.match(e.message, /[А-Яа-я]/);
      assert.doesNotMatch(e.message, /SQLAlchemy|SELECT|users|secret/); assert.match(e.autoflowErrorId, /^AF-/);
      return true;
    });
  });
}

test('402 VIP remains machine-readable and directs user to shortfall checkout', async () => {
  const detail = {code: 'insufficient_af_coins', purpose: 'listing_promotion', missing_af_coins: '3'};
  const {api} = loadApi(async () => jsonResponse({detail}, 402));
  await assert.rejects(api.request('/listings', {method: 'POST', body: '{}'}), e => {
    assert.equal(e.detail, detail); assert.match(e.message, /VIP.*Доплатите/); return true;
  });
});

test('state conflict is not falsely described as an already published listing', async () => {
  const {api} = loadApi(async () => jsonResponse({detail: 'Conflict'}, 409));
  await assert.rejects(api.request('/listings', {method: 'POST', body: '{}'}), e => {
    assert.match(e.message, /Состояние.*изменилось/); assert.doesNotMatch(e.message, /уже опубликовано|успешно/); return true;
  });
});

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

test("upload preserves a specific safe backend decode/size reason", async () => {
  for (const status of [413, 415, 422]) {
    const detail = "Фотография повреждена: повторите экспорт из галереи";
    const { api } = loadApi(async () => jsonResponse({ detail }, status));
    await assert.rejects(api.upload(new Blob(["bad"], {type:"image/jpeg"})), error => error.status === status && error.message === detail);
  }
});

test("known-size PNG with generic MIME is normalized; SVG/AVIF never decoded without a pixel bound", async () => {
  let decodes = 0, uploaded;
  const globals = {
    File,
    createImageBitmap: async () => { decodes++; return {width:32,height:24,close(){}}; },
    document: {baseURI:"https://autoflow.example/", createElement: () => ({
      getContext: () => ({fillRect(){},drawImage(){}}),
      toBlob: done => done(new Blob(["normalized-jpeg"], {type:"image/jpeg"})),
    })},
  };
  const {api} = loadApi(async (_url, options) => {uploaded=options.body.get("file");return jsonResponse({url:"/api/media/test"},201);}, "", {globals});
  const header=Buffer.alloc(24);header.set([137,80,78,71,13,10,26,10]);header.writeUInt32BE(32,16);header.writeUInt32BE(24,20);
  await api.upload(new File([header],"mobile.bin",{type:"application/octet-stream"}));
  assert.equal(decodes,1);assert.equal(uploaded.type,"image/jpeg");assert.equal(uploaded.name,"mobile.jpg");
  await api.upload(new File(["<svg>not a raster photo</svg>"],"fake.jpg",{type:"image/jpeg"}));
  assert.equal(decodes,1,"SVG cannot be laundered into a permitted raster via canvas");
  assert.equal(await uploaded.text(),"<svg>not a raster photo</svg>");
  await api.upload(new File([new Uint8Array([0,0,0,24]),"ftypavif",new Uint8Array(20)],"mobile.avif"));
  assert.equal(decodes,1,"AVIF safely falls back to server decoder instead of full WebView decode");
});

test("50 MB source is optimized before the smaller wire limit, with bounded quality retries", async () => {
  let uploaded, encodes=0, bitmapClosed=false, canvas;
  const header=Buffer.alloc(24);header.set([137,80,78,71,13,10,26,10]);header.writeUInt32BE(4000,16);header.writeUInt32BE(3000,20);
  const file=new File([header,Buffer.alloc(50*1024*1024)],"large.png",{type:"image/png"});
  const {api}=loadApi(async(_url,options)=>{uploaded=options.body.get('file');assert.equal(options.headers['Content-Type'],undefined);return jsonResponse({url:'/api/media/saved'});},'',{globals:{
    File, createImageBitmap:async(_file,options)=>{assert.equal(options.resizeWidth,2560);assert.equal(options.resizeHeight,undefined,'preserve EXIF-rotated aspect ratio');return {width:2560,height:1920,close(){bitmapClosed=true;}};},
    document:{baseURI:'https://autoflow.example/',createElement:()=>canvas={getContext:()=>({fillRect(){},drawImage(){}}),toBlob(done){encodes++;done(new Blob([Buffer.alloc(encodes===1?2*1024*1024:200000)],{type:'image/jpeg'}));}}},
  }});
  await api.upload(file,'/uploads',{maxBytes:1024*1024});
  assert.equal(encodes,2);assert.equal(uploaded.size,200000);assert.equal(uploaded.name,'large.jpg');assert.equal(uploaded.type,'image/jpeg');
  assert(bitmapClosed);assert.equal(canvas.width,0);assert.equal(canvas.height,0);
});

test("48 MP JPEG is never decoded in WebView and goes to server as original", async () => {
  let uploaded;
  const bytes=Buffer.from([255,216,255,192,0,8,8,23,112,31,64,1,0]);
  const {api}=loadApi(async(_url,options)=>{uploaded=options.body.get('file');return jsonResponse({url:'/api/media/server'});},'',{globals:{createImageBitmap(){throw new Error('must not decode');}}});
  await api.upload(new File([bytes],'48mp.jpg',{type:'image/jpeg'}));
  assert.equal(uploaded.size,bytes.length);
});

test("source and prepared size limits are distinct, enforced before transport", async () => {
  let calls=0;
  const {api}=loadApi(async()=>{calls++;return jsonResponse({});});
  await assert.rejects(api.upload(new Blob(['12345']),'/uploads',{sourceMaxBytes:4}),e=>e.status===413);
  await assert.rejects(api.upload(new Blob(['12345']),'/uploads',{maxBytes:4,sourceMaxBytes:8}),e=>e.status===413 && e.prepared_size===5);
  assert.equal(calls,0);
});

test("hanging WebView decode falls back to server; a late bitmap is closed", async () => {
  let finish, closed=false, uploaded;
  const header=Buffer.alloc(24);header.set([137,80,78,71,13,10,26,10]);header.writeUInt32BE(32,16);header.writeUInt32BE(24,20);
  const {api}=loadApi(async(_url,options)=>{uploaded=options.body.get('file');return jsonResponse({url:'/api/media/fallback'});},'',{
    setTimeout:(fn,ms)=>setTimeout(fn,ms===10000?5:ms),
    globals:{createImageBitmap:()=>new Promise(resolve=>{finish=resolve;})},
  });
  await api.upload(new File([header],'phone.png',{type:'image/png'}));
  assert.equal(uploaded.size,header.length);assert.equal(uploaded.type,'image/png');
  finish({close(){closed=true;}});
  await new Promise(resolve=>setTimeout(resolve,0));assert(closed);
});
