(function (root) {
  "use strict";
  const paymentLabels = { paid: "Оплачено", refunded: "Возвращено", partially_refunded: "Частичный возврат", unverified: "Нет подтверждения оплаты" };
  const deliveryLabels = { pending: "Ожидает выдачи", sending: "Выдаётся", delivered: "Выдано", failed: "Ошибка выдачи", not_applicable: "Персональное обучение" };
  const statusLabels = { awaiting_start: "Ожидает начала", in_progress: "В работе", completed: "Завершено" };
  function node(tag, text, cls) { const value = document.createElement(tag); if (text != null) value.textContent = text; if (cls) value.className = cls; return value; }
  function dateInZone(zone, days = 0) {
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
    const get = key => parts.find(p => p.type === key).value;
    const value = new Date(`${get("year")}-${get("month")}-${get("day")}T12:00:00Z`);
    value.setUTCDate(value.getUTCDate() + days); return value.toISOString().slice(0, 10);
  }
  function mount(api, parent) {
    const section = node("section", null, "training-sales"); section.id = "trainingSales";
    section.append(node("h2", "Аналитика обучений"));
    const form = node("form", null, "training-sales__filters");
    function field(label, type, name) { const wrapper = node("label", label); const input = node("input"); input.type = type; input.name = name; wrapper.append(input); form.append(wrapper); return input; }
    const zone = field("Часовой пояс", "text", "timezone"); zone.value = "Europe/Bratislava";
    const start = field("С даты", "date", "start"), end = field("По дату включительно", "date", "end");
    const search = field("№ покупки / username / Telegram ID / обучение", "search", "search"); search.maxLength = 128;
    const buyer = field("Покупатель: имя, username или ID", "search", "buyer"); buyer.maxLength = 128;
    const product = field("ID обучения (необязательно)", "text", "product_id");
    const statusLabel = node("label", "Оплата"), status = node("select"); status.name = "payment_status";
    for (const [value, label] of [["", "Все статусы"], ...Object.entries(paymentLabels)]) { const option = node("option", label); option.value = value; status.append(option); }
    statusLabel.append(status); form.append(statusLabel);
    const presets = node("div", null, "training-sales__presets");
    let allTime = true, offset = 0, generation = 0, debounce;
    for (const [label, days] of [["Сегодня", 0], ["Вчера", -1], ["7 дней", 6], ["30 дней", 29], ["Всё время", null]]) {
      const button = node("button", label); button.type = "button";
      button.onclick = () => { try { allTime = days === null; start.value = dateInZone(zone.value, days === -1 ? -1 : -(days || 0)); end.value = dateInZone(zone.value, days === -1 ? -1 : 0); offset = 0; void load(); } catch { message.textContent = "Проверьте часовой пояс"; } };
      presets.append(button);
    }
    const submit = node("button", "Показать / обновить"); submit.type = "submit"; form.append(submit);
    const message = node("p"); message.setAttribute("role", "status");
    const summary = node("div", null, "training-sales__summary"), list = node("div"), products = node("div");
    const prev = node("button", "Назад"), next = node("button", "Далее"), pages = node("div", null, "training-sales__presets");
    prev.type = next.type = "button"; prev.onclick = () => { offset = Math.max(0, offset - 25); void load(); }; next.onclick = () => { offset += 25; void load(); }; pages.append(prev, next);
    section.append(presets, form, message, summary, list, pages, node("h3", "По каждому обучению · вся сохранённая история"), products);
    parent.prepend(section);
    form.onsubmit = event => { event.preventDefault(); offset = 0; void load(); };
    for (const input of [start, end]) input.onchange = () => { allTime = false; };
    for (const input of [search, buyer]) input.oninput = () => { clearTimeout(debounce); debounce = setTimeout(() => { offset = 0; void load(); }, 350); };
    async function load() {
      const version = ++generation; message.textContent = "Загружаем реальные покупки…"; submit.disabled = true;
      const params = new URLSearchParams({ timezone: zone.value, limit: "25", offset: String(offset), all_time: String(allTime) });
      for (const input of [search, buyer, product, status, ...(allTime ? [] : [start, end])]) if (input.value.trim()) params.set(input.name, input.value.trim());
      try {
        const data = await api.request(`/admin/training-analytics?${params}`);
        if (version !== generation) return;
        const money = value => `${Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} AF`;
        const stamp = value => new Intl.DateTimeFormat("ru-RU", { timeZone: data.timezone, dateStyle: "short", timeStyle: "medium" }).format(new Date(value));
        message.textContent = `${allTime ? "Вся сохранённая история" : `${start.value} — ${end.value}`} · ${data.timezone} · Найдено: ${data.total}`;
        const metrics = [["Сегодня", data.counts.today], ["7 дней", data.counts.week], ["30 дней", data.counts.month], ["Всё время", data.counts.all_time], ["Продажи за период", data.summary.paid_count], ["Сумма за период", money(data.summary.gross_af)], ["Возвраты этих покупок", money(data.summary.refund_af)], ["После возвратов", money(data.summary.net_af)], ["Уникальных покупателей", data.summary.unique_buyers], ["Без подтверждения", data.summary.unverified_count]];
        summary.replaceChildren(...metrics.map(([label, value]) => { const item = node("div"); item.append(node("strong", value), node("span", label)); return item; }));
        list.replaceChildren(...data.items.map(item => {
          const card = node("article", null, "training-sales__card");
          card.append(node("small", `Покупка №${item.number}`), node("h3", item.title), node("p", item.buyer_username ? `@${item.buyer_username}` : "Username отсутствует"), node("p", item.buyer_name), node("small", `Внутренний ID: ${item.buyer_id}`), node("p", stamp(item.purchased_at)), node("strong", money(item.amount_af)), node("p", `${item.payment_method === "af_balance" ? "Внутренний баланс AF" : "Telegram Stars → AF"} · ${paymentLabels[item.payment_status]}`), node("p", `${statusLabels[item.fulfillment_status] || item.fulfillment_status} · ${deliveryLabels[item.delivery_status] || item.delivery_status}`));
          if (Number(item.refund_af)) card.append(node("p", `Возврат: ${money(item.refund_af)} · ${stamp(item.refunded_at)}`));
          if (/^(https:\/\/t\.me\/[A-Za-z][A-Za-z0-9_]{4,31}|tg:\/\/user\?id=\d+)$/.test(item.profile_url || "")) { const link = node("a", "Открыть профиль"); link.href = item.profile_url; link.rel = "noopener noreferrer"; card.append(link); }
          return card;
        }));
        if (!data.items.length) list.append(node("p", "Покупок по этим фильтрам нет"));
        products.replaceChildren(...data.products.map(item => { const card = node("article", null, "training-sales__card"); card.append(node("strong", item.title), node("p", `Сегодня: ${item.today} · 7 дней: ${item.week} · 30 дней: ${item.month} · Всего: ${item.all_time}`), node("p", `Продажи: ${money(item.gross_af)} · Возвраты: ${money(item.refund_af)}`)); const button = node("button", "Покупки этого обучения"); button.type = "button"; button.onclick = () => { product.value = item.product_id; offset = 0; void load(); }; card.append(button); return card; }));
        prev.disabled = offset === 0; next.disabled = !data.has_more && !data.products_has_more;
        const help = node("details"), title = node("summary", "Как считаются показатели"); help.append(title, ...data.definitions.map(text => node("p", text))); products.append(help);
      } catch (error) { if (version === generation) { message.textContent = `Не удалось загрузить: ${error.message}. Нажмите «Показать / обновить».`; summary.replaceChildren(); list.replaceChildren(); products.replaceChildren(); } }
      finally { if (version === generation) submit.disabled = false; }
    }
    return { load };
  }
  root.AutoFlowTrainingSales = { mount, dateInZone };
})(window);
