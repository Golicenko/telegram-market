(function () {
  "use strict";
  const number = value => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value);
  const friends = value => value % 100 >= 11 && value % 100 <= 14 ? "друзей" : value % 10 === 1 ? "друг" : [2, 3, 4].includes(value % 10) ? "друга" : "друзей";
  const inviteFriends = value => value % 10 === 1 && value % 100 !== 11 ? "друга" : "друзей";

  function rewardPresentation(milestone, invited) {
    const remaining = Math.max(0, milestone.count - invited), completed = milestone.completed === true;
    return {
      completed, remaining, progress: Math.min(invited, milestone.count), maximum: milestone.count,
      title: completed ? "Награда получена" : `Награда ${number(milestone.reward)} AF`,
      description: completed ? `${number(milestone.reward)} AF уже начислены на ваш баланс.`
        : remaining ? `Чтобы получить эту награду, пригласите ещё ${number(remaining)} ${inviteFriends(remaining)}.`
          : "Условие выполнено. Ожидаем подтверждения начисления награды.",
      progressLabel: `Ваш прогресс: ${number(Math.min(invited, milestone.count))} из ${number(milestone.count)}`,
      status: completed ? "Награда получена" : remaining ? "Начисление происходит автоматически по правилам программы" : "Начисление ещё не подтверждено",
    };
  }

  async function copyFullUrl(value) {
    if (navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(value); return; }
      catch { /* Some Telegram WebViews deny Clipboard API; try selection. */ }
    }
    const field = document.createElement("textarea");
    field.value = value; field.readOnly = true;
    field.style.cssText = "position:fixed;left:0;top:0;opacity:0;font-size:16px";
    const focused = document.activeElement; document.body.append(field);
    try {
      field.focus({ preventScroll: true }); field.select(); field.setSelectionRange(0, value.length);
      if (!document.execCommand("copy")) throw new Error("Clipboard unavailable");
    } finally {
      field.remove();
      if (focused instanceof HTMLElement && focused.isConnected) focused.focus({ preventScroll: true });
    }
  }

  function validSummary(value) {
    return value && Number.isSafeInteger(value.referralCount) && value.referralCount >= 0
      && Number.isFinite(value.commissionPercent) && value.commissionPercent >= 0
      && Number.isSafeInteger(value.referralLimit) && value.referralLimit >= 0
      && typeof value.canInvite === "boolean" && typeof value.referralUrl === "string" && value.referralUrl.length > 0
      && Array.isArray(value.milestones) && value.milestones.length > 0
      && value.milestones.every(item => Number.isSafeInteger(item.count) && item.count > 0 && Number.isFinite(item.reward)
        && item.reward >= 0 && typeof item.completed === "boolean")
      && new Set(value.milestones.map(item => item.count)).size === value.milestones.length;
  }

  /** @param {ReferralPageOptions} options */
  function create({ api, notify, refreshWallet }) {
    const get = id => document.getElementById(id);
    const root = document.querySelector('[data-view="more"]');
    const share = /** @type {HTMLButtonElement} */ (get("referralShare")), shareLabel = get("referralShareLabel");
    const copies = /** @type {HTMLButtonElement[]} */ ([...root.querySelectorAll("[data-copy-referral]")]);
    const milestonesRoot = get("referralMilestones"), modal = /** @type {HTMLDialogElement} */ (get("referralRewardModal"));
    const cards = new Map(), cardStates = new Map(), completionTimers = new Map();
    /** @type {ReferralSummary | null} */
    let data = null;
    let active = false, sharing = false, copying = false, timer = null, loadPromise = null, loadedAt = 0;
    let walletVersion = 0, refreshedWalletVersion = 0, walletPromise = null;
    let copyTimer = null, closeTimer = null, introTimer = null, progressFrame = null, openedCount = null, returnFocus = null, scrollLock = null;
    let firstOpened = false;
    let backgroundStates = [];
    const freshFor = 15000;
    const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
    const setText = (element, value) => { if (element.textContent !== value) element.textContent = value; };
    const telegramBack = method => { try { window.Telegram?.WebApp?.BackButton?.[method]?.(); } catch { /* Older SDKs may not expose BackButton. */ } };

    function renderButtons() {
      copies.forEach(button => { button.disabled = !data?.canInvite || copying; });
      share.disabled = !data?.canInvite || sharing;
      share.classList.toggle("is-loading", sharing); share.setAttribute("aria-busy", String(sharing));
      setText(shareLabel, sharing ? "Подготовка…" : data && !data.canInvite ? "Лимит приглашений достигнут" : "Переслать");
    }

    function createMilestone(count) {
      const card = document.createElement("button");
      card.type = "button"; card.className = "referral-milestone"; card.dataset.referralMilestone = String(count);
      card.setAttribute("aria-haspopup", "dialog"); card.setAttribute("aria-controls", "referralRewardModal");
      const content = document.createElement("span"); content.className = "referral-milestone__content";
      const icon = document.createElement("span"); icon.className = "referral-milestone__icon"; icon.setAttribute("aria-hidden", "true");
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", "0 0 40 36");
      const shape = document.createElementNS("http://www.w3.org/2000/svg", "path");
      shape.setAttribute("d", "M20 3a6 6 0 1 0 0 12 6 6 0 0 0 0-12ZM8 9a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm24 0a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM9 30v-5c0-4 5-7 11-7s11 3 11 7v5H9ZM1 28v-5c0-3 3-5 7-5l3 1c-3 2-5 4-5 7v2H1Zm33 0v-2c0-3-2-5-5-7l3-1c4 0 7 2 7 5v5h-5Z");
      svg.append(shape); icon.append(svg);
      const title = document.createElement("span"); title.className = "referral-milestone__title";
      const amount = document.createElement("strong"); amount.className = "referral-milestone__amount";
      const status = document.createElement("small"); status.className = "referral-milestone__status";
      const arrow = document.createElement("span"); arrow.className = "referral-milestone__arrow"; arrow.textContent = "›"; arrow.setAttribute("aria-hidden", "true");
      content.append(icon, title, amount, status, arrow);
      const overlay = document.createElement("span"); overlay.className = "referral-milestone__completed"; overlay.setAttribute("aria-hidden", "true");
      const check = document.createElement("span"); check.className = "referral-milestone__check"; check.textContent = "✓";
      const received = document.createElement("small"); received.textContent = "Получено"; overlay.append(check, received);
      card.append(content, overlay); cards.set(count, card); return card;
    }

    function render(previousCount = null) {
      if (!data || !active || document.hidden) return;
      get("referralContent").hidden = false; setText(get("referralPercent"), number(data.commissionPercent) + "%");
      const count = get("referralCount"); setText(count, number(data.referralCount));
      if (previousCount !== null && data.referralCount > previousCount && !reducedMotion()) {
        count.classList.remove("referral-count-up"); void count.offsetWidth; count.classList.add("referral-count-up");
      }
      const nextCards = data.milestones.map(milestone => {
        const card = cards.get(milestone.count) || createMilestone(milestone.count);
        const previous = cardStates.get(milestone.count), completed = milestone.completed === true;
        setText(card.querySelector(".referral-milestone__title"), `${number(milestone.count)} ${friends(milestone.count)}`);
        setText(card.querySelector(".referral-milestone__amount"), `${number(milestone.reward)} AF`);
        setText(card.querySelector(".referral-milestone__status"), completed ? "Получено" : "Награда");
        card.classList.toggle("is-complete", completed);
        card.setAttribute("aria-label", `${number(milestone.count)} ${friends(milestone.count)} — ${number(milestone.reward)} AF. ${completed ? "Награда получена" : "Подробнее о награде"}`);
        if (previous === false && completed && !reducedMotion()) {
          window.clearTimeout(completionTimers.get(milestone.count));
          card.classList.remove("is-newly-complete"); void card.offsetWidth; card.classList.add("is-newly-complete");
          completionTimers.set(milestone.count, window.setTimeout(() => { card.classList.remove("is-newly-complete"); completionTimers.delete(milestone.count); }, 500));
        }
        cardStates.set(milestone.count, completed); return card;
      });
      if (milestonesRoot.children.length !== nextCards.length || nextCards.some((card, index) => milestonesRoot.children[index] !== card)) milestonesRoot.replaceChildren(...nextCards);
      for (const [countValue, card] of cards) {
        if (nextCards.includes(card)) continue;
        window.clearTimeout(completionTimers.get(countValue)); completionTimers.delete(countValue); cards.delete(countValue); cardStates.delete(countValue);
      }
      get("referralLimit").hidden = data.canInvite;
      const url = /** @type {HTMLInputElement} */ (get("referralUrl"));
      if (url.value !== data.referralUrl) url.value = data.referralUrl;
      renderButtons(); if (modal.open && openedCount !== null) renderReward(false);
    }

    function lockBackground() {
      if (scrollLock) return;
      const body = document.body;
      scrollLock = { overflow: body.style.overflow, position: body.style.position, top: body.style.top, width: body.style.width, y: window.scrollY };
      body.style.overflow = "hidden"; body.style.position = "fixed"; body.style.top = `-${scrollLock.y}px`; body.style.width = "100%";
      body.classList.add("referral-reward-open");
      for (let node = modal; node?.parentElement; node = node.parentElement) {
        for (const sibling of node.parentElement.children) {
          if (sibling === node) continue;
          backgroundStates.push([sibling, sibling.inert]); sibling.inert = true;
        }
        if (node.parentElement === body) break;
      }
    }

    function releaseBackground(restoreFocus) {
      const wasOpen = Boolean(scrollLock || openedCount !== null);
      if (progressFrame !== null) window.cancelAnimationFrame(progressFrame); progressFrame = null;
      for (const [node, inert] of backgroundStates) node.inert = inert; backgroundStates = [];
      if (scrollLock) {
        const previous = scrollLock; scrollLock = null;
        Object.assign(document.body.style, { overflow: previous.overflow, position: previous.position, top: previous.top, width: previous.width });
        document.body.classList.remove("referral-reward-open"); window.scrollTo({ top: previous.y, behavior: "instant" });
      }
      if (restoreFocus && active && returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
      returnFocus = null; openedCount = null;
      if (wasOpen) telegramBack("hide");
    }

    function closeReward(immediate = false, restoreFocus = true) {
      if (!modal.open && !scrollLock) return false;
      window.clearTimeout(closeTimer); closeTimer = null;
      const finish = () => {
        closeTimer = null;
        if (typeof modal.close === "function" && modal.open) modal.close(); else modal.removeAttribute("open");
        modal.classList.remove("is-closing"); releaseBackground(restoreFocus);
      };
      if (immediate || reducedMotion()) finish(); else { modal.classList.add("is-closing"); closeTimer = window.setTimeout(finish, 200); }
      return true;
    }

    function renderReward(animate) {
      const milestone = data?.milestones.find(item => item.count === openedCount);
      if (!milestone) { closeReward(true); return; }
      const presentation = rewardPresentation(milestone, data.referralCount);
      setText(get("referralRewardTitle"), presentation.title); setText(get("referralRewardDescription"), presentation.description);
      setText(get("referralRewardProgressLabel"), presentation.progressLabel); setText(get("referralRewardStatus"), presentation.status);
      modal.classList.toggle("is-complete", presentation.completed); modal.classList.toggle("is-pending", !presentation.completed && presentation.remaining === 0);
      const progress = /** @type {HTMLProgressElement} */ (get("referralRewardProgress"));
      progress.max = presentation.maximum; progress.setAttribute("aria-label", presentation.progressLabel);
      if (progressFrame !== null) window.cancelAnimationFrame(progressFrame);
      if (animate && !reducedMotion()) {
        progress.value = 0;
        progressFrame = window.requestAnimationFrame(() => { progressFrame = null; if (modal.open) progress.value = presentation.progress; });
      } else progress.value = presentation.progress;
    }

    function openReward(count, trigger) {
      if (!active || !data?.milestones.some(item => item.count === count)) return;
      window.clearTimeout(closeTimer); closeTimer = null; modal.classList.remove("is-closing");
      openedCount = count; returnFocus = trigger; renderReward(true); lockBackground();
      if (!modal.open) { if (typeof modal.showModal === "function") modal.showModal(); else modal.setAttribute("open", ""); }
      telegramBack("show");
      modal.querySelector("[data-close-referral-reward]")?.focus({ preventScroll: true });
    }

    function startPolling() {
      window.clearInterval(timer); timer = null;
      if (active && !document.hidden) timer = window.setInterval(() => void load(true), 30000);
    }

    function refreshPendingWallet() {
      if (walletPromise) return walletPromise;
      if (walletVersion === refreshedWalletVersion || !active || document.hidden) return Promise.resolve();
      const version = walletVersion;
      walletPromise = Promise.resolve().then(refreshWallet).then(() => { refreshedWalletVersion = version; }).finally(() => { walletPromise = null; });
      return walletPromise;
    }

    function load(force = false) {
      if (!active || document.hidden) return Promise.resolve();
      if (loadPromise) return loadPromise;
      if (!force && data && loadedAt && Date.now() - loadedAt < freshFor && walletVersion === refreshedWalletVersion) { render(); return Promise.resolve(); }
      if (!force && data && loadedAt && Date.now() - loadedAt < freshFor) {
        render();
        return refreshPendingWallet().catch(() => { if (active) { loadedAt = 0; get("referralRetry").hidden = false; get("referralStatus").textContent = "Не удалось обновить баланс. Попробуйте снова."; } });
      }
      get("referralRetry").hidden = true; if (!data) get("referralStatus").textContent = "Загрузка программы…";
      loadPromise = (async () => {
        try {
          const next = await api.request("/referrals"); if (!validSummary(next)) throw new Error("Invalid referral response");
          const previousCount = data?.referralCount ?? null;
          // A top-up commission can arrive without any count/milestone change.
          // Each actual summary refresh also refreshes the authoritative wallet;
          // cached tab reopens remain request-free.
          data = next; loadedAt = Date.now(); walletVersion += 1;
          if (!active || document.hidden) return;
          render(previousCount); get("referralStatus").textContent = "";
          await refreshPendingWallet(); // Never add reward amounts locally.
        } catch {
          loadedAt = 0; if (!active || document.hidden) return;
          get("referralStatus").textContent = data ? "Не удалось обновить данные. Попробуйте снова." : "Не удалось загрузить реферальную программу.";
          get("referralRetry").hidden = false;
        }
      })().finally(() => { loadPromise = null; });
      return loadPromise;
    }

    milestonesRoot.addEventListener("click", event => {
      const card = event.target.closest("[data-referral-milestone]");
      if (card && milestonesRoot.contains(card)) openReward(Number(card.dataset.referralMilestone), card);
    });
    modal.querySelectorAll("[data-close-referral-reward]").forEach(button => button.addEventListener("click", () => closeReward()));
    modal.addEventListener("cancel", event => { event.preventDefault(); closeReward(); });
    modal.addEventListener("click", event => {
      if (event.target !== modal) return;
      const rect = modal.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeReward();
    });
    document.addEventListener("wheel", event => {
      if (!modal.open || !scrollLock || event.ctrlKey || event.metaKey) return;
      // A wheel over a short modal/backdrop must not queue compositor scrolling
      // on the document, which can otherwise land after the body is unlocked.
      const rect = modal.getBoundingClientRect();
      const outside = !modal.contains(event.target) || event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom;
      const cannotScroll = modal.scrollHeight <= modal.clientHeight
        || event.deltaY < 0 && modal.scrollTop <= 0
        || event.deltaY > 0 && Math.ceil(modal.scrollTop + modal.clientHeight) >= modal.scrollHeight;
      if (outside || cannotScroll) event.preventDefault();
    }, { passive: false, capture: true });
    document.addEventListener("touchmove", event => {
      // Keep normal scrolling inside long modal content and preserve two-finger
      // zoom. Only an outside single-finger gesture is blocked while open.
      if (!modal.open || !scrollLock || event.touches.length !== 1) return;
      const touch = event.touches[0], rect = modal.getBoundingClientRect();
      if (!modal.contains(event.target) || touch.clientX < rect.left || touch.clientX > rect.right || touch.clientY < rect.top || touch.clientY > rect.bottom) event.preventDefault();
    }, { passive: false, capture: true });
    modal.addEventListener("close", () => {
      // close is queued by the native dialog; an immediate re-open can precede
      // that old event. It must not unlock or clear the newly opened reward.
      if (modal.open) return;
      window.clearTimeout(closeTimer); closeTimer = null; modal.classList.remove("is-closing"); releaseBackground(active);
    });
    modal.addEventListener("keydown", event => {
      if (event.key !== "Tab") return;
      const buttons = [...modal.querySelectorAll("button:not([disabled])")], first = buttons[0], last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    });

    copies.forEach(button => button.addEventListener("click", async () => {
      if (!data?.canInvite || copying) return;
      window.clearTimeout(copyTimer); copyTimer = null; copies.forEach(copy => copy.classList.remove("is-copied"));
      copying = true; renderButtons();
      try {
        await copyFullUrl(data.referralUrl);
        if (!active || document.hidden) return;
        notify("Ссылка скопирована");
        window.clearTimeout(copyTimer); copies.forEach(copy => copy.classList.add("is-copied"));
        copyTimer = window.setTimeout(() => { copies.forEach(copy => copy.classList.remove("is-copied")); copyTimer = null; }, 1600);
      } catch { if (active && !document.hidden) notify("Не удалось скопировать ссылку. Выделите её и скопируйте вручную."); }
      finally { copying = false; renderButtons(); }
    }));
    share.addEventListener("click", async () => {
      if (!data?.canInvite || sharing) return;
      sharing = true; renderButtons(); const telegram = window.Telegram?.WebApp;
      try {
        const supported = typeof telegram?.shareMessage === "function" && (typeof telegram.isVersionAtLeast !== "function" || telegram.isVersionAtLeast("8.0"));
        if (supported) {
          const prepared = await api.request("/referrals/share-message", { method: "POST", retries: 0, timeoutMs: 45000 });
          if (!prepared.preparedMessageId) throw new Error("Missing prepared message");
          if (!active || document.hidden) return;
          await new Promise((resolve, reject) => {
            try { telegram.shareMessage(prepared.preparedMessageId, resolve); } catch (error) { reject(error); }
          });
        } else notify("Обновите Telegram, чтобы переслать приглашение с фото.");
      } catch (error) {
        if (active) notify(error.status === 409 ? "Лимит приглашений достигнут" : error.status === 429 ? "Пересылка уже готовится. Повторите через несколько секунд." : "Не удалось открыть пересылку. Попробуйте ещё раз.");
        if (error.status === 409 && data) { data.canInvite = false; render(data.referralCount); }
      } finally { sharing = false; renderButtons(); }
    });
    get("referralRetry").addEventListener("click", () => void load(true));
    document.addEventListener("visibilitychange", () => {
      startPolling(); if (active && !document.hidden) void load(); else if (document.hidden) closeReward(true, false);
    });
    renderButtons();
    return {
      setActive(value) {
        if (active === value) return;
        active = value; startPolling();
        if (active) {
          if (!firstOpened) {
            firstOpened = true; root.classList.add("is-first-open");
            introTimer = window.setTimeout(() => { root.classList.remove("is-first-open"); introTimer = null; }, 400);
          }
          if (data) render(); void load();
        }
        else {
          window.clearTimeout(introTimer); introTimer = null; root.classList.remove("is-first-open");
          closeReward(true, false); window.clearTimeout(copyTimer); copyTimer = null; copies.forEach(copy => copy.classList.remove("is-copied"));
          for (const [count, animationTimer] of completionTimers) { window.clearTimeout(animationTimer); cards.get(count)?.classList.remove("is-newly-complete"); }
          completionTimers.clear();
        }
      },
      dismiss() { return closeReward(); },
    };
  }
  window.AutoFlowReferrals = { create };
})();
