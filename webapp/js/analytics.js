(function (root) {
  "use strict";
  const allowed = new Set(["miniapp_opened", "market_viewed", "listing_viewed", "order_checkout_started", "topup_screen_opened", "topup_failure", "training_list_view", "training_product_view", "training_buy_click", "training_checkout_started", "training_support_opened", "support_opened"]);
  function create(api, context) {
    const uuid = () => {
      if (root.crypto?.randomUUID) return root.crypto.randomUUID();
      if (!root.crypto?.getRandomValues) return null;
      const bytes = root.crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
      const hex = [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
      return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
    };
    const session = uuid(), last = new Map(); let sent = 0, pausedUntil = 0, windowStart = Date.now();
    return function track(event, entity = null, reason = null) {
      const current = context();
      if (Date.now() - windowStart >= 3600000) { sent = 0; windowStart = Date.now(); for (const key of last.keys()) if (!key.startsWith("miniapp_opened:")) last.delete(key); }
      if (!session || !allowed.has(event) || !current.ready || current.staff || document.visibilityState === "hidden" || Date.now() < pausedUntil || sent >= 120) return;
      const key = `${event}:${entity}:${reason}`, now = Date.now();
      if (last.has(key) && (event === "miniapp_opened" || now - last.get(key) < 30000)) return;
      const platforms = ["ios", "android", "tdesktop", "macos", "web"];
      const platform = platforms.includes(current.platform) ? current.platform : String(current.platform || "").startsWith("web") ? "web" : "unknown";
      last.set(key, now); sent += 1;
      // Best effort: never delay checkout, retry payments, show a toast or queue private text.
      Promise.resolve().then(() => api.request("/analytics/events", { method: "POST", retries: 0, timeoutMs: 3000,
        body: JSON.stringify({ event_id: uuid(), session_id: session, event_name: event, entity_id: entity, reason, platform,
          source: ["listing", "training", "profile", "deeplink"].includes(current.source) ? current.source : "navigation" })
      })).catch(() => { pausedUntil = Date.now() + 60000; });
    };
  }
  root.AutoFlowAnalytics = { create };
})(window);
