(function (root) {
  "use strict";
  function create({ api, openDialog, notify, requestId, formatDate, refresh }) {
    let dialog = null, submitting = false;
    const requests = new Map();
    const node = (tag, text, className) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (className) el.className = className; return el; };
    function choose(options, initial = false) {
      if (dialog) return Promise.resolve("cancel");
      return new Promise(resolve => {
        const modal = node("dialog", null, "modal vip-pin-choice"); dialog = modal;
        modal.setAttribute("aria-label", "Закрепить объявление");
        modal.append(node("h2", "Закрепить объявление"), node("p", "Используйте закрепление из действующего VIP. AF Coins не списываются."));
        let settled = false;
        const finish = value => { if (settled) return; settled = true; modal.close(); modal.remove(); dialog = null; resolve(value); };
        for (const option of options) {
          if (!(option.remaining > 0)) continue;
          const button = node("button", `Использовать VIP: ${option.duration_hours === 72 ? "3 дня" : "1 день"} · ${option.remaining} из ${option.total} · 0 AF`, "publish-button"); button.type = "button";
          button.onclick = () => finish(option.duration_hours); modal.append(button);
        }
        const paid = node("button", "Обычное платное закрепление", "ghost-button"); paid.type = "button"; paid.onclick = () => finish("paid"); modal.append(paid);
        const cancel = node("button", initial ? "Опубликовать без закрепления" : "Отмена", "ghost-button"); cancel.type = "button"; cancel.onclick = () => finish("cancel"); modal.append(cancel);
        modal.addEventListener("cancel", event => { event.preventDefault(); finish("cancel"); });
        document.body.append(modal); openDialog(modal); cancel.focus();
      });
    }
    async function chooseInitial() {
      // No financial cache: privileges are revalidated again during activation.
      const result = await api.request("/seller-vip");
      const sub = result.active_subscription;
      if (!sub) return null;
      const options = [{ duration_hours: 72, remaining: sub.pins_72h_remaining, total: sub.pins_72h_total }, { duration_hours: 24, remaining: sub.pins_24h_remaining, total: sub.pins_24h_total }].filter(option => option.remaining > 0);
      return options.length ? choose(options, true) : null;
    }
    async function use(listingId, hours) {
      const key = `${listingId}:${hours}`;
      if (!requests.has(key)) { if (requests.size >= 30) requests.delete(requests.keys().next().value); requests.set(key, requestId()); }
      const result = await api.request("/seller-vip/pins", { method: "POST", retries: 0, body: JSON.stringify({ listing_id: listingId, duration_hours: hours, request_id: requests.get(key) }) });
      requests.delete(key); // Retain only ambiguous failures for a safe same-key retry.
      return result;
    }
    async function existing(listingId) {
      if (dialog || submitting) return true;
      submitting = true;
      try {
        const quote = await api.request(`/seller-vip/pins/${encodeURIComponent(listingId)}/quote`);
        if (quote.already_pinned) { notify(`Объявление уже закреплено до ${formatDate(quote.pinned_until)}`); return true; }
        const options = (quote.options || []).filter(option => option.remaining > 0);
        if (!options.length) return false;
        const choice = await choose(options);
        if (choice === "paid") return false;
        if (choice === "cancel") return true;
        const result = await use(listingId, choice);
        await refresh(); notify(`VIP-закрепление активно до ${formatDate(result.pinned_until)}`);
        return true;
      } catch (error) { notify(error.message || "Не удалось проверить VIP-закрепления. Попробуйте ещё раз."); return true; }
      finally { submitting = false; }
    }
    function dismiss() { if (!dialog) return false; dialog.dispatchEvent(new Event("cancel", { cancelable: true })); return true; }
    return { chooseInitial, use, existing, dismiss };
  }
  root.AutoFlowVipPinning = { create };
})(window);
