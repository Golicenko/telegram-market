(function (root) {
  "use strict";
  const node = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; };
  function create({ api, notify, refresh, openCar, support, userId, reloadDeal, topup, showEditor, closeEditor }) {
    let current = null, savedOverflow = "";
    let draft = null;
    root.addEventListener("pagehide", () => { draft?.dispose(); draft = null; });
    const dialogs = new Set();
    function modal(title) {
      const dialog = node("dialog", null, "modal account-modal");
      const heading = node("h2", title), close = button("×", () => dialog.close(), "ghost-button");
      dialog.setAttribute("aria-label", title);
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
      dialog.append(button("🚗 Автомобиль — продать машину в Car Parking", () => { dialog.close(); openCar(); }, "publish-button account-sale-choice"));
      dialog.append(button("👤 Аккаунт — продать игровой аккаунт", () => { dialog.close(); void editor(); }, "publish-button account-sale-choice"));
    }
    function explainAutodelivery(rules) {
      const dialog = modal("Как работает автовыдача?"); dialog.classList.add("account-autodelivery-help");
      dialog.append(node("p", "Вы указываете email или логин и пароль игрового аккаунта. Маркет хранит их в зашифрованном виде — в объявлении они не видны."));
      dialog.append(node("p", "После оплаты покупатель открывает данные в чате сделки. Отправлять их вручную не нужно."));
      const days = Number(rules.secret_retention_days);
      const retention = Number.isSafeInteger(days) && days > 0
        ? `Через ${days} сут. после завершения сделки маркет автоматически удаляет сохранённые данные.`
        : "После завершения сделки маркет автоматически удаляет сохранённые данные по установленному сроку хранения.";
      dialog.append(node("p", `${retention} Пока открыт спор, данные сохраняются для его рассмотрения.`));
      dialog.append(button("Понятно", () => dialog.close(), "publish-button"));
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
      const scope = listing?.id || "new";
      if (draft?.dialog.dataset.busy && draft.scope !== scope) { notify("Дождитесь завершения публикации текущего аккаунта."); return; }
      if (draft?.scope === scope) { draft.updateRules(rules); showEditor?.(draft.dialog, listing); return; }
      if (draft && !await prompt("Сменить объявление?", "Незаполненный черновик останется только до закрытия Mini App. Очистить его и открыть другое объявление?", "Очистить черновик")) return;
      draft?.dispose();
      const dialog = node("div", null, "account-editor"), form = node("form", null, "account-form");
      // A normal app view, never a <dialog>; Back preserves this in-memory form.
      dialog.close = () => { draft?.dispose(); draft = null; closeEditor?.(); };
      if (showEditor) showEditor(dialog, listing); else document.body.append(dialog);
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
      const videoPreview = node("video", null, "account-cover-preview"); videoPreview.controls = true; videoPreview.playsInline = true; videoPreview.preload = "metadata"; videoPreview.hidden = true; form.append(videoPreview);
      const videoStatus = node("p", "Выберите видео из медиатеки"), progress = node("progress"); videoStatus.setAttribute("role", "status"); progress.max = 100; progress.value = 0; progress.hidden = true; form.append(videoStatus, progress);
      let videoUrl = null, videoTask = null, videoController = null, selectedVideo = null, videoError = null;
      let transfer = null;
      const cancelVideo = button("Отменить загрузку видео", () => { videoController?.abort(); if (transfer?.upload) void api.request(`/account-videos/${transfer.upload.id}/cancel`, { method: "POST", retries: 0 }).catch(() => {}); transfer = null; }); cancelVideo.hidden = true; form.append(cancelVideo);
      async function prepareVideo() {
        const file = video.files[0]; if (!file) return;
        if (videoTask && selectedVideo === file) return videoTask;
        videoController?.abort(); if (selectedVideo !== file) { if (transfer?.upload) void api.request(`/account-videos/${transfer.upload.id}/cancel`, { method: "POST", retries: 0 }).catch(() => {}); transfer = null; } const controller = new AbortController(); videoController = controller; selectedVideo = file; videoId = null; videoError = null;
        if (videoUrl) URL.revokeObjectURL(videoUrl); videoUrl = URL.createObjectURL(file); videoPreview.src = videoUrl; videoPreview.hidden = false;
        progress.hidden = false; progress.value = 0; cancelVideo.hidden = false; videoStatus.textContent = `Подготавливаем: ${file.name}`;
        videoTask = (async () => {
          const contentType = /^(video\/(mp4|webm|quicktime))$/.test(file.type) ? file.type : /\.webm$/i.test(file.name) ? "video/webm" : /\.mov$/i.test(file.name) ? "video/quicktime" : "video/mp4";
          if (file.size > rules.video_max_bytes) throw new Error("Видео слишком большое. Выберите файл меньшего размера.");
          if (!transfer) { const created = await api.request("/account-videos", { method: "POST", body: JSON.stringify({ content_type: contentType, size_bytes: file.size }), retries: 0, signal: controller.signal }); if (videoController !== controller || controller.signal.aborted) { void api.request(`/account-videos/${created.id}/cancel`, { method: "POST", retries: 0 }).catch(() => {}); return; } transfer = { upload: created, uploaded: false }; }
          const item = transfer, upload = item.upload;
          if (controller.signal.aborted) throw new Error("Загрузка отменена");
          {
            const known = await api.request(`/account-videos/${upload.id}/status`, { retries: 0, signal: controller.signal });
            if (known.status === "failed") { await api.request(`/account-videos/${upload.id}/retry`, { method: "POST", retries: 0, signal: controller.signal }); item.uploaded = true; }
            item.uploaded = item.uploaded || known.ready || ["queued", "processing"].includes(known.status);
          }
          if (!item.uploaded) await api.uploadAccountVideo(upload, file, { signal: controller.signal, onProgress(value) { if (videoController !== controller) return; progress.value = value; videoStatus.textContent = `Загружаем: ${value}%`; } });
          item.uploaded = true;
          videoStatus.textContent = "Проверяем видео…";
          let checked = await api.request(`/account-videos/${upload.id}/complete`, { method: "POST", retries: 0, signal: controller.signal });
          const deadline = Date.now() + 10 * 60 * 1000;
          while (!checked.ready) {
            if (controller.signal.aborted) throw new Error("Загрузка отменена");
            if (["failed", "cancelled", "expired"].includes(checked.status)) throw new Error(checked.error || "Обработка остановлена. Выберите видео или повторите загрузку.");
            if (Date.now() > deadline) throw new Error("Обработка продолжается. Повторите проверку позже.");
            videoStatus.textContent = checked.status === "processing" ? `Готовим совместимое видео 480p: ${checked.progress || 0}%` : "Видео в очереди обработки…";
            if (checked.status === "processing") progress.value = checked.progress || 0; else progress.removeAttribute("value");
            await new Promise(resolve => setTimeout(resolve, 1500));
            checked = await api.request(`/account-videos/${upload.id}/status`, { retries: 0, signal: controller.signal });
          }
          if (videoController !== controller || controller.signal.aborted) return;
          videoId = checked.id; progress.value = 100; videoStatus.textContent = "Видео готово ✓";
        })().catch(error => { if (videoController === controller) { videoError = error; videoStatus.textContent = controller.signal.aborted ? "Загрузка отменена. Поля сохранены; выберите видео или повторите." : error.message; } }).finally(() => { if (videoController === controller) { videoTask = null; cancelVideo.hidden = true; } });
        return videoTask;
      }
      video.onchange = () => { void prepareVideo(); };
      form.append(button("Повторить подготовку видео", () => { if (!videoTask) void prepareVideo(); }));
      form.append(node("small", `Выберите видео из медиатеки и покажите содержимое аккаунта. MP4, MOV или WebM, до ${Math.floor(rules.video_max_bytes / 1024 / 1024)} МБ. Для совместимости с iPhone и Android рекомендуется MP4 H.264.`));
      form.append(node("p", "⚠️ Фото, видео и описание должны соответствовать аккаунту. Обман может привести к разбирательству, возврату по результатам проверки и блокировке.", "security-note"));
      const title = field(form, "Название объявления", "text", "title", { maxLength: 160, value: listing?.brand || "", placeholder: "Аккаунт CP2 — редкие автомобили" });
      const description = field(form, "Описание аккаунта", "textarea", "description", { maxLength: 5000, minLength: 5, value: listing?.description || "", placeholder: "Содержимое и особенности, без контактов и сторонней оплаты" });
      const deliveryInfo = node("div", null, "account-autodelivery-info");
      const deliveryHelp = button("?", () => explainAutodelivery(rules), "account-autodelivery-info__help");
      deliveryHelp.setAttribute("aria-label", "Как работает автовыдача?"); deliveryHelp.setAttribute("aria-haspopup", "dialog");
      deliveryInfo.append(node("strong", "⚡ Только автоматическая выдача"), deliveryHelp); form.append(deliveryInfo);
      if (listing) form.append(node("small", "Для изменения заново укажите актуальные данные входа. Сохранённый пароль не загружается в форму."));
      const login = field(form, "Email или логин игрового аккаунта", "text", "login", { minLength: 3, maxLength: 320, autocomplete: "off", spellcheck: false });
      const password = field(form, "Пароль игрового аккаунта (не личной почты)", "password", "password", { maxLength: 256, autocomplete: "new-password" });
      form.append(button("👁 Показать пароль", event => { password.type = password.type === "password" ? "text" : "password"; event.currentTarget.textContent = password.type === "password" ? "👁 Показать пароль" : "👁 Скрыть пароль"; }));
      field(form, "Я владею аккаунтом и могу передать доступ", "checkbox", "owns_account");
      const price = field(form, "Цена аккаунта, AF Coins", "number", "price_af_coins", { min: "1", step: "0.01", value: listing?.price_af_coins || "", inputMode: "decimal" });
      const quota = node("div", null, "account-quota");
      function updateRules(value) {
        rules = value; const count = Number(rules.active_count || 0), limit = Number(rules.free_limit), fee = rules.price_af;
        quota.replaceChildren(node("strong", "Бесплатные объявления аккаунтов"), node("span", count > limit ? `${count} активных объявления` : `${count} из ${limit} использовано`), node("small", count < limit ? `Осталось бесплатно: ${limit - count}` : `Бесплатный лимит исчерпан. Следующая публикация — ${fee} AF`), node("small", `Бесплатный лимит: ${limit}. Каждая дополнительная публикация — ${fee} AF Coins.`));
      }
      updateRules(rules); form.append(quota);
      const vipLabel = node("label", null, "switch-row promotion-option account-vip"), vipCopy = node("span"), vip = node("input"); vip.type = "checkbox"; vip.name = "vip"; vip.checked = true;
      vipCopy.append(node("strong", "⭐ VIP-закрепление аккаунта"), node("small", `Закрепить объявление на ${rules.vip_hours} часа за ${rules.vip_stars} ⭐`)); vipLabel.append(vipCopy, vip, node("i")); if (!listing) form.append(vipLabel);
      const status = node("p"); status.setAttribute("role", "status"); const submit = node("button", listing ? "Сохранить аккаунт" : "Опубликовать аккаунт", "publish-button"); submit.type = "submit"; form.append(status, submit);
      const requestId = root.crypto.randomUUID(); let busy = false;
      const ownedDraft = { scope, dialog, updateRules, dispose() { videoController?.abort(); videoPreview.pause(); videoPreview.removeAttribute("src"); if (previewUrl) URL.revokeObjectURL(previewUrl); if (videoUrl) URL.revokeObjectURL(videoUrl); uploadedCover = videoId = null; form.reset(); dialog.remove(); } }; draft = ownedDraft;
      dialog.close = () => { ownedDraft.dispose(); if (draft === ownedDraft) draft = null; closeEditor?.(); };
      form.onsubmit = async event => {
        event.preventDefault(); if (busy || !form.reportValidity()) return;
        busy = true; dialog.dataset.busy = "true"; submit.disabled = true; form.querySelectorAll("input,textarea,select").forEach(input => { input.disabled = true; });
        try {
          if (!uploadedCover) { status.textContent = "Загрузка фотографии…"; uploadedCover = (await api.upload(photo.files[0])).url; }
          if (!videoId) {
            if (!video.files[0]) throw new Error("Выберите видео");
            status.textContent = "Ожидаем готовность видео…"; await (videoTask || prepareVideo());
            if (!videoId) throw videoError || new Error("Видео ещё не готово");
          }
          const payload = { client_request_id: requestId, game_version: game.value, title: title.value, description: description.value, image_url: uploadedCover, video_asset_id: videoId, login: login.value, password: password.value, price_af_coins: price.value, owns_account: form.elements.owns_account.checked };
          const path = listing ? `/account-products/${listing.id}` : "/account-products", method = listing ? "PATCH" : "POST";
          status.textContent = "Сохранение…";
          let saved;
          try { saved = await api.request(path, { method, body: JSON.stringify(payload), retries: 0 }); }
          catch (error) {
            if (error.detail?.code !== "account_publication_confirmation") throw error;
            if (!await prompt("Лимит бесплатных объявлений", error.message, `Опубликовать за ${error.detail.price_af} AF`)) { status.textContent = "Публикация отменена. Средства не списаны."; return; }
            payload.publication_fee_confirmed = true;
            saved = await api.request(path, { method, body: JSON.stringify(payload), retries: 0 });
          } finally { payload.login = payload.password = ""; }
          const wantsVip = !listing && vip.checked;
          login.value = password.value = ""; ownedDraft.dispose(); if (draft === ownedDraft) draft = null;
          try { await refresh(); } catch (_) { /* Publication is already committed. */ }
          closeEditor?.(saved); notify(listing ? "Аккаунт сохранён" : "Аккаунт опубликован");
          if (wantsVip && saved?.id) await pin(saved, true);
        } catch (error) {
          status.textContent = error.message;
          if (error.detail?.code === "insufficient_af_coins") status.append(button("Пополнить баланс", () => { topup(); }));
        } finally { busy = false; delete dialog.dataset.busy; submit.disabled = false; form.querySelectorAll("input,textarea,select").forEach(input => { input.disabled = false; }); }
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
    function panel(host, deal) {
      const buyer = deal.buyer_id === userId(); host.replaceChildren(); host.hidden = false; host.classList.add("account-chat-access");
      if (deal.status === "completed") host.append(node("strong", "✅ Сделка завершена"));
      if (deal.status === "cancelled") { host.append(node("strong", "Сделка отменена. Доступ закрыт.")); return; }
      if (buyer && ["transfer_in_progress", "disputed", "completed"].includes(deal.status)) host.append(button("🔐 Открыть аккаунт", () => void openCredentials(deal), "publish-button"));
      else if (deal.status === "transfer_in_progress") host.append(node("strong", "Ожидаем подтверждения покупателя"));
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
      draft?.dialog.querySelectorAll("video").forEach(media => media.pause());
    }
    document.addEventListener("visibilitychange", () => { if (document.hidden) pauseVideos(); });
    root.addEventListener("pagehide", pauseVideos);
    function video(host, listing) {
      const key = `${listing.id}:${listing.video_asset_id}`;
      const existing = players.get(host);
      if (existing?.key === key && listing.product_kind === "account") { existing.select(existing.onVideo); return; }
      const old = players.get(host);
      if (old) { old.controller?.abort(); if (old.media) { old.media.pause(); old.media.removeAttribute("src"); old.media.load(); } if (old.swipeArea) { old.swipeArea.ontouchstart = null; old.swipeArea.ontouchend = null; } players.delete(host); }
      host.replaceChildren(); host.hidden = listing.product_kind !== "account";
      const gallery = host.closest(".listing-page__media"); gallery?.classList.toggle("account-media", !host.hidden);
      if (host.hidden) return;
      const state = { key, controller: null, media: null, onVideo: false }; players.set(host, state);
      let cover = gallery?.querySelector("#listingPageImage");
      if (!cover) { cover = node("img", null, "account-gallery-photo"); cover.alt = "Фотография аккаунта"; if (listing.images?.[0]) cover.src = listing.images[0]; host.append(cover); }
      const surface = node("div", null, "account-gallery-video"), nav = node("div", null, "account-gallery-nav"), count = node("span", "1 / 2"); surface.hidden = true;
      const photoTab = button("Фото", () => select(false)), videoTab = button("Видео", () => select(true)); nav.append(photoTab, count, videoTab); host.append(surface, nav);
      function select(isVideo) { state.onVideo = isVideo; cover.hidden = isVideo; surface.hidden = !isVideo; count.textContent = isVideo ? "2 / 2" : "1 / 2"; photoTab.setAttribute("aria-pressed", String(!isVideo)); videoTab.setAttribute("aria-pressed", String(isVideo)); if (!isVideo) { state.media?.pause(); state.controller?.abort(); } }
      state.select = select;
      select(false);
      let touchX = null, touchY = null;
      const swipeArea = gallery || host;
      state.swipeArea = swipeArea;
      swipeArea.ontouchstart = event => { if (event.target.closest("input,select,button,video")) return; touchX = event.changedTouches[0].clientX; touchY = event.changedTouches[0].clientY; };
      swipeArea.ontouchend = event => { if (touchX == null) return; const dx = event.changedTouches[0].clientX - touchX, dy = event.changedTouches[0].clientY - touchY; if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy)) select(dx < 0); touchX = null; };
      const preview = button("▶ Смотреть", () => void load(), "account-video__preview");
      preview.setAttribute("aria-label", "Смотреть видео аккаунта");
      const status = node("p", "Нажмите ▶ для просмотра", "account-video__status"); status.setAttribute("role", "status");
      surface.append(preview, status);
      async function load() {
        if (state.controller) return;
        const controller = new AbortController(); state.controller = controller;
        preview.disabled = true; status.textContent = "Загружаем видео…";
        const position = state.media?.currentTime || 0, speed = state.media?.playbackRate || 1;
        try {
          const result = await api.request(`/account-videos/${listing.video_asset_id}/play`, { retries: 0, signal: controller.signal });
          if (controller.signal.aborted || !state.onVideo || players.get(host) !== state || !host.isConnected) return;
          if (!state.media) buildPlayer();
          state.media.src = result.url; state.media.load();
          state.media.addEventListener("loadedmetadata", () => { if (position && Number.isFinite(state.media.duration)) state.media.currentTime = Math.min(position, state.media.duration); state.media.playbackRate = speed; }, { once: true });
          preview.hidden = true; status.textContent = "";
          try { await state.media.play(); } catch (_) { status.textContent = "Нажмите ▶ на плеере, чтобы начать просмотр"; }
        } catch (error) { if (!controller.signal.aborted && players.get(host) === state) { status.textContent = "Не удалось открыть видео. Проверьте сеть и попробуйте ещё раз."; retry.hidden = false; } }
        finally { if (state.controller === controller) state.controller = null; preview.disabled = false; }
      }
      const retry = button("Повторить загрузку", () => { retry.hidden = true; void load(); }); retry.hidden = true; surface.append(retry);
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
    async function pin(listing, alreadyConfirmed = false) {
      try {
        const rules = await api.request("/account-publication-rules", { retries: 0 });
        if (!alreadyConfirmed && !await prompt("VIP аккаунта", `Закрепить на ${rules.vip_hours} ч. за ${rules.vip_stars} Telegram Stars? Тариф автомобилей не меняется.`, `Оплатить ${rules.vip_stars} ⭐`)) return;
        if (typeof root.Telegram?.WebApp?.openInvoice !== "function") throw new Error("Откройте оплату внутри Telegram");
        const result = await api.request(`/account-products/${listing.id}/pin`, { method: "POST", body: JSON.stringify({ request_id: root.crypto.randomUUID() }), retries: 0 });
        root.Telegram.WebApp.openInvoice(result.invoice_url, async status => { try { const receipt = await api.request(`/account-pins/${result.id}`, { retries: 0 }); await refresh(); notify(receipt.status === "completed" ? "Аккаунт закреплён" : status === "cancelled" || status === "failed" ? "Аккаунт опубликован без VIP. Закрепление можно оплатить позже." : "Проверяем оплату закрепления. Повторно платить не нужно."); } catch (_) { notify("Объявление опубликовано. Статус VIP можно проверить позже в профиле."); } });
      } catch (error) { notify(error.message); }
    }
    return { choose, editor, dismiss, panel, controls, video, pauseVideos, pin };
  }
  root.AutoFlowAccountSales = { create };
})(window);
