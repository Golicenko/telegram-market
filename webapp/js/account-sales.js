(function (root) {
  "use strict";
  const node = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; };
  function create({ api, notify, refresh, openCar, support, userId, reloadDeal, topup }) {
    let current = null, explained = false, savedOverflow = "";
    const dialogs = new Set();
    function modal(title) {
      const dialog = node("dialog", null, "modal account-modal");
      const heading = node("h2", title), close = button("×", () => dialog.close(), "ghost-button");
      close.setAttribute("aria-label", "Закрыть"); close.classList.add("account-modal__close");
      dialog.append(close, heading); document.body.append(dialog);
      if (!dialogs.size) savedOverflow = document.body.style.overflow;
      dialogs.add(dialog); document.body.style.overflow = "hidden"; current = dialog;
      const erase = () => dialog.querySelectorAll("input").forEach(field => { field.value = ""; });
      const nativeClose = dialog.close.bind(dialog);
      dialog.close = (...args) => { erase(); return nativeClose(...args); };
      dialog.addEventListener("cancel", event => { if (dialog.dataset.busy) event.preventDefault(); else erase(); });
      dialog.addEventListener("close", () => {
        erase(); dialogs.delete(dialog);
        dialog.querySelectorAll("video").forEach(video => { video.pause(); video.removeAttribute("src"); video.load(); });
        document.body.style.overflow = dialogs.size ? "hidden" : savedOverflow;
        if (current === dialog) current = [...dialogs].reverse().find(item => item.open) || null;
        dialog.remove();
      }, { once: true });
      dialog.showModal(); return dialog;
    }
    function button(text, action, cls = "ghost-button") { const el = node("button", text, cls); el.type = "button"; el.onclick = action; return el; }
    function dismiss() { if (!current) return false; if (!current.dataset.busy) current.close(); return true; }
    function prompt(title, message, label) {
      return new Promise(resolve => {
        const dialog = modal(title); dialog.append(node("p", message));
        const guard = Date.now() + 450;
        dialog.append(button("Отмена", () => dialog.close()), button(label, () => { if (Date.now() >= guard) { resolve(true); dialog.close(); } }, "publish-button"));
        dialog.addEventListener("close", () => resolve(false), { once: true });
      });
    }
    async function choose() {
      const dialog = modal("Что хотите продать?");
      dialog.append(button("🚗 Автомобиль — продать машину в Car Parking", () => { dialog.close(); openCar(); }));
      dialog.append(button("👤 Аккаунт — продать игровой аккаунт", () => { dialog.close(); void editor(); }, "publish-button"));
    }
    function field(form, title, type, name, options = {}) {
      const label = node("label", title), input = node(type === "textarea" ? "textarea" : "input");
      if (type !== "textarea") input.type = type;
      input.name = name; input.required = options.required !== false;
      Object.assign(input, options); label.append(input); form.append(label); return input;
    }
    async function editor(listing = null) {
      let rules;
      try { rules = await api.request("/account-publication-rules", { retries: 0 }); if (!rules.enabled) throw new Error("Продажа аккаунтов ещё не включена. Публикация автомобилей доступна как прежде."); }
      catch (error) { notify(error.message); return; }
      if (!explained) {
        explained = await prompt("Как работает автовыдача?", "Вы заранее указываете данные игрового аккаунта. После оплаты покупатель откроет их в защищённой карточке чата. Средства остаются под защитой до подтверждения или решения спора. Передавайте только свой аккаунт, без пароля от личной почты.", "Понятно, продолжить");
        if (!explained) return;
      }
      const dialog = modal(listing ? "Изменить аккаунт" : "Продать аккаунт"), form = node("form", null, "account-form");
      dialog.append(form);
      const gameLabel = node("label", "Игра"), game = node("select"); game.name = "game_version"; game.required = true;
      [["", "Выберите игру"], ["car_parking_1", "Car Parking 1"], ["car_parking_2", "Car Parking 2"]].forEach(([value, text]) => { const option = node("option", text); option.value = value; game.append(option); });
      game.value = listing?.game_version || ""; gameLabel.append(game); form.append(gameLabel);
      const photo = field(form, "Главная фотография аккаунта", "file", "cover", { required: !listing, accept: "image/*,.heic,.heif" });
      form.append(node("small", "Это изображение будет отображаться на карточке вашего аккаунта в Market"));
      const preview = node("img", null, "account-cover-preview"); preview.alt = "Предпросмотр главной фотографии"; preview.hidden = !listing?.images?.[0]; if (!preview.hidden) preview.src = listing.images[0]; form.append(preview);
      let previewUrl = null, uploadedCover = listing?.images?.[0] || null, videoId = listing?.video_asset_id || null;
      photo.onchange = () => { if (previewUrl) URL.revokeObjectURL(previewUrl); uploadedCover = null; if (photo.files[0]) { previewUrl = URL.createObjectURL(photo.files[0]); preview.src = previewUrl; preview.hidden = false; } };
      const video = field(form, "Видео аккаунта", "file", "video", { required: !videoId, accept: "video/mp4,video/quicktime,video/webm,.mp4,.m4v,.mov,.webm" });
      video.onchange = () => { videoId = null; };
      form.append(node("small", `Выберите видео из медиатеки и покажите содержимое аккаунта. MP4, MOV или WebM, до ${Math.floor(rules.video_max_bytes / 1024 / 1024)} МБ. Для совместимости с iPhone и Android рекомендуется MP4 H.264.`));
      form.append(node("p", "⚠️ Фото, видео и описание должны соответствовать аккаунту. Обман может привести к разбирательству, возврату по результатам проверки и блокировке.", "security-note"));
      const title = field(form, "Название объявления", "text", "title", { maxLength: 160, value: listing?.brand || "", placeholder: "Аккаунт CP2 — редкие автомобили" });
      const description = field(form, "Описание аккаунта", "textarea", "description", { maxLength: 5000, minLength: 5, value: listing?.description || "", placeholder: "Содержимое и особенности, без контактов и сторонней оплаты" });
      form.append(node("strong", "⚡ Только автоматическая выдача"));
      if (listing) form.append(node("small", "Для изменения заново укажите актуальные данные входа. Сохранённый пароль не загружается в форму."));
      const login = field(form, "Email или логин игрового аккаунта", "text", "login", { minLength: 3, maxLength: 320, autocomplete: "off", spellcheck: false });
      const password = field(form, "Пароль игрового аккаунта (не личной почты)", "password", "password", { maxLength: 256, autocomplete: "new-password" });
      form.append(button("👁 Показать пароль", event => { password.type = password.type === "password" ? "text" : "password"; event.currentTarget.textContent = password.type === "password" ? "👁 Показать пароль" : "👁 Скрыть пароль"; }));
      field(form, "Я владею аккаунтом и могу передать доступ", "checkbox", "owns_account");
      field(form, "Доступ к моему личному почтовому ящику не требуется", "checkbox", "no_personal_mail_required");
      const price = field(form, "Цена аккаунта, AF Coins", "number", "price_af_coins", { min: "1", step: "0.01", value: listing?.price_af_coins || "", inputMode: "decimal" });
      form.append(node("p", `Аккаунты: ${rules.free_limit} бесплатных места; дополнительная публикация — ${rules.price_af} AF. VIP: ${rules.vip_stars} ⭐ на ${rules.vip_hours} ч. после публикации.`, "security-note"));
      const status = node("p"); status.setAttribute("role", "status"); const submit = node("button", listing ? "Сохранить аккаунт" : "Опубликовать аккаунт", "publish-button"); submit.type = "submit"; form.append(status, submit);
      const requestId = root.crypto.randomUUID(); let busy = false;
      dialog.addEventListener("cancel", event => { if (busy) event.preventDefault(); });
      dialog.addEventListener("close", () => { if (previewUrl) URL.revokeObjectURL(previewUrl); uploadedCover = videoId = null; form.reset(); }, { once: true });
      form.onsubmit = async event => {
        event.preventDefault(); if (busy || !form.reportValidity()) return;
        busy = true; dialog.dataset.busy = "true"; submit.disabled = true; form.inert = true;
        dialog.querySelector(".account-modal__close").disabled = true;
        try {
          if (!uploadedCover) { status.textContent = "Загрузка фотографии…"; uploadedCover = (await api.upload(photo.files[0])).url; }
          if (!videoId) {
            const file = video.files[0]; if (!file) throw new Error("Выберите видео");
            const contentType = file.type || (/\.webm$/i.test(file.name) ? "video/webm" : /\.mov$/i.test(file.name) ? "video/quicktime" : "video/mp4");
            if (file.size > rules.video_max_bytes) throw new Error("Видео слишком большое. Выберите файл меньшего размера.");
            if (!["video/mp4", "video/quicktime", "video/webm"].includes(contentType)) throw new Error("Выберите видео MP4, MOV или WebM");
            const upload = await api.request("/account-videos", { method: "POST", body: JSON.stringify({ content_type: contentType, size_bytes: file.size }), retries: 0 });
            status.textContent = "Загрузка видео в хранилище…";
            const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 300000);
            const cancelUpload = button("Прервать загрузку", () => controller.abort()); dialog.append(cancelUpload);
            try {
              const options = { method: "PUT", body: file, headers: { "Content-Type": upload.content_type }, signal: controller.signal };
              if (upload.upload_transport === "miniapp") {
                // Same-origin volume uploads use the existing signed Mini App
                // request. Never forward its auth headers to an external S3 URL.
                if (!/^\/account-videos\/[a-f0-9-]+\/content$/.test(upload.upload_url)) throw new Error("Некорректный адрес загрузки");
                await api.request(upload.upload_url, { ...options, retries: 0, timeoutMs: 300000 });
              } else {
                const result = await fetch(upload.upload_url, { ...options, credentials: "omit", referrerPolicy: "no-referrer" });
                if (!result.ok) throw new Error("Видео не загрузилось");
              }
            }
            catch (_) { throw new Error(controller.signal.aborted ? "Загрузка видео прервана или истёк срок ожидания. Данные формы сохранены; можно повторить." : "Не удалось загрузить видео. Проверьте сеть и повторите."); }
            finally { clearTimeout(timeout); cancelUpload.remove(); }
            const checked = await api.request(`/account-videos/${upload.id}/complete`, { method: "POST", retries: 0 }); videoId = checked.id;
          }
          const payload = { client_request_id: requestId, game_version: game.value, title: title.value, description: description.value, image_url: uploadedCover, video_asset_id: videoId, login: login.value, password: password.value, price_af_coins: price.value, owns_account: form.elements.owns_account.checked, no_personal_mail_required: form.elements.no_personal_mail_required.checked };
          const path = listing ? `/account-products/${listing.id}` : "/account-products", method = listing ? "PATCH" : "POST";
          status.textContent = "Сохранение…";
          try { await api.request(path, { method, body: JSON.stringify(payload), retries: 0 }); }
          catch (error) {
            if (error.detail?.code !== "account_publication_confirmation") throw error;
            if (!await prompt("Лимит бесплатных объявлений", error.message, `Опубликовать за ${error.detail.price_af} AF`)) { status.textContent = "Публикация отменена. Средства не списаны."; return; }
            payload.publication_fee_confirmed = true;
            await api.request(path, { method, body: JSON.stringify(payload), retries: 0 });
          } finally { payload.login = payload.password = ""; }
          login.value = password.value = ""; dialog.close(); await refresh(); notify(listing ? "Аккаунт сохранён" : "Аккаунт опубликован");
        } catch (error) {
          status.textContent = error.message;
          if (error.detail?.code === "insufficient_af_coins") status.append(button("Пополнить баланс", () => { dialog.close(); topup(); }));
        } finally { busy = false; delete dialog.dataset.busy; submit.disabled = false; form.inert = false; const close = dialog.querySelector(".account-modal__close"); if (close) close.disabled = false; }
      };
    }
    async function openCredentials(deal) {
      const dialog = modal("🔐 Данные вашего аккаунта"), status = node("p", "Получение защищённых данных…"); dialog.append(status);
      let values = null;
      dialog.addEventListener("close", () => { if (values) values.login = values.password = ""; values = null; }, { once: true });
      try {
        values = await api.request(`/account-deals/${deal.id}/credentials`, { method: "POST", retries: 0, cache: "no-store" });
        if (!dialog.open) { values.login = values.password = ""; values = null; return; }
        status.remove();
        const form = node("div", null, "account-form"); dialog.append(form);
        for (const [key, label] of [["login", "Email / логин"], ["password", "Пароль"]]) {
          const input = field(form, label, key === "password" ? "password" : "text", key, { value: values[key], readOnly: true, autocomplete: "off", spellcheck: false });
          if (key === "password") form.append(button("Показать / скрыть", () => { input.type = input.type === "password" ? "text" : "password"; }));
          form.append(button("Скопировать", async () => { try { await navigator.clipboard.writeText(input.value); notify("Скопировано"); } catch (_) { input.focus(); input.select(); if (!document.execCommand("copy")) notify("Выделите и скопируйте значение вручную"); input.setSelectionRange(0, 0); } }));
        }
        dialog.append(node("p", "Проверьте соответствие аккаунта описанию и видео. После входа обязательно смените привязанную электронную почту, пароль и данные восстановления: продавец может попытаться вернуть доступ. Сделайте это до подтверждения получения. Будьте внимательны.", "security-note"), button("Закрыть", () => dialog.close()));
      } catch (error) { if (dialog.open) status.textContent = error.message; }
    }
    function card(deal, buyer) {
      const box = node("div", null, "account-delivery-card");
      box.append(node("strong", buyer ? "⚡ Ваш аккаунт готов!" : "⚡ Автовыдача выполнена"), node("p", buyer ? "Данные для входа доступны в защищённой карточке. Открытие не завершает сделку." : "Данные предоставлены покупателю. Ожидаем подтверждения получения."));
      if (buyer) box.append(button("🔐 Открыть аккаунт", () => void openCredentials(deal), "publish-button"));
      return box;
    }
    function panel(host, deal) {
      const buyer = deal.buyer_id === userId(); host.replaceChildren(); host.hidden = false;
      if (["transfer_in_progress", "disputed"].includes(deal.status)) host.append(card(deal, buyer));
      if (deal.status === "completed") { host.append(node("strong", "✅ Сделка завершена")); if (buyer) host.append(button("Открыть данные (в пределах срока хранения)", () => void openCredentials(deal))); }
      else if (deal.status === "cancelled") host.append(node("strong", "Сделка отменена. Доступ закрыт."));
      else host.append(node("p", `🔒 ${deal.price_af_coins} AF под защитой${deal.status === "disputed" ? " · спор на рассмотрении" : " до подтверждения получения"}`));
    }
    function controls(host, deal) {
      host.replaceChildren();
      if (deal.buyer_id === userId() && deal.status === "transfer_in_progress") host.append(button("Аккаунт получен", () => confirmReceipt(deal), "deal-confirm"));
      host.append(button("Обратиться в поддержку", () => support(deal.id), "deal-support"));
    }
    function confirmReceipt(deal) {
      const dialog = modal("Вы действительно получили аккаунт?");
      dialog.append(node("p", "Убедитесь, что аккаунт действительно соответствует описанию и видео."));
      dialog.append(node("p", "После входа обязательно смените привязанную электронную почту, пароль и данные восстановления: продавец может попытаться вернуть доступ к аккаунту. Сделайте это до подтверждения получения. Будьте внимательны.", "security-note"));
      const form = node("form", null, "account-form"), checked = field(form, "Я проверил доступ к аккаунту и подтверждаю получение", "checkbox", "checked_access");
      const submit = node("button", "Подтвердить получение", "publish-button"); submit.type = "submit"; submit.disabled = true;
      const status = node("p"); status.setAttribute("role", "status");
      const available = new Date(deal.transfer_started_at).getTime() + 60000;
      function update() { submit.disabled = !checked.checked || Date.now() < available || Boolean(dialog.dataset.busy); status.textContent = Date.now() < available ? `Сначала проверьте вход. Подтверждение через ${Math.ceil((available - Date.now()) / 1000)} сек.` : ""; }
      checked.onchange = update; const timer = setInterval(update, 1000); update();
      dialog.addEventListener("close", () => clearInterval(timer), { once: true });
      dialog.addEventListener("cancel", event => { if (dialog.dataset.busy) event.preventDefault(); });
      form.append(status, submit, button("Вернуться к проверке", () => { if (!dialog.dataset.busy) dialog.close(); })); dialog.append(form);
      form.onsubmit = async event => {
        event.preventDefault(); if (submit.disabled) return; dialog.dataset.busy = "true"; submit.disabled = true; submit.textContent = "Подтверждаем…";
        try { await api.request(`/account-deals/${deal.id}/confirm`, { method: "POST", body: JSON.stringify({ checked_access: true }), retries: 0 }); clearInterval(timer); submit.textContent = "✓ Получение подтверждено"; root.Telegram?.WebApp?.HapticFeedback?.notificationOccurred?.("success"); await reloadDeal(); setTimeout(() => dialog.close(), 750); }
        catch (error) { delete dialog.dataset.busy; clearInterval(timer); submit.textContent = "Подтвердить получение"; submit.disabled = !checked.checked; status.textContent = error.message; }
      };
    }
    const players = new Map();
    const timestamp = value => { const n = Math.max(0, Math.floor(Number(value) || 0)); return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`; };
    function pauseVideos() {
      for (const player of players.values()) { player.media?.pause(); player.controller?.abort(); }
    }
    document.addEventListener("visibilitychange", () => { if (document.hidden) pauseVideos(); });
    root.addEventListener("pagehide", pauseVideos);
    function video(host, listing) {
      const key = `${listing.id}:${listing.video_asset_id}`;
      if (players.get(host)?.key === key && listing.product_kind === "account") return;
      const old = players.get(host);
      if (old) { old.controller?.abort(); if (old.media) { old.media.pause(); old.media.removeAttribute("src"); old.media.load(); } players.delete(host); }
      host.replaceChildren(); host.hidden = listing.product_kind !== "account";
      if (host.hidden) return;
      const state = { key, controller: null, media: null }; players.set(host, state);
      const preview = button("▶ Смотреть", () => void load(), "account-video__preview");
      preview.setAttribute("aria-label", "Смотреть видео аккаунта");
      if (listing.images?.[0]) { const image = node("img"); image.src = listing.images[0]; image.alt = ""; image.loading = "lazy"; preview.prepend(image); }
      const label = node("h3", "Видео аккаунта"), status = node("p", "Нажмите, чтобы посмотреть содержимое аккаунта", "account-video__status"); status.setAttribute("role", "status");
      host.append(label, preview, status);
      async function load() {
        if (state.controller) return;
        const controller = new AbortController(); state.controller = controller;
        preview.disabled = true; status.textContent = "Загружаем видео…";
        const position = state.media?.currentTime || 0, speed = state.media?.playbackRate || 1;
        try {
          const result = await api.request(`/account-videos/${listing.video_asset_id}/play`, { retries: 0, signal: controller.signal });
          if (controller.signal.aborted || players.get(host) !== state || !host.isConnected) return;
          if (!state.media) buildPlayer();
          state.media.src = result.url; state.media.load();
          state.media.addEventListener("loadedmetadata", () => { if (position && Number.isFinite(state.media.duration)) state.media.currentTime = Math.min(position, state.media.duration); state.media.playbackRate = speed; }, { once: true });
          preview.hidden = true; status.textContent = "";
          try { await state.media.play(); } catch (_) { status.textContent = "Нажмите ▶ на плеере, чтобы начать просмотр"; }
        } catch (error) { if (!controller.signal.aborted && players.get(host) === state) { status.textContent = "Не удалось открыть видео. Проверьте сеть и попробуйте ещё раз."; retry.hidden = false; } }
        finally { if (state.controller === controller) state.controller = null; preview.disabled = false; }
      }
      const retry = button("Повторить загрузку", () => { retry.hidden = true; void load(); }); retry.hidden = true; host.append(retry);
      function buildPlayer() {
        const media = node("video"); state.media = media;
        media.controls = true; media.playsInline = true; media.preload = "metadata"; media.referrerPolicy = "no-referrer"; media.setAttribute("aria-label", "Видео содержимого аккаунта");
        const bar = node("div", null, "account-video__controls"), time = node("span", "0:00 / 0:00", "account-video__time");
        const toggle = button("▶", () => { if (media.paused) void media.play().catch(() => { status.textContent = "Нажмите ▶ на плеере"; }); else media.pause(); }); toggle.setAttribute("aria-label", "Воспроизвести видео");
        const seek = node("input"); seek.type = "range"; seek.min = "0"; seek.max = "0"; seek.step = ".1"; seek.value = "0"; seek.disabled = true; seek.setAttribute("aria-label", "Позиция видео");
        seek.oninput = () => { if (Number.isFinite(media.duration)) media.currentTime = Number(seek.value); };
        const speedLabel = node("label", "Скорость"), rate = node("select"); rate.setAttribute("aria-label", "Скорость видео");
        [0.5, 1, 1.25, 1.5, 2, 3, 5].forEach(value => { const option = node("option", `${value}×`); option.value = value; rate.append(option); }); rate.value = "1";
        rate.onchange = () => { const before = media.playbackRate; try { const value = Number(rate.value); media.playbackRate = value; if (media.playbackRate !== value) throw new Error(); status.textContent = ""; } catch (_) { media.playbackRate = before; rate.value = String(before); status.textContent = "Эта скорость недоступна на устройстве. Выберите другую."; } };
        media.addEventListener("ratechange", () => { rate.value = String(media.playbackRate); });
        const sync = () => { const ready = Number.isFinite(media.duration) && media.duration > 0; seek.disabled = !ready; seek.max = ready ? media.duration : 0; seek.value = media.currentTime || 0; time.textContent = `${timestamp(media.currentTime)} / ${ready ? timestamp(media.duration) : "—"}`; };
        ["timeupdate", "durationchange", "loadedmetadata"].forEach(name => media.addEventListener(name, sync));
        media.addEventListener("play", () => { toggle.textContent = "Ⅱ"; toggle.setAttribute("aria-label", "Пауза"); });
        media.addEventListener("pause", () => { toggle.textContent = "▶"; toggle.setAttribute("aria-label", "Воспроизвести видео"); });
        media.addEventListener("error", () => { status.textContent = "Видео не загрузилось или формат не поддерживается устройством. Попробуйте ещё раз."; retry.hidden = false; });
        speedLabel.append(rate); bar.append(toggle, seek, time, speedLabel); preview.after(media, bar);
      }
    }
    async function pin(listing) {
      try {
        const rules = await api.request("/account-publication-rules", { retries: 0 });
        if (!await prompt("VIP аккаунта", `Закрепить на ${rules.vip_hours} ч. за ${rules.vip_stars} Telegram Stars? Тариф автомобилей не меняется.`, `Оплатить ${rules.vip_stars} ⭐`)) return;
        const result = await api.request(`/account-products/${listing.id}/pin`, { method: "POST", body: JSON.stringify({ request_id: root.crypto.randomUUID() }), retries: 0 });
        if (typeof root.Telegram?.WebApp?.openInvoice !== "function") throw new Error("Откройте оплату внутри Telegram");
        root.Telegram.WebApp.openInvoice(result.invoice_url, async () => { await refresh(); notify("Статус закрепления обновлён с сервера. При задержке платежа обновите страницу объявления позже."); });
      } catch (error) { notify(error.message); }
    }
    return { choose, editor, dismiss, card, panel, controls, video, pauseVideos, pin };
  }
  root.AutoFlowAccountSales = { create };
})(window);
