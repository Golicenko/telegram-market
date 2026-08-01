(function () {
  "use strict";

  const API_BASE = window.AUTO_FLOW_API_BASE || `${window.location.origin}/api`;

  class ApiError extends Error {
    constructor(status, detail) {
      super(typeof detail === "string" ? detail : "Ошибка запроса");
      this.name = "ApiError";
      this.status = status;
      this.detail = detail;
    }
  }

  function authHeaders() {
    const headers = { Accept: "application/json" };
    const initData = window.Telegram?.WebApp?.initData;
    if (initData) headers["X-Telegram-Init-Data"] = initData;
    return headers;
  }

  async function request(path, options = {}) {
    const headers = { ...authHeaders(), ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const payload = await response.json();
        detail = payload.detail || payload;
      } catch (_error) {
        // Keep the HTTP status text.
      }
      throw new ApiError(response.status, detail);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  async function upload(file, path = "/uploads") {
    const body = new FormData();
    body.append("file", file);
    return request(path, { method: "POST", body });
  }

  window.AutoFlowApi = Object.freeze({ request, upload, ApiError, baseUrl: API_BASE });
})();
