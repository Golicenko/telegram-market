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
        const error = rawError instanceof ApiError
          ? rawError
          : new ApiError(0, timedOut ? "Сервер не ответил вовремя" : "Нет соединения с сервером", {
              endpoint: safeEndpoint(url),
              errorType: timedOut ? "timeout" : "network",
              cause: rawError,
              autoflowErrorId: errorId,
            });
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

  function uploadError(error) {
    const metadata = { endpoint: error?.endpoint || "/api/uploads", errorType: error?.errorType || "upload", cause: error };
    if (error?.errorType === "timeout") return new ApiError(0, "Загрузка фотографии заняла слишком много времени. Попробуйте снова.", metadata);
    if (error?.errorType === "network") return new ApiError(0, "Нет соединения с сервером. Проверьте интернет.", metadata);
    const messages = {
      401: "Сессия Telegram истекла. Откройте Market заново.",
      413: "Фотография слишком большая.",
      415: "Формат фотографии не поддерживается.",
      422: "Не удалось обработать фотографию.",
      429: "Слишком много запросов. Попробуйте через несколько секунд.",
      500: "Ошибка сервера при обработке фотографии.",
    };
    return new ApiError(error?.status || 0, messages[error?.status] || error?.message || "Не удалось загрузить фотографию.", metadata);
  }

  function canvasBlob(canvas, type, quality) {
    if (typeof canvas.toBlob !== "function") return Promise.resolve(null);
    return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
  }

  async function prepareImage(file) {
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
      if (!width || !height) return file;
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
      return file;
    } finally {
      bitmap?.close?.();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    }
  }

  async function upload(file, path = "/uploads") {
    if (!file?.size) throw new ApiError(422, "Не удалось обработать фотографию.", { errorType: "upload" });
    if (file.size > 30 * 1024 * 1024) throw new ApiError(413, "Фотография слишком большая.", { errorType: "upload" });
    const preparedFile = await prepareImage(file);
    const body = new FormData();
    body.append("file", preparedFile, preparedFile.name || "photo.jpg");
    try {
      return await request(path, { method: "POST", body, timeoutMs: 60000, retries: 0 });
    } catch (error) {
      throw uploadError(error);
    }
  }

  window.AutoFlowApi = Object.freeze({ request, resource, upload, ApiError, baseUrl: API_BASE });
})();
