(function (root) {
  "use strict";
  const paths = {
    save: '<path d="M6 3h12v18l-6-4-6 4Z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/>',
    share: '<path d="m14 3 7 7-7 7v-5C7 12 4 16 3 20c0-9 3-13 11-13Z"/>',
    engine: '<path d="M3 10H1v7h2m3-9V5h7v3h4l3 4h3v7h-5l-3 2H7l-3-4V8Zm2-5h4"/>',
    speed: '<path d="M4 19a10 10 0 1 1 16 0M12 3v3M4 7l2 2m14-2-2 2M2 13h3m14 0h3m-10 3 5-7"/>',
    time: '<path d="m13 2-9 12h7l-1 8 10-13h-7Z"/>',
    status: '<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Zm-5 10 3 3 7-7"/>',
    full: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
    chat: '<path d="M21 11c0 5-4 8-9 8H7l-4 3 1-6a8 8 0 0 1-2-5c0-5 4-8 10-8s9 3 9 8Z"/><path d="M7 11h.1M12 11h.1M17 11h.1"/>',
    offer: '<path d="m3 12 9-9h8v8l-9 10Zm12-5h.1"/>',
  };
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = paths[name] || paths.status; return svg;
  }
  function node(tag, text, className) { const el = document.createElement(tag); if (text != null) el.textContent = text; if (className) el.className = className; return el; }
  function create({ api, notify, title, formatNumber, mediaUrl, thumbnail }) {
    const get = id => document.getElementById(id);
    const page = document.querySelector('[data-view="listing-detail"]');
    const galleryHost = get("listingGallery"), otherTrack = get("listingOtherTrack");
    const save = get("listingSave"), share = get("listingShare");
    save.append(icon("save")); share.append(icon("share"));
    let current = null, track = null, gallerySignature = "", context = null, busy = false;
    let controller = null, sequence = 0, lightbox = null, restorePosition = null;
    const cache = new Map();
    const number = value => new Intl.NumberFormat("ru-RU").format(value);

    function gallery(host, urls, start = 0, fullscreen = false) {
      host.replaceChildren();
      const rail = node("div", null, "listing-gallery__track"); rail.tabIndex = 0; rail.setAttribute("aria-label", "Фотографии автомобиля");
      urls.forEach((url, index) => {
        const frame = node("div", null, "listing-gallery__frame");
        const image = node("img"); image.src = mediaUrl(url); image.alt = `Фотография автомобиля ${index + 1} из ${urls.length}`;
        image.loading = index === start ? "eager" : "lazy"; image.decoding = "async"; image.draggable = false;
        image.addEventListener("error", () => { image.hidden = true; frame.append(node("span", "Фото недоступно", "listing-gallery__missing")); }, { once: true });
        frame.append(image); rail.append(frame);
      });
      const controls = node("div", null, "listing-gallery__controls"), count = node("span");
      const dots = node("div", null, "listing-gallery__dots"); dots.hidden = urls.length < 2;
      dots.classList.toggle("listing-gallery__dots--many", urls.length > 5);
      const move = (index, smooth = true) => rail.scrollTo({ left: rail.clientWidth * index, behavior: smooth && !root.matchMedia("(prefers-reduced-motion: reduce)").matches ? "smooth" : "instant" });
      urls.forEach((_, index) => { const dot = node("button"); dot.type = "button"; dot.setAttribute("aria-label", `Фото ${index + 1}`); dot.onclick = () => move(index); dots.append(dot); });
      const currentIndex = () => Math.max(0, Math.min(urls.length - 1, Math.round(rail.scrollLeft / (rail.clientWidth || 1))));
      const sync = () => {
        const index = currentIndex(); count.textContent = `${index + 1} / ${urls.length}`;
        [...dots.children].forEach((dot, i) => { dot.setAttribute("aria-pressed", String(i === index)); });
      };
      rail.addEventListener("scroll", sync, { passive: true });
      rail.addEventListener("keydown", event => { if (["ArrowLeft", "ArrowRight"].includes(event.key)) { event.preventDefault(); move(Math.max(0, Math.min(urls.length - 1, currentIndex() + (event.key === "ArrowLeft" ? -1 : 1)))); } });
      const expand = node("button"); expand.type = "button"; expand.append(icon("full")); expand.setAttribute("aria-label", "Открыть фото на весь экран");
      expand.onclick = () => showFullscreen(urls, currentIndex()); expand.hidden = fullscreen;
      controls.append(count, expand); host.append(rail, dots, controls);
      if (!urls.length) { rail.append(node("div", "Фотографий пока нет", "listing-gallery__frame listing-gallery__missing")); controls.hidden = dots.hidden = true; }
      sync(); requestAnimationFrame(() => { move(start, false); sync(); });
      return { rail, index: currentIndex, move };
    }
    function showFullscreen(urls, index) {
      if (!urls.length || lightbox) return;
      const dialog = node("dialog", null, "listing-lightbox"); dialog.setAttribute("aria-label", "Фотографии автомобиля на весь экран");
      const close = node("button", "×", "listing-lightbox__close"); close.type = "button"; close.setAttribute("aria-label", "Закрыть фото"); close.onclick = () => dialog.close();
      const host = node("div", null, "listing-lightbox__gallery"); dialog.append(close, host); document.body.append(dialog);
      const overflow = document.body.style.overflow; document.body.style.overflow = "hidden";
      lightbox = dialog; dialog.addEventListener("close", () => { document.body.style.overflow = overflow; lightbox = null; dialog.remove(); }, { once: true });
      dialog.showModal(); gallery(host, urls, index, true);
    }
    function dismiss() { if (!lightbox) return false; lightbox.close(); return true; }
    function snapshot() { return { photoIndex: track?.index() || 0, otherScrollLeft: otherTrack.scrollLeft }; }
    function restore(position) {
      if (!position) return;
      restorePosition = position;
      requestAnimationFrame(() => { track?.move(position.photoIndex || 0, false); otherTrack.scrollLeft = position.otherScrollLeft || 0; });
    }
    function avatar(name, url) {
      const host = get("listingSellerAvatar"); host.replaceChildren();
      host.append(icon("user")); // Neutral fallback, never a fabricated user photo.
      if (url) {
        const img = node("img"); img.alt = ""; img.src = mediaUrl(url); img.referrerPolicy = "no-referrer";
        img.addEventListener("load", () => host.querySelector("svg")?.remove(), { once: true });
        img.addEventListener("error", () => img.remove(), { once: true }); host.append(img);
      }
      host.setAttribute("aria-label", name);
    }
    function remember() {
      cache.delete(current.id); cache.set(current.id, context);
      if (cache.size > 8) cache.delete(cache.keys().next().value);
    }
    function renderContext(data) {
      get("listingSellerName").textContent = data.name;
      get("listingSellerSales").textContent = `✓ ${number(data.completed_sales)} ${data.completed_sales % 10 === 1 && data.completed_sales % 100 !== 11 ? "успешная сделка" : data.completed_sales % 10 >= 2 && data.completed_sales % 10 <= 4 && !(data.completed_sales % 100 >= 12 && data.completed_sales % 100 <= 14) ? "успешные сделки" : "успешных сделок"}`;
      avatar(data.name, data.photo_url); get("listingSellerRetry").hidden = true;
      save.disabled = false; save.setAttribute("aria-pressed", String(data.saved_by_me)); save.setAttribute("aria-label", data.saved_by_me ? "Убрать из сохранённого" : "Сохранить объявление");
      get("listingOtherCars").hidden = !data.other_active_count;
      get("listingOtherCount").textContent = number(data.other_active_count);
      const previousLeft = otherTrack.scrollLeft;
      otherTrack.replaceChildren(...data.items.map(item => {
        const button = node("button", null, "listing-other-card"); button.type = "button"; button.dataset.openListing = item.id;
        const media = node("div", null, "listing-other-card__media");
        if (item.images?.[0]) { const img = node("img"); img.src = thumbnail(item.images[0]); img.alt = ""; img.loading = "lazy"; img.decoding = "async"; img.addEventListener("error", () => img.remove(), { once: true }); media.append(img); }
        const game = node("span", item.game_version === "car_parking_2" ? "CP2" : "CP1"); media.append(game);
        button.append(media, node("strong", title(item)), node("b", `${formatNumber(item.effective_price_af_coins ?? item.price_af_coins)} AF`)); return button;
      }));
      otherTrack.scrollLeft = restorePosition?.otherScrollLeft ?? previousLeft;
    }
    async function loadContext(append = false) {
      if (!current || busy) return;
      const id = current.id, version = sequence; busy = true; const offset = append ? context?.items.length || 0 : 0;
      get("listingOtherRetry").hidden = true;
      try {
        const data = await api.request(`/listings/${encodeURIComponent(id)}/seller-context?limit=12&offset=${offset}`, { signal: controller.signal, retries: 0 });
        if (version !== sequence || current?.id !== id) return;
        if (!Array.isArray(data.items) || !Number.isInteger(data.completed_sales) || !Number.isInteger(data.other_active_count)) throw Error("Не удалось загрузить информацию продавца");
        const previous = append ? context.items : [];
        const items = [...new Map([...previous, ...data.items].filter(item => item.id !== id && item.status === "active" && (item.product_kind || "car") === "car").map(item => [item.id, item])).values()];
        context = { ...data, items }; renderContext(context); remember();
      } catch (error) {
        if (version !== sequence || controller.signal.aborted) return;
        if (!context) { get("listingSellerSales").textContent = "Не удалось загрузить информацию"; get("listingSellerRetry").hidden = false; }
        else get("listingOtherRetry").hidden = false;
      } finally { if (version === sequence) busy = false; }
    }
    otherTrack.addEventListener("scroll", () => {
      if (context?.has_more && otherTrack.scrollLeft > 0 && otherTrack.scrollLeft + otherTrack.clientWidth >= otherTrack.scrollWidth - 80) void loadContext(true);
    }, { passive: true });
    ["pointerdown", "touchstart", "wheel"].forEach(event => otherTrack.addEventListener(event, () => { restorePosition = null; }, { passive: true }));
    get("listingSellerRetry").onclick = () => void loadContext(); get("listingOtherRetry").onclick = () => void loadContext(Boolean(context?.has_more));
    save.onclick = async () => {
      if (!current || !context || save.disabled) return;
      const id = current.id, saved = context.saved_by_me; save.disabled = true;
      try {
        await api.request(`/favorites/${encodeURIComponent(id)}`, { method: saved ? "DELETE" : "POST", retries: 0 });
        if (current?.id === id) { context.saved_by_me = !saved; renderContext(context); remember(); }
      } catch (error) { notify(error.message); }
      finally { if (current?.id === id) save.disabled = false; }
    };
    share.onclick = async () => {
      if (!current || share.disabled) return;
      const id = current.id, text = title(current); share.disabled = true;
      try {
        const result = await api.request(`/listings/${encodeURIComponent(id)}/share-link`, { retries: 0 });
        if (current?.id !== id) return;
        const url = new URL(result.url); if (url.origin !== "https://t.me" || url.searchParams.get("startapp") !== `listing_${id}`) throw Error("Не удалось получить ссылку объявления");
        const telegram = root.Telegram?.WebApp;
        if (telegram?.openTelegramLink) telegram.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(url.href)}&text=${encodeURIComponent(text)}`);
        else if (navigator.share) await navigator.share({ title: text, url: url.href });
        else { await navigator.clipboard.writeText(url.href); notify("Ссылка на объявление скопирована"); }
      } catch (error) { if (error.name !== "AbortError") notify(error.message); }
      finally { share.disabled = false; }
    };
    function leave() { dismiss(); controller?.abort(); sequence++; current = null; busy = false; }
    function render(listing) {
      const isCar = (listing.product_kind || "car") === "car";
      page.classList.toggle("listing-page--car", isCar); galleryHost.hidden = !isCar;
      get("listingDetailToolbar").hidden = get("listingSellerIdentity").hidden = !isCar;
      const actions = get("listingPageActions"), seller = page.querySelector(".listing-detail-seller");
      const chat = get("listingPageChat"), offer = get("listingPageOfferButton");
      const description = page.querySelector(".listing-detail-description"), specs = page.querySelector(".listing-detail-specs"), engagement = get("listingPageViews").parentElement;
      if (isCar) { description.before(specs); page.querySelector(".listing-page__price").append(engagement); }
      else description.after(specs, engagement);
      if (isCar && chat.parentElement !== seller) seller.append(chat, offer);
      if (!isCar && chat.parentElement !== actions) actions.append(chat, offer);
      if (!isCar) { leave(); get("listingOtherCars").hidden = true; return; }
      const signature = JSON.stringify([listing.id, listing.images]);
      if (signature !== gallerySignature) { gallerySignature = signature; track = gallery(galleryHost, Array.isArray(listing.images) ? listing.images : []); }
      if (current?.id === listing.id) { current = listing; return; }
      leave(); current = listing; controller = new AbortController(); restorePosition = null;
      requestAnimationFrame(() => { if (current?.id === listing.id && !restorePosition) track?.move(0, false); });
      otherTrack.replaceChildren(); otherTrack.scrollLeft = 0;
      context = cache.get(listing.id) || null;
      get("listingSellerName").textContent = "Продавец"; get("listingSellerSales").textContent = "Загрузка информации…";
      get("listingSellerRetry").hidden = true; get("listingOtherCars").hidden = true; save.disabled = true; avatar("Продавец", null);
      if (context) renderContext(context);
      void loadContext();
    }
    return { render, restore, snapshot, leave, dismiss, icon };
  }
  root.AutoFlowListingDetail = { create };
})(window);
