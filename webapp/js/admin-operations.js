(function (root) {
  "use strict";
  const labels = {
    new_users: "Новые аккаунты (включая бота)", orders_created: "Создано заказов",
    orders_completed: "Завершено заказов", orders_cancelled: "Отменено заказов",
    seller_timeouts: "Обработано неответов продавца", topup_intents: "Создано Stars-инвойсов",
    credited_payments: "Зачислено Stars-платежей", credited_stars: "Зачислено Stars, ⭐",
    withdrawals_requested: "Создано заявок на вывод", withdrawals_paid: "Выполнено выводов",
    training_paid: "Оплачено заказов обучения", withdrawals: "Выводы в очереди",
    support: "Открытые обращения", deal_review: "Сделки на проверке",
    active_listings: "Активные объявления", notification_failures: "Ошибки доставки уведомлений",
  };
  const pages = new Map();
  const versions = new Map();
  function node(tag, text, className) {
    const result = document.createElement(tag); if (text != null) result.textContent = text;
    if (className) result.className = className; return result;
  }
  function button(text, action) {
    const result = node("button", text); result.type = "button"; result.addEventListener("click", action); return result;
  }
  function dateText(value) {
    return new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Bratislava", dateStyle: "short", timeStyle: "short" }).format(new Date(value));
  }
  function currentDate() {
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Bratislava", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
    const value = (name) => parts.find(p => p.type === name).value;
    return `${value("year")}-${value("month")}-${value("day")}`;
  }
  function errorState(container, error, retry) {
    const message = node("p", error.message || "Не удалось загрузить данные"); message.setAttribute("role", "alert");
    container.replaceChildren(message, button("Повторить", retry));
  }
  function mount() {
    const tabs = document.querySelector(".admin-tabs");
    if (!tabs || document.getElementById("adminOverview")) return;
    for (const [key, title, id] of [["overview", "Обзор", "adminOverview"], ["analytics", "Аналитика", "adminAnalytics"], ["audit", "Журнал действий", "adminAudit"]]) {
      const tab = node("button", title); tab.type = "button"; tab.dataset.adminTab = key;
      key === "overview" ? tabs.prepend(tab) : tabs.append(tab);
      const panel = node("section"); panel.dataset.adminPanel = key; panel.hidden = true;
      const content = node("div"); content.id = id; panel.append(content); tabs.parentElement.append(panel);
    }
  }
  async function overview(api) {
    const host = document.getElementById("adminOverview");
    if (!host.dataset.ready) {
      host.dataset.ready = "true";
      const form = node("form", null, "admin-report-filters");
      const start = node("input"), end = node("input"); start.type = end.type = "date";
      start.name = "start"; end.name = "end"; start.required = end.required = true;
      start.value = end.value = currentDate();
      for (const [caption, input] of [["С", start], ["По", end]]) { const label = node("label", caption); label.append(input); form.append(label); }
      const submit = node("button", "Показать"); submit.type = "submit"; form.append(submit);
      const content = node("div"); content.setAttribute("aria-live", "polite");
      const load = async () => {
        const generation = (versions.get("overview") || 0) + 1; versions.set("overview", generation);
        content.textContent = "Загрузка…"; submit.disabled = true;
        try {
          const data = await api.request(`/admin/overview?${new URLSearchParams({ start: start.value, end: end.value, timezone: "Europe/Bratislava" })}`);
          if (versions.get("overview") !== generation) return;
          content.replaceChildren(node("p", `${dateText(data.from_utc)} — ${dateText(data.until_utc_exclusive)} (конец не включён) · ${data.timezone}`));
          for (const [heading, values] of [["За выбранный период", data.metrics], ["Требует внимания сейчас · все даты", data.pending_now]]) {
            content.append(node("h3", heading)); const grid = node("div", null, "admin-metric-grid");
            for (const [key, value] of Object.entries(values)) {
              const card = node("div", null, "admin-metric"); card.append(node("strong", String(value)), node("span", labels[key] || key)); grid.append(card);
            }
            content.append(grid);
          }
          const details = node("details"); details.append(node("summary", "Определения и ограничения данных"));
          Object.values(data.definitions).forEach(value => details.append(node("p", value)));
          content.append(node("p", "DAU, открытия Mini App и просмотры обучения — во вкладке «Аналитика». История до начала сбора недоступна."), details);
        } catch (error) { if (versions.get("overview") === generation) errorState(content, error, load); }
        finally { if (versions.get("overview") === generation) submit.disabled = false; }
      };
      form.addEventListener("submit", event => { event.preventDefault(); void load(); });
      const quick = node("div", null, "admin-report-filters");
      for (const [days, caption] of [[1, "Сегодня"], [7, "7 дней"], [30, "30 дней"]]) quick.append(button(caption, () => {
        end.value = currentDate(); const value = new Date(`${end.value}T12:00:00Z`); value.setUTCDate(value.getUTCDate() - days + 1); start.value = value.toISOString().slice(0, 10); void load();
      }));
      host.append(node("h2", "Операционный обзор"), quick, form, content); host.reload = load;
    }
    await host.reload();
  }
  async function audit(api) {
    const host = document.getElementById("adminAudit");
    if (!host.dataset.ready) {
      host.dataset.ready = "true";
      const form = node("form", null, "admin-report-filters"), input = node("input");
      input.placeholder = "Тип действия (точное совпадение)"; input.setAttribute("aria-label", "Тип действия"); input.maxLength = 96;
      const submit = node("button", "Найти"); submit.type = "submit"; form.append(input, submit);
      const content = node("div"); let offset = 0;
      const load = async () => {
        const generation = (versions.get("audit") || 0) + 1; versions.set("audit", generation);
        content.textContent = "Загрузка…";
        try {
          const query = new URLSearchParams({ limit: 50, offset }); if (input.value.trim()) query.set("action", input.value.trim());
          const data = await api.request(`/admin/audit?${query}`); if (versions.get("audit") !== generation) return;
          content.replaceChildren(); if (!data.items.length) content.append(node("p", "Записей нет"));
          data.items.forEach(item => {
            const card = node("article", null, "admin-record"); card.append(node("strong", item.action), node("small", `${dateText(item.created_at)} · Europe/Bratislava · ${item.actor_name}`), node("p", `${item.target_type}: ${item.target_id || "—"}`), node("p", item.reason || "Причина не записана в старой операции"));
            if (Object.keys(item.changes).length) card.append(node("pre", JSON.stringify(item.changes, null, 2)));
            content.append(card);
          });
          const prev = button("Назад", () => { offset = Math.max(0, offset - 50); void load(); }); prev.disabled = !offset;
          const next = button("Далее", () => { offset += 50; void load(); }); next.disabled = !data.has_more;
          const controls = node("div", null, "admin-report-filters"); controls.append(prev, node("span", `Страница ${offset / 50 + 1}`), next); content.append(controls);
        } catch (error) { if (versions.get("audit") === generation) errorState(content, error, load); }
      };
      form.addEventListener("submit", event => { event.preventDefault(); offset = 0; void load(); });
      host.append(node("h2", "Журнал административных действий"), form, content); host.reload = load;
    }
    await host.reload();
  }
  async function analytics(api) {
    const host = document.getElementById("adminAnalytics");
    if (!host.dataset.ready) {
      host.dataset.ready = "true";
      const form = node("form", null, "admin-report-filters"), start = node("input"), end = node("input");
      start.type = end.type = "date"; start.required = end.required = true; start.value = end.value = currentDate();
      for (const [text, input] of [["С", start], ["По", end]]) { const label = node("label", text); label.append(input); form.append(label); }
      const submit = node("button", "Показать"); submit.type = "submit"; form.append(submit);
      const content = node("div"), products = node("div"); let offset = 0;
      const query = () => new URLSearchParams({ start: start.value, end: end.value, timezone: "Europe/Bratislava" });
      const table = (headers, rows) => {
        const box = node("div", null, "analytics-table-scroll"), element = node("table"), head = node("tr");
        headers.forEach(h => head.append(node("th", h))); const thead = node("thead"); thead.append(head); element.append(thead);
        const body = node("tbody"); rows.forEach(values => { const row = node("tr"); values.forEach(value => row.append(node("td", value == null ? "Не собиралось" : String(value)))); body.append(row); });
        element.append(body); box.append(element); return box;
      };
      const loadProducts = async () => {
        const key = (versions.get("analytics-products") || 0) + 1; versions.set("analytics-products", key);
        products.textContent = "Загрузка товаров…";
        try {
          const params = query(); params.set("offset", offset);
          const data = await api.request(`/admin/analytics/training?${params}`); if (versions.get("analytics-products") !== key) return;
          products.replaceChildren(node("h3", "Обучение: товары"), node("p", data.definition));
          if (data.views_partial) products.append(node("p", "История просмотров неполная: сбор начат позже выбранного периода или отключён."));
          products.append(table(["Продукт", "Просмотры", "Пользователи", "Оплаты", "Выдано", "Ошибки выдачи"], data.items.map(p => [p.title, p.views, p.viewers, p.paid, p.fulfilled, p.delivery_failed])));
          const prev = button("Назад", () => { offset = Math.max(0, offset - 50); void loadProducts(); }); prev.disabled = !offset;
          const next = button("Далее", () => { offset += 50; void loadProducts(); }); next.disabled = !data.has_more;
          const controls = node("div", null, "admin-report-filters"); controls.append(prev, next); products.append(controls);
        } catch (error) { if (versions.get("analytics-products") === key) errorState(products, error, loadProducts); }
      };
      const eventLabels = { account_created: "Новые аккаунты", listing_created: "Создано объявлений", order_paid: "Оплачено заказов (удержано)", order_completed: "Завершено (выплата продавцу)", order_refunded: "Возвращено покупателям", listing_pinned: "Платные закрепления", seller_order_accepted: "Принято продавцом", seller_timeout: "Неответ обработан", topup_checkout_started: "Создано Stars-инвойсов", topup_success: "Зачислено Stars-платежей", withdrawal_requested: "Заявки на вывод", withdrawal_paid: "Вывод выполнен", training_paid: "Оплачено обучение", referral_registered: "Новые рефералы", referral_milestone_paid: "Награды 3/10/20", referral_topup_commission_paid: "Комиссии рефералов" };
      const load = async () => {
        const key = (versions.get("analytics") || 0) + 1; versions.set("analytics", key);
        versions.set("analytics-products", (versions.get("analytics-products") || 0) + 1);
        products.replaceChildren();
        content.textContent = "Загрузка…"; submit.disabled = true; offset = 0;
        try {
          const data = await api.request(`/admin/analytics?${query()}`); if (versions.get("analytics") !== key) return;
          content.replaceChildren(node("p", `${start.value} — ${end.value} · ${data.timezone}`));
          content.append(node("h3", "Подтверждённые серверные события"), table(["Событие", "Количество", "Предыдущий равный период", "Сумма"], Object.entries(data.server_events).map(([name, value]) => [eventLabels[name] || name, value.count, data.previous_server_events[name]?.count, value.unit === "count" ? "—" : value.amount == null ? "Не сохранена в старых записях" : `${value.amount} ${value.unit}`])));
          content.append(node("h3", "Воронки и активность"));
          if (!data.client_data_available) content.append(node("p", "За этот период наблюдения не собирались или сбор отключён. Это не нулевые показатели."));
          else {
            if (data.client_period_partial) content.append(node("p", "Неполный период сбора. Конверсию нельзя сравнивать с полным историческим периодом."));
            const t = data.funnels.topup, training = data.funnels.training;
            content.append(node("p", `Пополнение, пользователи одной когорты: открыли ${t.opened_users} → создали инвойс ${t.invoice_users} → оплатили ${t.paid_users}.`));
            content.append(node("p", `Обучение, пары пользователь/товар: посмотрели ${training.viewed_user_products} → купили ${training.paid_user_products}.`));
            content.append(table(["День", "DAU (наблюдавшиеся)", "Запуски"], data.daily_activity.map(day => [day.day, day.dau, day.opens])));
            content.append(node("h3", "Наблюдения клиента (не платежные подтверждения)"), table(["Событие", "Платформа", "Причина", "События", "Пользователи"], data.client_observations.map(e => [e.event_name, e.platform, e.reason || "—", e.events, e.users])));
          }
          const timing = data.seller_accept_seconds;
          content.append(node("p", timing.sample ? `Принятие продавцом: ${timing.sample} заказов; медиана ${(Number(timing.median) / 60).toFixed(1)} мин, p90 ${(Number(timing.p90) / 60).toFixed(1)} мин.` : "Недостаточно записей явного принятия для расчёта времени ответа."));
          const details = node("details"); details.append(node("summary", "Как считаются данные")); data.definitions.forEach(text => details.append(node("p", text))); content.append(details);
          await loadProducts();
        } catch (error) { if (versions.get("analytics") === key) errorState(content, error, load); }
        finally { if (versions.get("analytics") === key) submit.disabled = false; }
      };
      form.addEventListener("submit", event => { event.preventDefault(); void load(); });
      const quick = node("div", null, "admin-report-filters");
      for (const [days, label] of [[1, "Сегодня"], [7, "7 дней"], [30, "30 дней"]]) quick.append(button(label, () => { end.value = currentDate(); const begin = new Date(`${end.value}T12:00:00Z`); begin.setUTCDate(begin.getUTCDate() - days + 1); start.value = begin.toISOString().slice(0, 10); void load(); }));
      host.append(node("h2", "Аналитика"), quick, form, content, products); host.reload = load;
    }
    await host.reload();
  }
  async function page(api, key, query = {}) {
    const generation = (versions.get(key) || 0) + 1; versions.set(key, generation);
    const values = await api.request(`/admin/${key}?${new URLSearchParams({ ...query, limit: 50, offset: pages.get(key) || 0 })}`);
    return versions.get(key) === generation ? values : null;
  }
  function filters(host, key, fields, reload) {
    let form = document.getElementById(`admin-filters-${key}`);
    if (!form) {
      form = node("form", null, "admin-report-filters"); form.id = `admin-filters-${key}`;
      for (const [name, title, options] of fields) {
        const label = node("label", title), select = node("select"); select.name = name;
        for (const [value, text] of options) { const option = node("option", text); option.value = value; select.append(option); }
        select.addEventListener("change", () => { pages.set(key, 0); reload().catch(error => errorState(host, error, reload)); });
        label.append(select); form.append(label);
      }
      form.addEventListener("submit", event => event.preventDefault()); host.before(form);
    }
    return Object.fromEntries([...new FormData(form)].filter(([, value]) => value));
  }
  function pager(host, key, count, reload) {
    if (!count) host.append(node("p", "Записей нет"));
    const controls = node("div", null, "admin-report-filters"), offset = pages.get(key) || 0;
    const move = async delta => { controls.querySelectorAll("button").forEach(b => { b.disabled = true; }); pages.set(key, Math.max(0, offset + delta)); try { await reload(); } catch (error) { pages.set(key, offset); errorState(host, error, reload); } };
    const prev = button("Назад", () => void move(-50)); prev.disabled = !offset;
    const next = button("Далее", () => void move(50)); next.disabled = count < 50;
    controls.append(prev, node("span", `Страница ${offset / 50 + 1}`), next); host.append(controls);
  }
  root.AutoFlowAdmin = { mount, overview, audit, analytics, page, pager, filters, errorState, reset: key => pages.set(key, 0) };
})(window);
