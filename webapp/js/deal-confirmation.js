// @ts-check
(function () {
  "use strict";
  /** @type {(() => void) | null} */
  let closeCurrent = null;
  /**
   * @template T
   * @param {DealConfirmationOptions<T>} options
   * @returns {Promise<T | null>}
   */
  function confirm({ seller, gameId, submit, haptic, copyId }) {
    const focusBefore = document.activeElement;
    const scrollY = window.scrollY;
    const previousBodyStyle = document.body.getAttribute("style");
    return new Promise(resolve => {
      let phase = "idle";
      // Ignore the second tap of the gesture that opened the dialog, including
      // when the new confirm button happens to appear under the original tap.
      const openingGuardUntil = Date.now() + 450;
      const dialog = document.createElement("dialog");
      dialog.className = "modal deal-confirmation";
      dialog.setAttribute("aria-labelledby", "dealConfirmTitle");
      dialog.setAttribute("aria-describedby", "dealConfirmText");
      dialog.setAttribute("aria-modal", "true");
      const mark = document.createElement("div");
      mark.className = "deal-confirmation__mark"; mark.textContent = "🚘"; mark.setAttribute("aria-hidden", "true");
      const title = document.createElement("h2"); title.id = "dealConfirmTitle";
      title.textContent = seller ? "Подтвердить передачу?" : "Автомобиль получен?";
      const text = document.createElement("p"); text.id = "dealConfirmText";
      text.textContent = seller
        ? "Вы действительно передали автомобиль покупателю на указанный им ID?"
        : "Подтвердите только в том случае, если автомобиль действительно получен на ваш ID.";
      dialog.append(mark, title, text);
      if (seller && gameId) {
        const recipient = document.createElement("div"); recipient.className = "deal-confirmation__recipient";
        const label = document.createElement("small"); label.textContent = "ID покупателя";
        const value = document.createElement("strong"); value.textContent = gameId;
        const copy = document.createElement("button"); copy.type = "button"; copy.textContent = "Скопировать";
        copy.addEventListener("click", async () => {
          const copied = await copyId(gameId, dialog);
          copy.textContent = copied ? "✓ ID скопирован" : "Не удалось скопировать";
        });
        recipient.append(label, value, copy); dialog.append(recipient);
      }
      const note = document.createElement("p"); note.className = "deal-confirmation__note";
      note.textContent = seller
        ? "После подтверждения покупатель получит уведомление и должен будет подтвердить получение автомобиля."
        : "После подтверждения сделка завершится, а средства будут начислены продавцу.";
      const status = document.createElement("p"); status.className = "deal-confirmation__status";
      status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
      const buttons = document.createElement("div"); buttons.className = "deal-confirmation__buttons";
      const cancel = document.createElement("button"); cancel.type = "button"; cancel.textContent = "Нет, вернуться"; cancel.autofocus = true;
      const accept = document.createElement("button"); accept.type = "button"; accept.className = "publish-button";
      const acceptLabel = seller ? "Да, передал" : "Да, получил"; accept.textContent = acceptLabel;
      accept.disabled = true;
      window.setTimeout(() => { if (phase === "idle") accept.disabled = false; }, 450);
      buttons.append(cancel, accept); dialog.append(note, status, buttons);
      /** @param {T | null} result */
      const finish = (result) => {
        if (phase === "closing") return;
        phase = "closing"; dialog.classList.add("is-closing");
        window.setTimeout(() => {
          dialog.close(); dialog.remove();
          closeCurrent = null;
          if (previousBodyStyle === null) document.body.removeAttribute("style");
          else document.body.setAttribute("style", previousBodyStyle);
          window.scrollTo(0, scrollY);
          if (focusBefore instanceof HTMLElement && focusBefore.isConnected) focusBefore.focus({ preventScroll: true });
          resolve(result);
        }, 200);
      };
      const dismiss = () => { if (phase === "idle") finish(null); };
      cancel.addEventListener("click", dismiss);
      dialog.addEventListener("cancel", event => { event.preventDefault(); dismiss(); });
      dialog.addEventListener("click", event => {
        const rect = dialog.getBoundingClientRect();
        if (Date.now() >= openingGuardUntil && event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dismiss();
      });
      accept.addEventListener("click", async () => {
        if (phase !== "idle" || Date.now() < openingGuardUntil) return;
        phase = "pending"; accept.disabled = true; cancel.disabled = true;
        dialog.setAttribute("aria-busy", "true"); dialog.classList.add("is-pending");
        status.textContent = "Сохраняем подтверждение…"; accept.textContent = "Подтверждаем…";
        try {
          const result = await submit();
          phase = "success"; dialog.classList.remove("is-pending"); dialog.classList.add("is-success");
          dialog.removeAttribute("aria-busy"); mark.textContent = "✓"; accept.textContent = "Готово";
          status.textContent = seller ? "Передача отмечена" : "Сделка завершена";
          haptic("success");
          window.setTimeout(() => finish(result), 800);
        } catch (_error) {
          phase = "idle"; accept.disabled = false; cancel.disabled = false;
          dialog.removeAttribute("aria-busy"); dialog.classList.remove("is-pending");
          status.textContent = seller ? "Не удалось подтвердить передачу. Попробуйте ещё раз." : "Не удалось подтвердить получение. Попробуйте ещё раз.";
          accept.textContent = acceptLabel; haptic("error");
        }
      });
      document.body.append(dialog);
      document.body.style.position = "fixed"; document.body.style.top = `-${scrollY}px`;
      document.body.style.width = "100%"; document.body.style.overflow = "hidden";
      closeCurrent = dismiss;
      dialog.showModal(); cancel.focus({ preventScroll: true }); haptic("open");
    });
  }

  window.AutoFlowDealConfirmation = {
    confirm,
    dismiss() {
      if (!closeCurrent) return false;
      closeCurrent();
      return true;
    },
  };
})();
