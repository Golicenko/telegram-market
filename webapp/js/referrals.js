(function () {
  "use strict";
  const number = value => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value);
  const friends = value => value % 100 >= 11 && value % 100 <= 14 ? "друзей" : value % 10 === 1 ? "друг" : [2, 3, 4].includes(value % 10) ? "друга" : "друзей";

  async function copyFullUrl(value) {
    if (navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(value); return; }
      catch { /* Some Telegram WebViews deny Clipboard API; try the selection fallback. */ }
    }
    const field = document.createElement("textarea");
    field.value = value;
    field.readOnly = true;
    field.style.cssText = "position:fixed;left:0;top:0;opacity:0;font-size:16px";
    const focused = document.activeElement;
    document.body.append(field);
    try {
      field.focus({ preventScroll: true }); field.select(); field.setSelectionRange(0, value.length);
      if (!document.execCommand("copy")) throw new Error("Clipboard unavailable");
    } finally {
      field.remove();
      if (focused instanceof HTMLElement) focused.focus({ preventScroll: true });
    }
  }

  /** @param {ReferralPageOptions} options */
  function create({ api, notify, refreshWallet }) {
    const get = id => document.getElementById(id);
    const root = document.querySelector('[data-view="more"]');
    const share = /** @type {HTMLButtonElement} */ (get("referralShare"));
    const copies = /** @type {HTMLButtonElement[]} */ ([...root.querySelectorAll("[data-copy-referral]")]);
    /** @type {ReferralSummary | null} */
    let data = null;
    let active = false, loading = false, sharing = false, timer = null;

    function renderButtons() {
      copies.forEach(button => { button.disabled = !data?.canInvite; });
      share.disabled = !data?.canInvite || sharing;
      share.textContent = sharing ? "Подготовка…" : data && !data.canInvite ? "Лимит приглашений достигнут" : "Переслать";
    }

    function render(previousCount) {
      get("referralContent").hidden = false;
      get("referralPercent").textContent = number(data.commissionPercent) + "%";
      const count = get("referralCount");
      count.textContent = number(data.referralCount);
      if (previousCount !== null && data.referralCount > previousCount) {
        count.classList.remove("referral-count-up");
        void count.offsetWidth;
        count.classList.add("referral-count-up");
      }
      get("referralMilestones").replaceChildren(...data.milestones.map(milestone => {
        const card = document.createElement("div");
        card.className = "referral-milestone" + (milestone.completed ? " is-complete" : "");
        const title = document.createElement("span");
        title.textContent = (milestone.completed ? "✓ " : "") + number(milestone.count) + " " + friends(milestone.count);
        const amount = document.createElement("strong"); amount.textContent = number(milestone.reward) + " AF";
        const status = document.createElement("small"); status.textContent = milestone.completed ? "Получено" : "Награда";
        card.append(title, amount, status);
        return card;
      }));
      get("referralLimit").hidden = data.canInvite;
      const urlField = /** @type {HTMLInputElement} */ (get("referralUrl"));
      urlField.value = data.referralUrl;
      renderButtons();
    }

    async function load() {
      if (!active || loading || document.hidden) return;
      loading = true;
      get("referralRetry").hidden = true;
      if (!data) get("referralStatus").textContent = "Загрузка программы…";
      try {
        const next = await api.request("/referrals");
        if (!next || !Array.isArray(next.milestones) || typeof next.canInvite !== "boolean" || !next.referralUrl) {
          throw new Error("Invalid referral response");
        }
        const previousCount = data?.referralCount ?? null;
        data = next; render(previousCount);
        // Display only the server wallet; never add reward amounts locally.
        await refreshWallet();
        get("referralStatus").textContent = "";
      } catch {
        get("referralStatus").textContent = data ? "Не удалось обновить данные. Попробуйте снова." : "Не удалось загрузить реферальную программу.";
        get("referralRetry").hidden = false;
      } finally {
        loading = false;
      }
    }

    copies.forEach(button => button.addEventListener("click", async () => {
      if (!data?.canInvite) return;
      try { await copyFullUrl(data.referralUrl); notify("Ссылка скопирована"); }
      catch { notify("Не удалось скопировать ссылку. Выделите её и скопируйте вручную."); }
    }));
    share.addEventListener("click", async () => {
      if (!data?.canInvite || sharing) return;
      sharing = true; renderButtons();
      const telegram = window.Telegram?.WebApp;
      try {
        const supported = typeof telegram?.shareMessage === "function" &&
          (typeof telegram.isVersionAtLeast !== "function" || telegram.isVersionAtLeast("8.0"));
        if (supported) {
          const prepared = await api.request("/referrals/share-message", { method: "POST", retries: 0, timeoutMs: 45000 });
          if (!prepared.preparedMessageId) throw new Error("Missing prepared message");
          // A false callback means the user cancelled; do not send again via fallback.
          await new Promise((resolve, reject) => {
            try { telegram.shareMessage(prepared.preparedMessageId, resolve); } catch (error) { reject(error); }
          });
        } else {
          // share/url cannot attach a photo or a real inline keyboard.
          // Never silently replace the requested photo invitation with plain text.
          notify("Обновите Telegram, чтобы переслать приглашение с фото.");
        }
      } catch (error) {
        notify(error.status === 409 ? "Лимит приглашений достигнут" : error.status === 429 ?
          "Пересылка уже готовится. Повторите через несколько секунд." : "Не удалось открыть пересылку. Попробуйте ещё раз.");
        if (error.status === 409) { data.canInvite = false; render(data.referralCount); }
      } finally {
        sharing = false; renderButtons();
      }
    });
    get("referralRetry").addEventListener("click", load);
    document.addEventListener("visibilitychange", () => { if (active && !document.hidden) void load(); });
    renderButtons();
    return {
      setActive(value) {
        active = value;
        window.clearInterval(timer); timer = null;
        if (active) { void load(); timer = window.setInterval(load, 30000); }
      },
    };
  }
  window.AutoFlowReferrals = { create };
})();
