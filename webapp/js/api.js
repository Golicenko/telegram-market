(function () {
  "use strict";

  const DEFAULT_TIMEOUT_MS = 12000;
  const DEFAULT_RETRY_DELAY_MS = 650;
  const rawApiBase = window.AUTO_FLOW_API_BASE || `${window.location.origin}/api`;
  const API_BASE = rawApiBase.replace(/\/$/, "");

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
        const rawField = Array.isArray(item?.loc) ? item.loc.filter((part) => !["body", "query", "path"].includes(String(part))).at(-1) : null;
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
    return error?.errorType === "timeout" || error?.errorType === "network" || error?.errorType === "invalid_json" || Number(error?.status || 0) >= 500;
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
    if (fetchOptions.body && !(fetchOptions.body instanceof FormData)) headers["Content-Type"] = "application/json";

    for (let attempt = 1; attempt <= maxRetries + 1; attempt += 1) {
      const controller = new AbortController();
      let timedOut = false;
      const startedAt = performance.now();
      const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, Math.max(1, timeoutMs));
      const externalSignal = fetchOptions.signal;
      const forwardAbort = () => controller.abort();
      externalSignal?.addEventListener?.("abort", forwardAbort, { once: true });
      try {
        const response = await fetch(url, { ...fetchOptions, headers, signal: controller.signal });
        if (!response.ok) {
          let detail = response.statusText || "Ошибка запроса";
          try {
            const payload = await response.json();
            detail = payload.detail || payload;
          } catch (_error) { /* Keep the HTTP status text. */ }
          throw new ApiError(response.status, detail, { endpoint: safeEndpoint(url), errorType: "http" });
        }
        if (response.status === 204) return null;
        try { return await response.json(); }
        catch (error) { throw new ApiError(502, "Сервер вернул некорректный ответ", { endpoint: safeEndpoint(url), errorType: "invalid_json", cause: error }); }
      } catch (rawError) {
        const durationMs = performance.now() - startedAt;
        const error = rawError instanceof ApiError
          ? rawError
          : new ApiError(0, timedOut ? "Сервер не ответил вовремя" : "Нет соединения с сервером", {
              endpoint: safeEndpoint(url),
              errorType: timedOut ? "timeout" : "network",
              cause: rawError,
            });
        diagnostic(error, url, durationMs, attempt);
        if (attempt > maxRetries || !shouldRetry(error) || externalSignal?.aborted) throw error;
        await delay(retryDelayMs * attempt);
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

  async function upload(file, path = "/uploads") {
    const body = new FormData();
    body.append("file", file);
    return request(path, { method: "POST", body, timeoutMs: 60000, retries: 1 });
  }

  window.AutoFlowApi = Object.freeze({ request, resource, upload, ApiError, baseUrl: API_BASE });
})();
