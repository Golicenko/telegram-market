(function () {
  "use strict";

  const DEFAULT_TIMEOUT_MS = 12000;
  const DEFAULT_RETRY_DELAY_MS = 650;
  const rawApiBase = window.AUTO_FLOW_API_BASE || `${window.location.origin}/api`;
  const API_BASE = rawApiBase.replace(/\/$/, "");

  function requestErrorId() {
    const bytes = new Uint8Array(5);
    if (typeof window.crypto?.getRandomValues === "function") window.crypto.getRandomValues(bytes);
    else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
    return `AF-${[...bytes].map((value) => value.toString(36).toUpperCase().padStart(2, "0")).join("").slice(0, 8)}`;
  }

  if (window.location.protocol === "https:" && API_BASE.startsWith("http:")) {
    throw new Error("Небезопасный HTTP API недоступен со страницы HTTPS");
  }

  class ApiError extends Error {
    constructor(status, detail, metadata = {}) {
      super(readableErrorDetail(detail));
      this.name = "ApiError";
      this.status = status;
      this.detail = detail;
      Object.assign(this, metadata);
    }
  }

  function readableErrorDetail(detail) {
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const fieldNames = {
        brand: "Автомобиль",
        model: "Модель",
        power_hp: "Мощность",
        max_speed_kph: "Максимальная скорость",
        description: "Описание",
        price_af_coins: "Цена",
        image_urls: "Фотографии",
        delivery_time_estimate: "Срок передачи",
        file: "Фотография",
      };
      const messages = detail.map((item) => {
        const location = Array.isArray(item?.loc) ? item.loc.filter((part) => !["body", "query", "path"].includes(String(part))) : [];
        const rawField = location.length ? location[location.length - 1] : null;
        const field = fieldNames[rawField] || rawField || "Данные";
        const type = String(item?.type || "");
        let message = item?.msg || "некорректное значение";
        if (type === "missing") message = "поле обязательно";
        else if (type === "greater_than") message = `значение должно быть больше ${item?.ctx?.gt ?? 0}`;
        else if (type === "greater_than_equal") message = `значение должно быть не меньше ${item?.ctx?.ge ?? 0}`;
        else if (type === "int_parsing") message = "введите целое число";
        else if (type === "decimal_parsing" || type === "float_parsing") message = "введите корректное число";
        else if (type === "too_short") message = "поле не должно быть пустым";
        return `${field}: ${message}`;
      }).filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
    if (detail && typeof detail === "object") {
      if (typeof detail.message === "string") return detail.message;
      if (typeof detail.detail === "string") return detail.detail;
    }
    return "Сервер отклонил запрос. Проверьте заполненные поля.";
  }

  function authHeaders() {
    const headers = { Accept: "application/json" };
    const initData = window.Telegram?.WebApp?.initData;
    if (initData) headers["X-Telegram-Init-Data"] = initData;
    headers["X-Telegram-Platform"] = window.Telegram?.WebApp?.platform || "browser";
    if (window.AutoFlowStartupStage) headers["X-AutoFlow-Startup-Stage"] = window.AutoFlowStartupStage;
    return headers;
  }

  function telegramUserId() {
    try {
      const rawUser = new URLSearchParams(window.Telegram?.WebApp?.initData || "").get("user");
      return rawUser ? JSON.parse(rawUser).id || null : null;
    } catch (_error) {
      return null;
    }
  }

  function safeEndpoint(url) {
    try { return new URL(url, window.location.href).pathname; }
    catch (_error) { return "unknown"; }
  }

  function diagnostic(error, url, durationMs, attempt) {
    const entry = {
      error_id: error?.autoflowErrorId || null,
      endpoint: safeEndpoint(url),
      status: Number(error?.status || 0),
      duration_ms: Math.round(durationMs),
      error_type: error?.errorType || error?.name || "Error",
      telegram_user_id: telegramUserId(),
      platform: window.Telegram?.WebApp?.platform || "browser",
      startup_stage: window.AutoFlowStartupStage || "unknown",
      user_agent: String(window.navigator?.userAgent || "unknown").slice(0, 180),
      attempt,
      time: new Date().toISOString(),
    };
    console.warn("[AutoFlow API]", entry);
    try { window.dispatchEvent(new CustomEvent("autoflow:api-error", { detail: entry })); }
    catch (_error) { /* Diagnostic events are optional. */ }
  }

  function delay(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  function shouldRetry(error) {
    const status = Number(error?.status || 0);
    if (error?.errorType === "invalid_json") return false;
    return error?.errorType === "timeout" || error?.errorType === "network" || [408, 429, 500, 502, 503, 504].includes(status);
  }

  async function perform(url, options = {}, includeAuth = true) {
    const {
      timeoutMs = DEFAULT_TIMEOUT_MS,
      retries,
      retryDelayMs = DEFAULT_RETRY_DELAY_MS,
      ...fetchOptions
    } = options;
    const method = String(fetchOptions.method || "GET").toUpperCase();
    const maxRetries = retries ?? (["GET", "HEAD"].includes(method) ? 1 : 0);
    const headers = { ...(includeAuth ? authHeaders() : { Accept: "application/json" }), ...(fetchOptions.headers || {}) };
    const errorId = requestErrorId();
    headers["X-AutoFlow-Error-ID"] = errorId;
    if (fetchOptions.body && !(fetchOptions.body instanceof FormData)) headers["Content-Type"] = "application/json";

    for (let attempt = 1; attempt <= maxRetries + 1; attempt += 1) {
      const controller = typeof AbortController === "function" ? new AbortController() : null;
      let timedOut = false;
      const startedAt = performance.now();
      const externalSignal = fetchOptions.signal;
      const forwardAbort = () => controller?.abort();
      externalSignal?.addEventListener?.("abort", forwardAbort, { once: true });
      let timeout;
      try {
        const timeoutRequest = new Promise((_resolve, reject) => {
          timeout = window.setTimeout(() => {
            timedOut = true;
            controller?.abort();
            reject(new ApiError(0, "Сервер не ответил вовремя", { endpoint: safeEndpoint(url), errorType: "timeout", autoflowErrorId: errorId }));
          }, Math.max(1, timeoutMs));
        });
        const request = fetch(url, { ...fetchOptions, headers, signal: controller?.signal || externalSignal });
        const response = await Promise.race([request, timeoutRequest]);
        if (!response.ok) {
          let detail = response.statusText || "Ошибка запроса";
          try {
            const payload = await response.json();
            detail = payload.detail || payload;
          } catch (_error) { /* Keep the HTTP status text. */ }
          const retryAfter = Number(response.headers?.get?.("Retry-After") || 0);
          throw new ApiError(response.status, detail, {
            endpoint: safeEndpoint(url),
            errorType: "http",
            autoflowErrorId: errorId,
            retryAfterMs: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : 0,
          });
        }
        if (response.status === 204) return null;
        try { return await response.json(); }
        catch (error) { throw new ApiError(502, "Сервер вернул некорректный ответ", { endpoint: safeEndpoint(url), errorType: "invalid_json", cause: error, autoflowErrorId: errorId }); }
      } catch (rawError) {
        const durationMs = performance.now() - startedAt;
        const aborted = !timedOut && (rawError?.name === "AbortError" || externalSignal?.aborted);
        const isNetworkFailure = !timedOut && !aborted && rawError?.name === "TypeError";
        const error = rawError instanceof ApiError
          ? rawError
          : new ApiError(0, timedOut ? "Сервер не ответил вовремя" : aborted ? "Загрузка отменена" : isNetworkFailure ? "Нет соединения с сервером" : "Ошибка подготовки запроса", {
              endpoint: safeEndpoint(url),
              errorType: timedOut ? "timeout" : aborted ? "aborted" : isNetworkFailure ? "network" : "client_request",
              cause: rawError,
              autoflowErrorId: errorId,
            });
        error.duration_ms = Math.round(durationMs);
        diagnostic(error, url, durationMs, attempt);
        if (attempt > maxRetries || !shouldRetry(error) || externalSignal?.aborted) throw error;
        const exponentialDelay = Math.min(5000, retryDelayMs * (2 ** (attempt - 1)));
        await delay(Math.max(exponentialDelay, Number(error.retryAfterMs || 0)));
      } finally {
        window.clearTimeout(timeout);
        externalSignal?.removeEventListener?.("abort", forwardAbort);
      }
    }
    throw new ApiError(0, "Запрос не выполнен", { endpoint: safeEndpoint(url), errorType: "unknown" });
  }

  function request(path, options = {}) {
    return perform(`${API_BASE}${path}`, options, true);
  }

  function resource(path, options = {}) {
    return perform(new URL(path, document.baseURI).toString(), options, false);
  }

  function uploadError(error, metadata = {}, kind = "image") {
    const details = { ...metadata, endpoint: error?.endpoint || metadata.endpoint || "/api/uploads", errorType: error?.errorType || metadata.errorType || "upload", cause: error, autoflowErrorId: error?.autoflowErrorId || metadata.autoflowErrorId };
    if (kind === "training") {
      if (error?.errorType === "timeout") return new ApiError(0, "Загрузка не завершилась за допустимое время. Проверьте соединение и повторите.", details);
      if (error?.errorType === "network") return new ApiError(0, "Не удалось загрузить файл. Проверьте интернет и попробуйте ещё раз.", details);
      if (error?.errorType === "aborted") return new ApiError(0, "Загрузка файла отменена.", details);
      if (error?.status === 413 || error?.status === 415) return new ApiError(error.status, readableErrorDetail(error.detail), details);
      if ([502, 503, 504].includes(Number(error?.status))) return new ApiError(error.status, "Сервер временно недоступен. Попробуйте ещё раз через несколько секунд.", details);
      return new ApiError(error?.status || 0, error?.message || "Не удалось загрузить файл.", details);
    }
    if (error?.errorType === "timeout") return new ApiError(0, "Сервер не ответил вовремя при загрузке фотографии. Попробуйте снова.", details);
    if (error?.errorType === "network") return new ApiError(0, "Не удалось установить соединение с сервером. Проверьте интернет.", details);
    if (error?.errorType === "aborted") return new ApiError(0, "Загрузка фотографии была отменена.", details);
    if (error?.errorType === "client_request") return new ApiError(0, "Не удалось подготовить фотографию к отправке.", details);
    const messages = {
      401: "Сессия Telegram истекла. Откройте Market заново.",
      413: "Фотография слишком большая.",
      415: "Формат фотографии не поддерживается.",
      422: "Не удалось обработать фотографию.",
      429: "Слишком много запросов. Попробуйте через несколько секунд.",
      500: "Ошибка сервера при обработке фотографии.",
      502: "Сервер загрузки временно недоступен (502). Попробуйте снова.",
      503: "Сервис загрузки временно недоступен (503). Попробуйте снова.",
      504: "Сервер не успел обработать фотографию (504). Попробуйте снова.",
    };
    return new ApiError(error?.status || 0, messages[error?.status] || error?.message || "Не удалось загрузить фотографию.", details);
  }

  function canvasBlob(canvas, type, quality) {
    if (typeof canvas.toBlob !== "function") return Promise.resolve(null);
    return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
  }

  function uploadWithProgress(path, body, options, metadata) {
    return new Promise((resolve, reject) => {
      const xhr = new window.XMLHttpRequest();
      const url = `${API_BASE}${path}`;
      const errorId = requestErrorId();
      const startedAt = performance.now();
      xhr.open("POST", url, true);
      xhr.timeout = options.timeoutMs;
      const headers = authHeaders();
      headers["X-AutoFlow-Error-ID"] = errorId;
      Object.entries(headers).forEach(([name, value]) => xhr.setRequestHeader(name, value));
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && typeof options.onProgress === "function") {
          options.onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
        }
      };
      const fail = (errorType, detail) => {
        const error = new ApiError(Number(xhr.status || 0), detail, {
          endpoint: safeEndpoint(url), errorType, autoflowErrorId: errorId,
          duration_ms: Math.round(performance.now() - startedAt),
        });
        diagnostic(error, url, error.duration_ms, 1);
        reject(error);
      };
      xhr.onerror = () => fail("network", "Нет соединения с сервером");
      xhr.ontimeout = () => fail("timeout", "Сервер не ответил вовремя");
      xhr.onabort = () => fail("aborted", "Загрузка отменена");
      xhr.onload = () => {
        let payload = null;
        try { payload = xhr.responseText ? JSON.parse(xhr.responseText) : null; }
        catch (_error) { return fail("invalid_json", "Сервер вернул некорректный ответ"); }
        if (xhr.status < 200 || xhr.status >= 300) return fail("http", payload?.detail || xhr.statusText || "Ошибка запроса");
        if (typeof options.onProgress === "function") options.onProgress(100);
        resolve(payload);
      };
      xhr.send(body);
    });
  }

  async function prepareImage(file, diagnosticMetadata) {
    diagnosticMetadata.upload_stage = "client_inspect";
    if (!file || file.size <= 8 * 1024 * 1024 || !/^image\/(jpeg|png|webp)$/i.test(file.type || "")) return file;
    let bitmap = null;
    let objectUrl = null;
    try {
      if (typeof createImageBitmap === "function") {
        bitmap = await createImageBitmap(file);
      } else {
        objectUrl = URL.createObjectURL(file);
        bitmap = await new Promise((resolve, reject) => {
          const image = new Image();
          image.onload = () => resolve(image);
          image.onerror = () => reject(new Error("image_decode_failed"));
          image.src = objectUrl;
        });
      }
      const width = Number(bitmap.width || bitmap.naturalWidth || 0);
      const height = Number(bitmap.height || bitmap.naturalHeight || 0);
      diagnosticMetadata.image_width = width || null;
      diagnosticMetadata.image_height = height || null;
      if (!width || !height) return file;
      diagnosticMetadata.upload_stage = "client_compress";
      const scale = Math.min(1, 2560 / Math.max(width, height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      const context = canvas.getContext("2d", { alpha: false });
      if (!context) return file;
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await canvasBlob(canvas, "image/jpeg", 0.86);
      if (!blob || blob.size >= file.size) return file;
      const safeName = String(file.name || "photo").replace(/\.[^.]+$/, "") || "photo";
      if (typeof File === "function") {
        return new File([blob], `${safeName}.jpg`, { type: "image/jpeg", lastModified: file.lastModified || Date.now() });
      }
      return blob;
    } catch (error) {
      console.warn("[AutoFlow Image] client compression skipped", { error_type: error?.name || "Error" });
      diagnosticMetadata.compression_error_type = error?.name || "Error";
      return file;
    } finally {
      bitmap?.close?.();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    }
  }

  async function upload(file, path = "/uploads", options = {}) {
    const kind = options.kind || "image";
    const maxBytes = Number(options.maxBytes || 30 * 1024 * 1024);
    const metadata = {
      endpoint: `/api${path.split("?")[0]}`,
      upload_stage: "client_validate",
      file_mime: String(file?.type || "unknown").slice(0, 80),
      file_size: Number(file?.size || 0),
      image_width: null,
      image_height: null,
    };
    if (!file?.size) throw uploadError(new ApiError(422, kind === "training" ? "Файл пуст." : "Не удалось обработать фотографию.", { errorType: "upload" }), metadata, kind);
    if (file.size > maxBytes) throw uploadError(new ApiError(413, kind === "training" ? `Файл слишком большой для загрузки. Максимум: ${Math.floor(maxBytes / 1024 / 1024)} МБ.` : "Фотография слишком большая.", { errorType: "upload" }), metadata, kind);
    try {
      const preparedFile = options.prepareImage === false ? file : await prepareImage(file, metadata);
      metadata.prepared_mime = String(preparedFile?.type || "unknown").slice(0, 80);
      metadata.prepared_size = Number(preparedFile?.size || 0);
      metadata.upload_stage = "formdata";
      const body = new FormData();
      body.append("file", preparedFile, preparedFile.name || "photo.jpg");
      metadata.upload_stage = "fetch";
      const startedAt = performance.now();
      const timeoutMs = Number(options.timeoutMs || 90000);
      const response = typeof options.onProgress === "function" && typeof window.XMLHttpRequest === "function"
        ? await uploadWithProgress(path, body, { timeoutMs, onProgress: options.onProgress }, metadata)
        : await request(path, { method: "POST", body, timeoutMs, retries: 0 });
      metadata.duration_ms = Math.round(performance.now() - startedAt);
      return response;
    } catch (error) {
      throw uploadError(error, metadata, kind);
    }
  }

  window.AutoFlowApi = Object.freeze({ request, resource, upload, ApiError, baseUrl: API_BASE });
})();
