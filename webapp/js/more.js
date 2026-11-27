(function (root) {
  "use strict";
  const number = value => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value));
  const node = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; };
  const paths = {
    crown: "m3 7 5 4 4-8 4 8 5-4-2 12H5L3 7Zm3 15h12",
    pin: "m15 3 6 6-3 1-4 5-1 4-3-3-6 6 5-7-3-3 4-1 5-4V3Z",
    car: "m4 10 2-6h12l2 6M3 10h18v9H3v-9Zm3 4h1m10 0h1M6 19v2m12-2v2",
    account: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-3c0-8 16-8 16 0v3H4Z",
    badge: "m12 2 3 2 4 1 1 4 2 3-2 3-1 4-4 1-3 2-3-2-4-1-1-4-2-3 2-3 1-4 4-1 3-2Zm-5 10 3 3 7-7",
    bolt: "m13 2-9 12h7l-1 8 10-13h-7l0-7Z",
    shield: "m12 2 9 4v6c0 6-9 10-9 10S3 18 3 12V6l9-4Zm-5 10 3 3 7-7",
    coin: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 5v14m4-11c-6-3-9 2-4 4s3 5-4 4",
    support: "M3 13v-2a9 9 0 0 1 18 0v2M3 12h4v8H3v-8Zm14 0h4v8h-4v-8Zm4 8c0 3-9 2-9 2",
    refresh: "M20 7A9 9 0 1 0 21 15M20 2v6h-6",
    community: "M15 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM5 21v-5c0-7 14-7 14 0v5H5ZM2 9a3 3 0 0 1 3 5M22 9a3 3 0 0 0-3 5",
    info: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 10v7m0-11v1",
  };
  function icon(kind, cls = "") {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("class", `more-icon ${cls}`);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path"); path.setAttribute("d", paths[kind] || paths.info); svg.append(path); return svg;
  }
  function button(text, action, cls = "ghost-button") { const result = node("button", text, cls); result.type = "button"; result.onclick = action; return result; }
  function openExternal(url) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "https:") return false;
      if (parsed.hostname === "t.me" && typeof root.Telegram?.WebApp?.openTelegramLink === "function") { root.Telegram.WebApp.openTelegramLink(parsed.href); return true; }
      if (typeof root.Telegram?.WebApp?.openLink === "function") { root.Telegram.WebApp.openLink(parsed.href); return true; }
    } catch (_) { /* The ordinary safe anchor remains the fallback. */ }
    return false;
  }
  function link(text, url, cls = "") {
    const result = node("a", text, cls); result.href = url; result.target = "_blank"; result.rel = "noopener noreferrer";
    result.onclick = event => { if (openExternal(result.href)) event.preventDefault(); }; return result;
  }
  function timeLeft(seconds) {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    return `${Math.floor(value / 86400)} дн. ${Math.floor(value % 86400 / 3600)} ч. ${Math.floor(value % 3600 / 60)} мин.`;
  }
  function create({ api, notify, navigate, topup, support, userId, refreshWallet, createRequestId }) {
    let activeView = "", data = null, requestVersion = 0, timer = null, selected = 0, modal = null, lastOverflow = "", activeStarted = 0;
    let purchasing = false, retryKey = null;
    const get = id => document.getElementById(id);
    function dialog(title) {
      modal?.close();
      const el = node("dialog", null, "modal more-modal"); el.setAttribute("aria-label", title);
      const heading = node("h2", title); el.append(heading); document.body.append(el); modal = el;
      lastOverflow = document.body.style.overflow; document.body.style.overflow = "hidden";
      el.addEventListener("cancel", event => { if (purchasing) event.preventDefault(); });
      el.addEventListener("click", event => { if (event.target !== el || purchasing) return; const r = el.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) el.close(); });
      el.addEventListener("close", () => { document.body.style.overflow = lastOverflow; if (modal === el) modal = null; el.remove(); }, { once: true });
      el.showModal(); return el;
    }
    function message(title, text) { const el = dialog(title); el.append(node("p", text), button("Понятно", () => el.close(), "publish-button")); }
    function services() {
      const el = dialog("🛠 Раздел обновляется");
      el.append(node("p", "Мы работаем над этим разделом. Следите за новостями и обновлениями в нашем Telegram-канале:"), link("Следить за обновлениями", "https://t.me/AutoFlowStore", "more-channel"), button("Понятно", () => el.close(), "ghost-button"));
    }
    document.querySelectorAll("[data-more-page]").forEach(el => { el.onclick = () => navigate(el.dataset.morePage); });
    document.querySelector("[data-more-services]").onclick = services;
    function loadError(host, error, retry) { host.replaceChildren(node("p", error?.message || "Не удалось загрузить данные.", "more-status"), button("Попробовать снова", retry)); }
    function benefit(text, kind, note) {
      const row = node("li", null, "seller-vip__benefit"); const mark = node("span", null, "seller-vip__benefit-icon"); mark.append(icon(kind));
      const copy = node("span"); copy.append(text); if (note) copy.append(node("small", note)); row.append(mark, copy); return row;
    }
    function laurel(right = false) {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", "0 0 36 70"); svg.setAttribute("class", `seller-vip__laurel${right ? " seller-vip__laurel--right" : ""}`); svg.setAttribute("aria-hidden", "true");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path"); path.setAttribute("d", "M29 67C10 51 8 24 28 3M21 58C7 57 5 48 6 44c8 2 12 6 15 14Zm-5-11C3 44 2 36 4 32c7 4 11 8 12 15Zm-3-13C2 28 4 21 7 18c5 5 7 9 6 16Zm3-13C9 13 14 6 18 4c2 7 1 12-2 17Zm7 42c-4-12 2-17 6-18 2 7 0 13-6 18Zm-7-14c-2-11 4-16 9-16 0 7-3 12-9 16Zm-3-14c0-10 7-13 11-11-1 7-5 10-11 11Zm4-14c3-9 9-10 13-8-3 5-7 8-13 8Zm6-11c3-8 8-10 12-9-1 5-5 8-12 9Z"); svg.append(path); return svg;
    }
    function vipBrand(card, active = false) {
      const brand = node("div", null, "seller-vip__brand"); brand.append(icon("crown"));
      const line = node("div", null, "seller-vip__word"); line.append(laurel(), node("strong", "VIP"), laurel(true));
      brand.append(line, node("span", active ? "Ваш VIP активен" : "для продавцов")); card.append(brand);
    }
    function renderPlans() {
      const host = get("sellerVipContent"); host.replaceChildren();
      const slider = node("div", null, "seller-vip__slider"); slider.setAttribute("aria-roledescription", "карусель"); slider.setAttribute("aria-label", "Тарифы VIP");
      const track = node("div", null, "seller-vip__track"); track.tabIndex = 0;
      data.plans.forEach(plan => {
        const card = node("article", null, "seller-vip-card"); card.dataset.vipPlan = plan.code; card.setAttribute("aria-label", plan.title);
        vipBrand(card); const price = node("p", null, "seller-vip__price"); price.append(node("strong", number(plan.price_af)), node("span", ` AF / ${plan.duration_days === 30 ? "месяц" : `${plan.duration_days} дней`}`));
        card.append(price, node("h2", plan.title, "seller-vip__plan-title"));
        const list = node("ul", null, "seller-vip__benefits");
        list.append(benefit(`${number(plan.pins_72h)} закреплений на 3 дня`, "pin"));
        if (plan.pins_24h > 0) list.append(benefit(`${number(plan.pins_24h)} закрепления на 1 день`, "pin"));
        list.append(benefit(`До ${number(plan.car_limit)} активных объявлений машин`, "car"), benefit(`VIP-галочка на ${number(plan.duration_days)} дней`, "badge"), benefit("Приоритетная обработка вывода", "bolt"), benefit(`До ${number(plan.account_limit)} объявлений аккаунтов`, "account", data.account_sales_enabled ? null : "Будет доступно после запуска продажи аккаунтов"));
        const buy = button("Купить VIP", () => void confirmPurchase(plan), "publish-button seller-vip__buy"); buy.prepend(icon("crown")); card.append(list, buy); track.append(card);
      });
      const controls = node("div", null, "seller-vip__controls"), dots = node("div", null, "seller-vip__dots");
      const show = index => { selected = Math.min(data.plans.length - 1, Math.max(0, index)); track.scrollTo({ left: selected * track.clientWidth, behavior: root.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" }); updateControls(); };
      const previous = button("‹", () => show(selected - 1)), next = button("›", () => show(selected + 1)); previous.setAttribute("aria-label", "Предыдущий тариф"); next.setAttribute("aria-label", "Следующий тариф");
      data.plans.forEach((plan, index) => { const dot = button("", () => show(index), "seller-vip__dot"); dot.setAttribute("aria-label", plan.title); dots.append(dot); });
      function updateControls() { previous.disabled = selected === 0; next.disabled = selected === data.plans.length - 1; [...dots.children].forEach((el, index) => { el.classList.toggle("is-active", index === selected); el.setAttribute("aria-pressed", String(index === selected)); }); }
      track.addEventListener("scroll", () => { selected = Math.round(track.scrollLeft / Math.max(1, track.clientWidth)); updateControls(); }, { passive: true });
      track.addEventListener("keydown", event => { if (!["ArrowRight", "ArrowLeft"].includes(event.key)) return; event.preventDefault(); show(selected + (event.key === "ArrowRight" ? 1 : -1)); });
      controls.append(previous, dots, next); slider.append(track, controls); host.append(slider, node("p", "Подписка не продлевается автоматически. Комиссия и ручной порядок выплат не меняются. VIP не подтверждает личность и не гарантирует безопасность сделки.", "seller-vip__fineprint"));
      selected = 0; updateControls();
    }
    function counter(list, text, value, total, kind, note) {
      const row = benefit(`${text}: ${number(value)} из ${number(total)}`, kind, note);
      const bar = node("progress"); bar.max = Math.max(1, Number(total)); bar.value = Math.min(Number(value), Number(total)); bar.setAttribute("aria-label", text); row.lastElementChild.append(bar); list.append(row);
    }
    function renderActive() {
      const subscription = data.active_subscription, card = node("article", null, "seller-vip-card seller-vip-card--active"); vipBrand(card, true);
      card.append(node("h2", subscription.title, "seller-vip__active-title")); const remaining = node("p", null, "seller-vip__remaining"); remaining.setAttribute("role", "timer"); card.append(remaining);
      activeStarted = performance.now();
      const tick = () => { const value = subscription.remaining_seconds - (performance.now() - activeStarted) / 1000; remaining.textContent = `Осталось: ${timeLeft(value)}`; if (value <= 0) { clearInterval(timer); timer = null; if (activeView === "seller-vip") void loadVip(); } };
      tick(); timer = root.setInterval(tick, 15000);
      const list = node("ul", null, "seller-vip__benefits");
      counter(list, "Закрепления на 3 дня", subscription.pins_72h_remaining, subscription.pins_72h_total, "pin");
      if (subscription.pins_24h_total > 0) counter(list, "Закрепления на 1 день", subscription.pins_24h_remaining, subscription.pins_24h_total, "pin");
      counter(list, "Активные объявления машин", subscription.active_cars, subscription.car_limit, "car");
      counter(list, "Активные объявления аккаунтов", subscription.active_accounts, subscription.account_limit, "account", data.account_sales_enabled ? null : "Будет доступно после запуска продажи аккаунтов");
      list.append(benefit("VIP-галочка: активна", "badge"), benefit("Приоритет вывода: активен", "bolt")); card.append(list, node("p", "У вас уже действует VIP. Повторная покупка временно недоступна, чтобы сохранить срок и оставшиеся привилегии.", "seller-vip__fineprint"), button("Обновить состояние", () => void loadVip()));
      get("sellerVipContent").replaceChildren(card);
    }
    async function loadVip() {
      const version = ++requestVersion, host = get("sellerVipContent"); clearInterval(timer); timer = null;
      host.setAttribute("aria-busy", "true"); host.replaceChildren(node("p", "Загружаем VIP…", "more-status"));
      try {
        const result = await api.request("/seller-vip", { retries: 0 });
        if (activeView !== "seller-vip" || version !== requestVersion) return;
        if (!Array.isArray(result.plans) || (!result.plans.length && !result.active_subscription)) throw new Error("Тарифы пока недоступны.");
        data = result; if (data.active_subscription) renderActive(); else renderPlans();
      } catch (error) { if (activeView === "seller-vip" && version === requestVersion) loadError(host, error, () => void loadVip()); }
      finally { if (version === requestVersion) host.removeAttribute("aria-busy"); }
    }
    function pendingPurchase(plan) {
      const key = `autoflow.vip.purchase.${userId()}.${plan.code}`;
      try { const existing = JSON.parse(localStorage.getItem(key)); if (existing?.id && existing?.fingerprint) return { ...existing, key, code: plan.code }; } catch (_) { /* Storage may be unavailable in private WebViews. */ }
      return null;
    }
    function requestId(plan, quote) {
      const existing = pendingPurchase(plan); if (existing) return existing;
      const key = `autoflow.vip.purchase.${userId()}.${plan.code}`, id = createRequestId(), fingerprint = quote.quote_fingerprint;
      const originalQuote = { plan: quote.plan, bonus_af: quote.bonus_af, regular_af: quote.regular_af, can_purchase: true, quote_fingerprint: fingerprint };
      try { localStorage.setItem(key, JSON.stringify({ id, fingerprint, quote: originalQuote })); } catch (_) { /* Backend still protects an active subscription. */ } return { key, id, code: plan.code, fingerprint, quote: originalQuote };
    }
    async function confirmPurchase(plan) {
      if (purchasing || modal) return;
      const el = dialog("Покупка VIP"), status = node("p", "Проверяем стоимость и баланс…", "more-status"); el.append(status);
      try {
        let quote = await api.request("/seller-vip/quote", { method: "POST", body: JSON.stringify({ plan_code: plan.code }), retries: 0 });
        if (!el.open) return;
        if (quote.active_subscription_id) { el.close(); await loadVip(); return; }
        const pending = pendingPurchase(plan);
        if (pending?.quote) { quote = pending.quote; el.append(node("p", "Есть ранее подтверждённая вами попытка с неизвестным результатом. Ниже её первоначальные условия. Повтор использует тот же номер запроса, а не создаёт новую покупку.", "seller-vip__fineprint")); }
        status.remove(); el.append(node("p", `Тариф: ${quote.plan.title}`)); const amounts = node("dl", null, "more-amounts");
        for (const [label, amount] of [["Стоимость", quote.plan.price_af], ["Из реферальных бонусов", quote.bonus_af], ["Из обычного баланса", quote.regular_af]]) amounts.append(node("dt", label), node("dd", `${number(amount)} AF`));
        el.append(amounts, node("p", "Сначала расходуются бонусы, затем обычные AF. Бонусы не становятся доступными для вывода.", "seller-vip__fineprint"));
        if (!quote.can_purchase) {
          el.append(node("p", `Не хватает ${number(quote.missing_af)} AF.`), button("Пополнить баланс", () => { el.close(); topup(); }, "publish-button"), button("Отмена", () => el.close())); return;
        }
        const feedback = node("p", "", "more-purchase-error"); feedback.setAttribute("role", "status");
        const actions = node("div", null, "more-modal__actions"), cancel = button("Отмена", () => el.close()), confirm = button("Подтвердить покупку", async () => {
          if (purchasing) return; purchasing = true; confirm.disabled = true; cancel.disabled = true; confirm.classList.add("is-loading"); confirm.textContent = "Покупаем…"; feedback.textContent = "";
          try {
            if (!retryKey || retryKey.code !== plan.code) retryKey = requestId(plan, quote);
            await api.request("/seller-vip/purchases", { method: "POST", body: JSON.stringify({ plan_code: plan.code, request_id: retryKey.id, quote_fingerprint: retryKey.fingerprint }), retries: 0 });
            try { localStorage.removeItem(retryKey.key); } catch (_) { /* Nonessential cleanup. */ } retryKey = null;
            purchasing = false; el.close(); if (activeView === "seller-vip") await loadVip();
            try { await refreshWallet(); } catch (_) { notify("VIP приобретён. Обновите баланс при следующем открытии кошелька."); }
            message("🎉 Поздравляем!", `Вы успешно приобрели «${quote.plan.title}». Все привилегии уже доступны.`);
            try { root.Telegram?.WebApp?.HapticFeedback?.notificationOccurred?.("success"); } catch (_) { /* Optional. */ }
          } catch (error) {
            if (error.detail?.code === "seller_vip_quote_changed" || error.status === 402) {
              try { localStorage.removeItem(retryKey.key); } catch (_) { /* Nonessential cleanup. */ }
              retryKey = null; purchasing = false; el.close(); notify("Условия или источники оплаты изменились. Проверьте новый расчёт перед покупкой."); void confirmPurchase(plan);
            } else feedback.textContent = `${error.message || "Не удалось подтвердить покупку."} При сетевой ошибке можно повторить: списание защищено от дублирования.`;
          } finally { purchasing = false; confirm.disabled = false; cancel.disabled = false; confirm.classList.remove("is-loading"); confirm.textContent = "Подтвердить покупку"; }
        }, "publish-button");
        actions.append(cancel, confirm); el.append(feedback, actions);
      } catch (error) { if (el.open) { status.textContent = error.message || "Не удалось проверить покупку."; el.append(button("Понятно", () => el.close())); } }
    }
    function aboutSection(title, text) { const card = node("section", null, "about-card"); card.append(node("h2", title)); if (text) card.append(node("p", text)); return card; }
    function renderAbout(info) {
      const host = get("aboutContent"); host.replaceChildren();
      const hero = node("header", null, "about-hero"); hero.append(node("strong", "AUTOFLOW"), node("strong", "MARKET"), node("p", "Создано игроком для игроков"));
      const intro = aboutSection("О нашем проекте", "AutoFlow Market — независимая торговая площадка, созданная для удобной и безопасной покупки и продажи игровых автомобилей. Наша цель — создать место, где каждый игрок сможет продавать свои проекты, покупать автомобили и зарабатывать, используя систему защиты сделок.");
      const games = node("div", null, "about-games"); for (const [name, mark] of [["Car Parking 1", "CP1"], ["Car Parking 2", "CP2"]]) { const tile = node("div", null, "about-game"); tile.append(icon("car"), node("strong", mark), node("span", name)); games.append(tile); } intro.append(games);
      const stats = node("section", null, "about-stats"); stats.setAttribute("aria-label", "AutoFlow в цифрах");
      for (const [value, label, kind] of [[info.users, "Пользователей", "community"], [info.completed_deals, "Успешных сделок", "badge"], [info.founded_year || 2026, "Год основания", "pin"], [info.games?.length || 2, "Поддерживаемые игры", "car"]]) { const tile = node("div", null, "about-stat"); tile.append(icon(kind), node("strong", value == null ? "—" : kind === "pin" ? String(value) : number(value)), node("span", label)); stats.append(tile); }
      const source = node("p", "Показатели рассчитаны сервером по сохранённым пользователям и завершённым сделкам. Отменённые и возвращённые сделки не учитываются.", "seller-vip__fineprint");
      const story = aboutSection("История создания"); story.prepend(node("span", "“", "about-quote"));
      for (const paragraph of ["Я решил создать AutoFlow Market, потому что видел, как часто игроки сталкиваются с обманом при покупке и продаже автомобилей. Людям приходилось искать покупателей в чатах, тратить своё время и рисковать своими деньгами.", "Я хотел это изменить и создать площадку, где каждый сможет продавать свои проекты, покупать автомобили и зарабатывать.", "На протяжении нескольких месяцев я работал над маркетом, часто до поздней ночи. Исправлял ошибки, переделывал дизайн и улучшал функционал, стараясь довести каждую деталь до идеала.", "Не всё получалось с первого раза, но я продолжал работать над проектом. И сегодня я продолжаю развивать его, прислушиваясь к мнению наших пользователей."]) story.append(node("p", paragraph));
      const founder = node("div", null, "about-founder"); if (info.founder?.photo_url || info.founder_photo_url) { const photo = node("img"); photo.src = info.founder?.photo_url || info.founder_photo_url; photo.alt = "Maxim — основатель AutoFlow Market"; photo.loading = "lazy"; photo.onerror = () => photo.replaceWith(icon("account")); founder.append(photo); } else founder.append(icon("account"));
      const identity = node("div"); identity.append(node("strong", "Maxim"), node("span", "Основатель AutoFlow Market")); founder.append(identity); story.append(founder);
      const why = aboutSection("Почему AutoFlow?"), reasons = node("div", null, "about-reasons");
      for (const [kind, title, text] of [["shield", "Защита сделок", "Средства резервируются до завершения сделки."], ["coin", "Возможность заработка", "Продавайте свои проекты и выводите заработанные средства."], ["bolt", "Удобство использования", "Покупайте и продавайте прямо в Telegram."], ["support", "Поддержка пользователей", "Помогаем разобраться в вопросах и спорных ситуациях."], ["refresh", "Постоянные обновления", "Регулярно улучшаем маркет и добавляем новые возможности."], ["community", "Сообщество игроков", "Объединяем игроков с общими интересами."]]) { const tile = node("div"); tile.append(icon(kind), node("h3", title), node("p", text)); reasons.append(tile); } why.append(reasons);
      const plans = aboutSection("Наши планы"), list = node("ul"); for (const item of ["Безопасная покупка и продажа игровых аккаунтов", "Раздел игровых услуг", "Развитие VIP-программы", "Улучшение скорости и стабильности маркета"]) list.append(node("li", item)); plans.append(list);
      const socials = aboutSection("Наши социальные сети");
      for (const [title, handle, url, mark] of [["YouTube", "@autoflow01", "https://youtube.com/@autoflow01?si=jZICmcVQNtoxvox6", "▶"], ["TikTok", "@autoflow01", "https://www.tiktok.com/@autoflow01", "♪"], ["Новости AutoFlow Market", "@AutoFlowStore", "https://t.me/AutoFlowStore", "➤"], ["Основной Telegram-канал", "@AutoFlow1", "https://t.me/AutoFlow1", "➤"], ["Отзывы пользователей", "@otzyvy_AutoFlow1", "https://t.me/otzyvy_AutoFlow1", "★"]]) { const row = link("", url, "about-social"); const text = node("span"); text.append(node("strong", title), node("small", handle)); row.append(node("span", mark, "about-social__icon"), text, node("span", "›")); socials.append(row); }
      const feedback = aboutSection("Обратная связь"); for (const label of ["Предложения по улучшению", "Сотрудничество", "Техническая поддержка"]) feedback.append(button(label, () => support(), "about-feedback")); feedback.append(node("small", "Откроется действующая поддержка AutoFlow Market. Укажите тему обращения."));
      const footer = node("footer", null, "about-footer"); footer.append(node("h2", "Спасибо, что вы с нами!"), node("p", "Каждый пользователь помогает нашему проекту становиться лучше. И это только начало."), node("strong", "AUTOFLOW MARKET"), node("p", "© 2026 AutoFlow Market."), node("small", "Независимый проект, не связанный с разработчиками Car Parking Multiplayer."));
      host.append(hero, intro, stats, source, story, why, plans, socials, feedback, footer);
    }
    async function loadAbout() {
      const version = ++requestVersion, host = get("aboutContent"); host.replaceChildren(node("p", "Загрузка информации…", "more-status")); host.setAttribute("aria-busy", "true");
      try { const info = await api.request("/about", { retries: 0 }); if (activeView === "about" && version === requestVersion) renderAbout(info); }
      catch (error) { if (activeView === "about" && version === requestVersion) loadError(host, error, () => void loadAbout()); }
      finally { if (version === requestVersion) host.removeAttribute("aria-busy"); }
    }
    let adminOffset = 0, adminVersion = 0, adminFilter = "active", adminPlans = null;
    function mountAdmin() {
      if (get("adminSellerVip")) return;
      const tabs = document.querySelector(".admin-tabs"); if (!tabs) return;
      const tab = button("VIP для продавцов", () => {}); tab.dataset.adminTab = "seller-vip"; tabs.append(tab);
      const panel = node("section", null, "seller-vip-admin"); panel.dataset.adminPanel = "seller-vip"; panel.hidden = true; panel.id = "adminSellerVip";
      const filters = node("div", null, "seller-vip-admin__filters"), select = node("select"); select.setAttribute("aria-label", "Статус VIP-подписки");
      for (const [value, label] of [["active", "Активные"], ["expired", "Истёкшие"], ["disabled", "Отключённые"]]) { const option = node("option", label); option.value = value; select.append(option); }
      select.onchange = () => { adminFilter = select.value; adminOffset = 0; void loadAdmin(); };
      filters.append(select, button("Выдать VIP", () => void grantSearch()), button("Обновить", () => void loadAdmin()));
      panel.append(node("h2", "VIP-подписки продавцов"), node("p", "Время: Europe/Bratislava. Выдача, продление и отключение требуют подтверждения и причины; сервер сохраняет административный журнал."), filters, node("div", null, "seller-vip-admin__list")); tabs.parentElement.append(panel);
    }
    async function loadAdmin() {
      mountAdmin(); const host = get("adminSellerVip").querySelector(".seller-vip-admin__list"), version = ++adminVersion;
      host.replaceChildren(node("p", "Загружаем подписки…"));
      try {
        const result = await api.request(`/admin/seller-vip?status=${encodeURIComponent(adminFilter)}&limit=25&offset=${adminOffset}`);
        if (version !== adminVersion) return; host.replaceChildren();
        for (const item of result.items) {
          const card = node("article", null, "admin-record"), dates = value => new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Bratislava", dateStyle: "short", timeStyle: "short" }).format(new Date(value));
          card.append(node("strong", `${item.name}${item.username ? ` · @${item.username}` : ""}`), node("small", `Telegram ID ${item.telegram_id} · ${item.title} · ${item.status}`), node("p", `${dates(item.starts_at)} → ${dates(item.expires_at)} (Europe/Bratislava)`), node("p", `Стоимость: ${number(item.price_paid)} AF · Бонусы: ${number(item.bonus_af)} AF · Обычные: ${number(Number(item.purchased_af) + Number(item.earned_af))} AF · ${item.payment_source === "admin" ? "Выдано администратором" : item.payment_source === "mixed" ? "Смешанная оплата" : item.payment_source === "bonus" ? "Бонусный баланс" : "Обычный баланс"}`), node("p", `Закрепления: 3 дня — ${item.pins_72h_remaining} из ${item.pins_72h_total}; 1 день — ${item.pins_24h_remaining} из ${item.pins_24h_total}`));
          const actions = node("div", null, "admin-record__actions"); if (item.status === "active") actions.append(button("Продлить", () => adminAction("extend", item)), button("Отключить", () => adminAction("disable", item))); card.append(actions); host.append(card);
        }
        if (!result.items.length) host.append(node("p", "Подписок с таким статусом нет."));
        const pager = node("div", null, "seller-vip-admin__filters"); if (adminOffset > 0) pager.append(button("Назад", () => { adminOffset = Math.max(0, adminOffset - 25); void loadAdmin(); })); if (result.has_more) pager.append(button("Далее", () => { adminOffset += 25; void loadAdmin(); })); host.append(pager);
      } catch (error) { if (version === adminVersion) loadError(host, error, () => void loadAdmin()); }
    }
    async function grantSearch() {
      const el = dialog("Выдать VIP пользователю"), form = node("form"), field = node("input"), results = node("div"); field.placeholder = "Username, имя или Telegram ID"; field.required = true; field.minLength = 1; field.setAttribute("aria-label", "Найти пользователя для выдачи VIP");
      const submit = node("button", "Найти", "ghost-button"); submit.type = "submit"; form.append(field, submit); el.append(form, results);
      form.onsubmit = async event => { event.preventDefault(); if (submit.disabled) return; submit.disabled = true; results.textContent = "Поиск…";
        try {
          const items = await api.request(`/admin/users?q=${encodeURIComponent(field.value.trim())}&limit=10&offset=0`); if (!el.open) return; results.replaceChildren();
          for (const value of items) { const user = value.user; results.append(button(`${user.first_name}${user.username ? ` · @${user.username}` : ""} · ${user.telegram_id}`, async event => { const choice = event.currentTarget; if (choice.disabled) return; choice.disabled = true; try { if (!adminPlans) adminPlans = (await api.request("/seller-vip")).plans; el.close(); adminAction("grant", { user_id: user.id, name: user.first_name }, adminPlans); } catch (error) { notify(error.message || "Не удалось загрузить тарифы"); } finally { choice.disabled = false; } }, "about-feedback")); }
          if (!items.length) results.textContent = "Пользователь не найден.";
        } catch (error) { results.textContent = error.message; } finally { submit.disabled = false; }
      }; el.append(button("Отмена", () => el.close()));
    }
    function adminAction(action, item, plans = []) {
      const titles = { grant: "Выдать VIP", extend: "Продлить VIP", disable: "Отключить VIP" }, el = dialog(titles[action]), form = node("form"), reason = node("textarea"), status = node("p", "");
      el.append(node("p", `Пользователь: ${item.name}. Изменение будет сохранено в журнале.`));
      const plan = node("select"), days = node("input");
      if (action === "grant") { plan.setAttribute("aria-label", "Тариф VIP"); for (const value of plans) { const option = node("option", value.title); option.value = value.code; plan.append(option); } form.append(plan); }
      if (action === "extend") { const label = node("label", "На сколько дней продлить"); days.type = "number"; days.min = "1"; days.max = "365"; days.step = "1"; days.required = true; days.value = "30"; label.append(days); form.append(label); }
      const reasonLabel = node("label", "Причина (обязательно)"); reason.required = true; reason.minLength = 3; reason.maxLength = 2000; reason.rows = 3; reasonLabel.append(reason); form.append(reasonLabel);
      const id = createRequestId(), actions = node("div", null, "more-modal__actions"), cancel = button("Отмена", () => el.close()), confirm = node("button", `Подтвердить: ${titles[action].toLowerCase()}`, "publish-button"); confirm.type = "submit"; actions.append(cancel, confirm); status.setAttribute("role", "status"); form.append(status, actions); el.append(form);
      form.onsubmit = async event => { event.preventDefault(); if (purchasing) return; purchasing = true; cancel.disabled = true; confirm.disabled = true; status.textContent = "Сохраняем…";
        const payload = { user_id: item.user_id, action, request_id: id, reason: reason.value.trim(), confirmed: true }; if (action === "grant") payload.plan_code = plan.value; if (action === "extend") payload.days = Number(days.value);
        try { await api.request("/admin/seller-vip/actions", { method: "POST", body: JSON.stringify(payload), retries: 0 }); purchasing = false; el.close(); await loadAdmin(); notify("Изменение VIP сохранено в журнале"); }
        catch (error) { status.textContent = error.message || "Не удалось изменить VIP."; }
        finally { purchasing = false; cancel.disabled = false; confirm.disabled = false; }
      };
    }
    function setActive(view) {
      const changed = activeView !== view; activeView = view;
      if (!changed) return;
      ++requestVersion; clearInterval(timer); timer = null;
      if (view === "seller-vip") void loadVip();
      if (view === "about") void loadAbout();
    }
    function dismiss() { if (!modal?.open) return false; if (!purchasing) modal.close(); return true; }
    return { setActive, dismiss, refreshVip: loadVip, message, mountAdmin, loadAdmin };
  }
  root.AutoFlowMore = { create, timeLeft, openExternal };
  if (typeof module === "object" && module.exports) module.exports = { timeLeft };
})(typeof window === "object" ? window : globalThis);
