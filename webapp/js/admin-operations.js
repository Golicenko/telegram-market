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
    for (const [key, title, id] of [["overview", "Обзор", "adminOverview"], ["audit", "Журнал действий", "adminAudit"]]) {
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
          content.append(node("p", "DAU, открытия Mini App и просмотры обучения: не собирались. Это не нулевые значения."), details);
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
  async function page(api, key, query = {}) {
    const generation = (versions.get(key) || 0) + 1; versions.set(key, generation);
    const values = await api.request(`/admin/${key}?${new URLSearchParams({ ...query, limit: 50, offset: pages.get(key) || 0 })}`);
    return versions.get(key) === generation ? values : null;
  }
  function pager(host, key, count, reload) {
    if (!count) host.append(node("p", "Записей нет"));
    const controls = node("div", null, "admin-report-filters"), offset = pages.get(key) || 0;
    const move = async delta => { controls.querySelectorAll("button").forEach(b => { b.disabled = true; }); pages.set(key, Math.max(0, offset + delta)); try { await reload(); } catch (error) { pages.set(key, offset); errorState(host, error, reload); } };
    const prev = button("Назад", () => void move(-50)); prev.disabled = !offset;
    const next = button("Далее", () => void move(50)); next.disabled = count < 50;
    controls.append(prev, node("span", `Страница ${offset / 50 + 1}`), next); host.append(controls);
  }
  root.AutoFlowAdmin = { mount, overview, audit, page, pager, errorState, reset: key => pages.set(key, 0) };
})(window);
