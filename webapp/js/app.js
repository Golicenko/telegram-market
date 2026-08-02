(function () {
  "use strict";

  const api = window.AutoFlowApi;
  const telegram = window.Telegram?.WebApp || null;
  const state = {
    currentView: "market",
    previousView: "market",
    listingMode: "regular",
    me: null,
    regular: [],
    unique: [],
    accounts: [],
    cart: [],
    advertisement: null,
    supportTickets: [],
    profile: null,
    catalog: { brands: [] },
    photoFiles: [],
    currentConversation: null,
    editingListingId: null,
    messages: [],
    unreadConversations: [],
    totalUnread: 0,
    messagePollingId: null,
    serverAvailable: true,
  };

  const elements = {
    shell: document.querySelector(".app-shell"),
    views: [...document.querySelectorAll("[data-view]")],
    navButtons: [...document.querySelectorAll("[data-nav-target]")],
    marketCars: document.getElementById("marketCars"),
    uniqueCars: document.getElementById("uniqueCars"),
    marketEmpty: document.getElementById("marketEmptyState"),
    uniqueEmpty: document.getElementById("uniqueEmptyState"),
    accountCards: document.getElementById("accountCards"),
    accountsEmpty: document.getElementById("accountsEmptyState"),
    brandFilter: document.getElementById("brandFilter"),
    modelFilter: document.getElementById("modelFilter"),
    priceFilter: document.getElementById("priceFilter"),
    powerFilter: document.getElementById("powerFilter"),
    speedFilter: document.getElementById("speedFilter"),
    extraFilters: document.getElementById("extraFilters"),
    extraFiltersButton: document.getElementById("extraFiltersButton"),
    carForm: document.getElementById("carForm"),
    carPhotos: document.getElementById("carPhotos"),
    photoPreview: document.getElementById("photoPreview"),
    brandInput: document.getElementById("brandInput"),
    modelInput: document.getElementById("modelInput"),
    priceInput: document.getElementById("priceInput"),
    cartList: document.getElementById("cartList"),
    cartEmpty: document.getElementById("cartEmptyState"),
    cartSummary: document.getElementById("cartSummary"),
    infoModal: document.getElementById("infoModal"),
    toast: document.getElementById("toast"),
    paymentResult: document.getElementById("paymentResult"),
    profileActive: document.getElementById("profileActiveCars"),
    profileSold: document.getElementById("profileSoldCars"),
    profilePurchases: document.getElementById("profilePurchaseCars"),
    history: document.getElementById("operationHistory"),
    withdrawalHistory: document.getElementById("withdrawalHistory"),
    activeDeals: document.getElementById("activeDeals"),
    conversationList: document.getElementById("conversationList"),
    dealMessages: document.getElementById("dealMessages"),
    dealControls: document.getElementById("dealControls"),
    offerPanel: document.getElementById("offerPanel"),
    chatListing: document.getElementById("chatListing"),
    chatForm: document.getElementById("chatForm"),
    withdrawForm: document.getElementById("withdrawForm"),
    adminWithdrawals: document.getElementById("adminWithdrawals"),
    adminUsers: document.getElementById("adminUsers"),
    adminListings: document.getElementById("adminListings"),
    adminDeals: document.getElementById("adminDeals"),
    adminUserHistory: document.getElementById("adminUserHistory"),
    marketAdvertisement: document.getElementById("marketAdvertisement"),
    marketAdvertisementImage: document.getElementById("marketAdvertisementImage"),
    supportForm: document.getElementById("supportForm"),
    supportTickets: document.getElementById("supportTickets"),
    adminSupportTickets: document.getElementById("adminSupportTickets"),
    advertisementForm: document.getElementById("advertisementForm"),
    advertisementPreview: document.getElementById("advertisementPreview"),
    floatingChatButton: document.getElementById("floatingChatButton"),
    chatUnreadBadge: document.getElementById("chatUnreadBadge"),
    chatNotification: document.getElementById("chatNotification"),
    chatNotificationText: document.getElementById("chatNotificationText"),
    successOverlay: document.getElementById("successOverlay"),
    successTitle: document.getElementById("successTitle"),
    successText: document.getElementById("successText"),
  };

  initTelegram();
  bindEvents();
  bootstrap();

  function initTelegram() {
    if (!telegram) return;
    telegram.ready();
    telegram.expand();
    if (typeof telegram.isVersionAtLeast !== "function" || telegram.isVersionAtLeast("6.1")) {
      telegram.setHeaderColor?.("#030912");
      telegram.setBackgroundColor?.("#030912");
    }
  }

  function bindEvents() {
    document.addEventListener("click", handleClick);
    document.getElementById("infoButton").addEventListener("click", () => openDialog(elements.infoModal));
    document.getElementById("settingsButton").addEventListener("click", () => notify("Настройки появятся в следующей версии"));
    elements.extraFiltersButton.addEventListener("click", toggleExtraFilters);
    document.getElementById("resetFiltersButton").addEventListener("click", resetFilters);
    document.getElementById("applyFiltersButton").addEventListener("click", renderListings);
    [elements.brandFilter, elements.modelFilter, elements.priceFilter].forEach((control) => control.addEventListener("change", renderListings));
    elements.brandInput.addEventListener("input", updateBrandSuggestions);
    elements.modelInput.addEventListener("input", updateModelSuggestions);
    elements.carPhotos.addEventListener("change", previewPhotos);
    elements.carForm.addEventListener("submit", submitListing);
    document.getElementById("checkoutButton").addEventListener("click", checkout);
    document.getElementById("topupForm").addEventListener("submit", requestStarInvoice);
    elements.chatForm.addEventListener("submit", sendChatMessage);
    elements.withdrawForm.addEventListener("submit", createWithdrawal);
    document.getElementById("accountDraftForm").addEventListener("submit", submitAccountListing);
    elements.supportForm.addEventListener("submit", submitSupportTicket);
    elements.advertisementForm.addEventListener("submit", submitAdvertisement);
    document.getElementById("deleteAdvertisementButton").addEventListener("click", deleteAdvertisement);
    document.getElementById("balanceAdjustmentForm").addEventListener("submit", createBalanceAdjustment);
    document.getElementById("adminUserSearch").addEventListener("submit", searchAdminUsers);
    elements.floatingChatButton.addEventListener("click", openFloatingChat);
  }

  async function bootstrap() {
    try {
      const [catalog, me, regular, unique, accounts, cart, profile, advertisement] = await Promise.all([
        fetch("data/vehicle_catalog.json").then((response) => response.json()),
        api.request("/me"),
        api.request("/listings?type=regular"),
        api.request("/listings?type=unique"),
        api.request("/accounts"),
        api.request("/cart"),
        api.request("/profile"),
        api.request("/advertisement"),
      ]);
      state.catalog = catalog;
      state.me = me;
      state.regular = regular;
      state.unique = unique;
      state.accounts = accounts;
      state.cart = cart;
      state.profile = profile;
      state.advertisement = advertisement;
      state.serverAvailable = true;
     applyRole();
     renderUser();
     updateFilterOptions();
     renderAll();
     updateFloatingChatVisibility();
     startMessagePolling();
    } catch (error) {
  state.serverAvailable = false;
  renderAll();
  updateFloatingChatVisibility();
  showServerState(error);
}
  }

  async function refreshMarketplace() {
    if (!state.serverAvailable) return;
    const [regular, unique, accounts, cart, profile, me, advertisement] = await Promise.all([
      api.request("/listings?type=regular"),
      api.request("/listings?type=unique"),
      api.request("/accounts"),
      api.request("/cart"),
      api.request("/profile"),
      api.request("/me"),
      api.request("/advertisement"),
    ]);
    state.regular = regular;
    state.unique = unique;
    state.accounts = accounts;
    state.cart = cart;
    state.profile = profile;
    state.me = me;
    state.advertisement = advertisement;
    applyRole();
    renderUser();
    updateFilterOptions();
    renderAll();
  }

  function handleClick(event) {
    const target = event.target;
    const navButton = target.closest("[data-nav-target]");
    if (navButton) return void navigate(navButton.dataset.navTarget);
    if (target.closest("[data-open-add]")) return void openListingForm("regular");
    if (target.closest("[data-open-unique]")) return void openListingForm("unique");
    if (target.closest("[data-open-account]")) return void openAdminAccountDraft();
    if (target.closest("[data-open-cart]")) return void openSecondary("cart");
    if (target.closest("[data-open-topup]")) return void openSecondary("topup");
    if (target.closest("[data-open-withdraw]")) return void openSecondary("withdraw");
    if (target.closest("[data-open-support]")) return void openSupport();
    if (target.closest("[data-open-admin]")) return void openAdminPanel();
    if (target.closest("[data-open-frozen]")) return void openFrozenDeals();
    if (target.closest("[data-open-info]")) return void openDialog(elements.infoModal);
    const topupAmount = target.closest("[data-topup-amount]");
    if (topupAmount) return void (document.getElementById("topupAmount").value = topupAmount.dataset.topupAmount);
    if (target.closest("[data-ad-banner]") && !state.advertisement?.link_url) {
      event.preventDefault();
      return void notify("Для баннера не указана ссылка");
    }
    if (target.closest("[data-back]")) return void navigate(state.previousView || "market");

    const closeDialog = target.closest("[data-close-dialog]");
    if (closeDialog) return void document.getElementById(closeDialog.dataset.closeDialog).close();
    const preset = target.closest("[data-price]");
    if (preset) return void selectPrice(preset);
    const cartToggle = target.closest("[data-cart-toggle]");
    if (cartToggle) return void toggleCart(cartToggle.dataset.cartToggle);
    const buyNow = target.closest("[data-buy-now]");
    if (buyNow) return void buyNowFlow(buyNow.dataset.buyNow);
    const chatListing = target.closest("[data-chat-listing]");
    if (chatListing) return void startConversation(chatListing.dataset.chatListing);
    const editListingButton = target.closest("[data-edit-listing]");
    if (editListingButton) return void editListing(editListingButton.dataset.editListing);
    const deleteListingButton = target.closest("[data-delete-listing]");
    if (deleteListingButton) return void deleteListing(deleteListingButton.dataset.deleteListing);
    const promoteListingButton = target.closest("[data-promote-listing]");
    if (promoteListingButton) return void promoteListing(promoteListingButton.dataset.promoteListing);
    const openListingButton = target.closest("[data-open-listing]");
    if (openListingButton) return void openListingDetails(openListingButton.dataset.openListing);
    const cartRemove = target.closest("[data-cart-remove]");
    if (cartRemove) return void removeFromCart(cartRemove.dataset.cartRemove);
    const profileTab = target.closest("[data-profile-tab]");
    if (profileTab) return void switchProfileTab(profileTab.dataset.profileTab);
    const profileSection = target.closest("[data-profile-section]");
    if (profileSection) return void toggleProfileSection(profileSection.dataset.profileSection);
    const conversationButton = target.closest("[data-open-conversation]");
    if (conversationButton) {
      return void openConversation(conversationButton.dataset.openConversation);
    }

    const hideConversationButton = target.closest("[data-hide-conversation]");
    if (hideConversationButton) {
      return void hideConversation(
        hideConversationButton.dataset.hideConversation
      );
    }

    const dealAction = target.closest("[data-deal-action]");
    if (dealAction) return void runDealAction(dealAction.dataset.dealAction);
    const adminWithdrawal = target.closest("[data-withdrawal-action]");
    if (adminWithdrawal) return void adminWithdrawalAction(adminWithdrawal);
    const cancelWithdrawal = target.closest("[data-cancel-withdrawal]");
    if (cancelWithdrawal) return void cancelOwnWithdrawal(cancelWithdrawal.dataset.cancelWithdrawal);
    const financialHistory = target.closest("[data-financial-history]");
    if (financialHistory) return void loadAdminFinancialHistory(financialHistory.dataset.financialHistory);
    const offerAction = target.closest("[data-offer-action]");
    if (offerAction) return void runOfferAction(offerAction);
    if (target.closest("[data-new-offer]")) return void createOffer();
    const accountDelete = target.closest("[data-delete-account]");
    if (accountDelete) return void deleteAccountListing(accountDelete.dataset.deleteAccount);
    const adminTab = target.closest("[data-admin-tab]");
    if (adminTab) return void switchAdminTab(adminTab.dataset.adminTab);
    const userAction = target.closest("[data-admin-user-action]");
    if (userAction) return void adminUserAction(userAction);
    const listingAction = target.closest("[data-admin-listing-action]");
    if (listingAction) return void adminListingAction(listingAction);
    const resolveAction = target.closest("[data-resolve-deal]");
    if (resolveAction) return void resolveAdminDeal(resolveAction);
    const supportReply = target.closest("[data-support-reply]");
    if (supportReply) return void replySupportTicket(supportReply.dataset.supportReply, supportReply.dataset.adminReply === "true");
    const supportStatus = target.closest("[data-support-status]");
    if (supportStatus) return void setSupportTicketStatus(supportStatus.dataset.ticketId, supportStatus.dataset.supportStatus);
  }

  async function navigate(viewName) {
    const next = elements.views.find((view) => view.dataset.view === viewName);
    if (!next) return;
    state.currentView = viewName;
    updateFloatingChatVisibility();
    elements.views.forEach((view) => {
      const active = view === next;
      view.hidden = !active;
      view.classList.toggle("is-active", active);
    });
    const navView = ["add", "cart", "deal-chat"].includes(viewName) ? "market" : ["topup", "withdraw"].includes(viewName) ? "profile" : ["admin", "support"].includes(viewName) ? "more" : viewName;
    elements.navButtons.forEach((button) => {
      const active = button.dataset.navTarget === navView;
      button.classList.toggle("is-active", active);
      active ? button.setAttribute("aria-current", "page") : button.removeAttribute("aria-current");
    });
    elements.shell.classList.toggle("is-focused", ["add", "topup", "cart", "profile", "deal-chat", "withdraw", "support", "account-draft", "admin"].includes(viewName));
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (state.serverAvailable && ["market", "unique", "accounts", "profile", "cart"].includes(viewName)) {
      try { await refreshMarketplace(); } catch (error) { notify(error.message); }
    }
  }
async function refreshUnreadMessages() {
  if (!state.serverAvailable || document.hidden) return;

  try {
    const summary = await api.request("/conversations/unread-summary");

    const previousTotal = state.totalUnread;

    state.totalUnread = Number(summary.total_unread || 0);
    state.unreadConversations = summary.conversations || [];

    renderUnreadBadge();

    if (state.totalUnread > previousTotal) {
      showNewMessageNotification();
    }

    if (
      state.currentView === "deal-chat" &&
      state.currentConversation?.id
    ) {
      await refreshOpenConversation();
    }
  } catch (error) {
    console.error("Не удалось обновить сообщения", error);
  }
}

function renderUnreadBadge() {
  const count = state.totalUnread;

  elements.chatUnreadBadge.textContent =
    count > 99 ? "99+" : String(count);

  elements.chatUnreadBadge.hidden = count === 0;
}

function showNewMessageNotification() {
  elements.chatNotificationText.textContent =
    state.totalUnread === 1
      ? "Вам пришло новое сообщение"
      : `У вас ${state.totalUnread} непрочитанных сообщений`;

  elements.chatNotification.hidden = false;

  window.clearTimeout(showNewMessageNotification.timeoutId);

  showNewMessageNotification.timeoutId = window.setTimeout(() => {
    elements.chatNotification.hidden = true;
  }, 4000);
}

async function refreshOpenConversation() {
  const conversationId = state.currentConversation?.id;

  if (!conversationId) return;

  const messages = await api.request(
    `/conversations/${conversationId}/messages`
  );

  const oldLastMessageId = state.messages.at(-1)?.id;
  const newLastMessageId = messages.at(-1)?.id;

  if (oldLastMessageId !== newLastMessageId) {
    state.messages = messages;
    renderConversation();
  }

  await markConversationRead(conversationId);
}

async function markConversationRead(conversationId) {
  await api.request(
    `/conversations/${conversationId}/read`,
    { method: "POST" }
  );

  state.unreadConversations =
    state.unreadConversations.filter(
      (item) => item.conversation_id !== conversationId
    );

  state.totalUnread = state.unreadConversations.reduce(
    (total, item) => total + Number(item.unread_count || 0),
    0
  );

  renderUnreadBadge();
}

function startMessagePolling() {
  if (state.messagePollingId) {
    window.clearInterval(state.messagePollingId);
  }

  refreshUnreadMessages();

  state.messagePollingId = window.setInterval(
    refreshUnreadMessages,
    2000
  );
}
  
function updateFloatingChatVisibility() {
  const visibleViews = ["market", "unique", "accounts", "profile"];
  const shouldShow = visibleViews.includes(state.currentView);

  elements.floatingChatButton.hidden = !shouldShow;
}

async function openFloatingChat() {
  elements.chatNotification.hidden = true;

  if (state.unreadConversations.length === 1) {
    await openConversation(
      state.unreadConversations[0].conversation_id
    );
    return;
  }

  await navigate("profile");
  switchProfileTab("chats");
}
  function openSecondary(viewName) {
    state.previousView = ["add", "topup", "cart", "deal-chat", "withdraw", "support", "account-draft", "admin"].includes(state.currentView) ? "market" : state.currentView;
    navigate(viewName);
  }

  function openListingForm(mode) {
    if (mode === "unique" && state.me?.user.role !== "admin") return notify("Только администратор может создавать уникальные машины");
    state.listingMode = mode;
    state.editingListingId = null;
    state.photoFiles = [];
    elements.carForm.reset();
    elements.photoPreview.replaceChildren();
    document.getElementById("listingType").value = mode;
    document.getElementById("addTitle").textContent = mode === "unique" ? "Добавить уникальную машину" : "Добавить автомобиль";
    document.getElementById("publicationNote").textContent = mode === "unique" ? "Уникальная машина публикуется администратором бесплатно." : "Публикация, редактирование и удаление объявлений всегда бесплатны.";
    document.getElementById("promoteLabel").textContent = mode === "unique" ? "📌 Закрепить объявление бесплатно" : "📌 Закрепить объявление — 15 AF Coins";
    document.getElementById("promotionNote").hidden = mode === "unique";
    elements.modelInput.disabled = true;
    elements.modelInput.placeholder = "Сначала выберите марку";
    openSecondary("add");
  }

  function openAdminAccountDraft() {
    if (state.me?.user.role !== "admin") return notify("Требуется роль администратора");
    document.getElementById("accountDraftForm").reset();
    openSecondary("account-draft");
  }

  async function openSupport() {
    openSecondary("support");
    if (!state.serverAvailable) return;
    try {
      state.supportTickets = await api.request("/support/tickets");
      renderSupportTickets();
    } catch (error) { notify(error.message); }
  }

  async function openAdminPanel() {
    if (state.me?.user.role !== "admin") return notify("Требуется роль администратора");
    openSecondary("admin");
    try {
      await Promise.all([loadAdminUsers(), loadAdminListings(), loadAdminDeals(), loadAdminWithdrawals(), loadAdminSupport(), loadAdvertisementAdmin()]);
    } catch (error) { notify(error.message); }
  }

  function applyRole() {
    const isAdmin = state.me?.user.role === "admin";
    document.querySelectorAll("[data-admin-only]").forEach((element) => { element.hidden = !isAdmin; });
  }

  function renderAll() {
    renderListings();
    renderAccounts();
    renderCart();
    renderProfile();
    renderBalance();
    renderAdvertisement();
  }

  function renderAdvertisement() {
    const advertisement = state.advertisement;
    const visible = Boolean(advertisement?.is_active && advertisement.image_url);
    elements.marketAdvertisement.hidden = !visible;
    if (!visible) {
      elements.marketAdvertisement.removeAttribute("href");
      elements.marketAdvertisementImage.removeAttribute("src");
      return;
    }
    elements.marketAdvertisementImage.src = absoluteMediaUrl(advertisement.image_url);
    if (advertisement.link_url) elements.marketAdvertisement.href = advertisement.link_url;
    else elements.marketAdvertisement.removeAttribute("href");
  }

  function getFilteredRegular() {
    const brand = elements.brandFilter.value;
    const model = elements.modelFilter.value;
    const price = elements.priceFilter.value;
    const minPower = Number(elements.powerFilter.value || 0);
    const minSpeed = Number(elements.speedFilter.value || 0);
    return state.regular.filter((listing) => {
      if (brand && listing.brand !== brand) return false;
      if (model && listing.model !== model) return false;
      if (minPower && Number(listing.power_hp) < minPower) return false;
      if (minSpeed && Number(listing.max_speed_kph) < minSpeed) return false;
      if (price === "above" && Number(listing.price_af_coins) <= 500) return false;
      if (price && price !== "above" && Number(listing.price_af_coins) > Number(price)) return false;
      return true;
    });
  }

  function renderListings() {
    const regular = getFilteredRegular();
    elements.marketCars.replaceChildren(...regular.map(createListingCard));
    elements.uniqueCars.replaceChildren(...state.unique.map(createListingCard));
    elements.marketEmpty.hidden = regular.length > 0;
    elements.uniqueEmpty.hidden = state.unique.length > 0;
  }

  function createListingCard(listing) {
    const card = document.createElement("article");
    card.className = `car-card${listing.listing_type === "unique" ? " is-unique" : ""}`;
    if (listing.listing_type === "unique") {
      const label = document.createElement("span");
      label.className = "unique-label";
      label.textContent = "Уникальная";
      card.append(label);
    }
    if (listing.pinned) {
      const pin = document.createElement("span");
      pin.className = "pin-label";
      pin.textContent = "✦";
      card.append(pin);
    }
    const media = document.createElement("div");
    media.className = "car-card__media";
    if (listing.images?.[0]) {
      const image = document.createElement("img");
      image.src = absoluteMediaUrl(listing.images[0]);
      image.alt = `${listing.brand} ${listing.model}`;
      image.loading = "lazy";
      media.append(image);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "car-placeholder";
      placeholder.textContent = "◇";
      media.append(placeholder);
    }
    const body = document.createElement("div");
    body.className = "car-card__body";
    const title = document.createElement("h3");
    title.textContent = `${listing.brand} ${listing.model}`;
    const price = document.createElement("div");
    price.className = "car-price";
    const effectivePrice = listing.effective_price_af_coins ?? listing.price_af_coins;
    price.append(document.createTextNode(`${formatNumber(effectivePrice)} `), coin("af-coin--small"));
    if (listing.effective_price_af_coins) {
      const oldPrice = document.createElement("del"); oldPrice.textContent = formatNumber(listing.price_af_coins); price.append(oldPrice);
    }
    const stats = document.createElement("div");
    stats.className = "car-stats";
    [`${listing.power_hp} л.с.`, `${listing.max_speed_kph} км/ч`, `Просмотров: ${listing.views_count || 0}`, statusLabel(listing.status)].forEach((value) => {
      const chip = document.createElement("span");
      chip.textContent = value;
      stats.append(chip);
    });
    const actions = document.createElement("div");
    actions.className = "card-actions";
    const openButton = document.createElement("button");
    openButton.className = "card-message";
    openButton.dataset.openListing = listing.id;
    openButton.textContent = "Открыть";
    actions.append(openButton);
    const isOwner = state.me?.user.id === listing.seller_id;
    const inCart = state.cart.some((item) => item.id === listing.id);
    const cartButton = document.createElement("button");
    cartButton.className = `card-cart${inCart ? " is-added" : ""}`;
    cartButton.dataset.cartToggle = listing.id;
    cartButton.textContent = inCart ? "✓ В корзине" : "🛒 В корзину";
    cartButton.disabled = listing.status !== "active";
    if (!isOwner) actions.append(cartButton);
    if (!isOwner) {
      const chat = document.createElement("button");
      chat.className = "card-message"; chat.dataset.chatListing = listing.id; chat.textContent = "Написать продавцу";
      actions.append(chat);
    }
    if (!isOwner && listing.listing_type === "unique") {
      const buy = document.createElement("button");
      buy.className = "card-buy";
      buy.dataset.buyNow = listing.id;
      buy.textContent = "Купить";
      buy.disabled = listing.status !== "active";
      actions.append(buy);
    }
    if (isOwner) {
      const ownerActions = document.createElement("div"); ownerActions.className = "owner-actions";
      const edit = document.createElement("button"); edit.dataset.editListing = listing.id; edit.textContent = "Изменить";
      const promote = document.createElement("button"); promote.dataset.promoteListing = listing.id; promote.textContent = listing.pinned ? "Закреплено" : (state.me.user.role === "admin" && listing.listing_type === "unique" ? "Закрепить бесплатно" : "Закрепить · 15 AF"); promote.disabled = listing.pinned || listing.status !== "active";
      const remove = document.createElement("button"); remove.dataset.deleteListing = listing.id; remove.textContent = "Удалить"; remove.className = "is-danger";
      ownerActions.append(edit, promote, remove); actions.append(ownerActions);
    }
    body.append(title, price, stats, actions);
    card.append(media, body);
    return card;
  }

  function renderAccounts() {
    elements.accountCards.replaceChildren(...state.accounts.map((account) => {
      const card = document.createElement("article"); card.className = "account-card";
      const media = document.createElement("div"); media.className = "account-card__media";
      if (account.image_url) { const image = document.createElement("img"); image.src = absoluteMediaUrl(account.image_url); image.alt = account.title; media.append(image); }
      else media.textContent = "AF";
      const body = document.createElement("div"); body.className = "account-card__body";
      const title = document.createElement("h3"); title.textContent = account.title;
      const facts = document.createElement("p"); facts.textContent = `Уровень ${account.level} · ${account.cars_count} машин · ${account.game_currency}${account.extra_currency ? ` · ${account.extra_currency}` : ""}`;
      const email = document.createElement("small"); email.textContent = `Email: ${{linked: "привязана", unlinked: "не привязана", unknown: "не указано"}[account.email_binding]}`;
      const description = document.createElement("p"); description.textContent = account.description;
      const assets = document.createElement("p"); assets.textContent = `${account.game_assets || "Игровые активы не указаны"} · ${account.auto_delivery ? "Автовыдача" : "Ручная передача"}`;
      const footer = document.createElement("div"); footer.className = "account-card__footer";
      const price = document.createElement("strong"); price.append(document.createTextNode(`${formatNumber(account.price_af_coins)} `), coin("af-coin--small")); footer.append(price);
      if (state.me?.user.role === "admin") { const remove = document.createElement("button"); remove.dataset.deleteAccount = account.id; remove.textContent = "Удалить"; footer.append(remove); }
      body.append(title, facts, email, assets, description, footer); card.append(media, body); return card;
    }));
    elements.accountsEmpty.hidden = state.accounts.length > 0;
  }

  async function toggleCart(id) {
    if (!state.serverAvailable) return notify("Сервер недоступен");
    try {
      const exists = state.cart.some((item) => item.id === id);
      await api.request(`/cart/items/${id}`, { method: exists ? "DELETE" : "POST" });
      state.cart = await api.request("/cart");
      renderAll();
    } catch (error) { notify(error.message); }
  }

  async function buyNowFlow(id) {
    if (!state.cart.some((item) => item.id === id)) await toggleCart(id);
    if (state.cart.some((item) => item.id === id)) openSecondary("cart");
  }

  async function removeFromCart(id) {
    try {
      await api.request(`/cart/items/${id}`, { method: "DELETE" });
      state.cart = await api.request("/cart");
      renderCart();
      renderListings();
    } catch (error) { notify(error.message); }
  }

  function renderCart() {
    document.querySelectorAll("[data-cart-count]").forEach((node) => {
      node.textContent = String(state.cart.length);
      if (node.classList.contains("cart-badge")) node.hidden = state.cart.length === 0;
    });
    elements.cartEmpty.hidden = state.cart.length > 0;
    elements.cartSummary.hidden = state.cart.length === 0;
    elements.cartList.replaceChildren(...state.cart.map(createCartRow));
    const available = state.cart.filter((item) => item.status === "active");
    const total = available.reduce((sum, item) => sum + Number(item.effective_price_af_coins ?? item.price_af_coins), 0);
    document.getElementById("cartTotal").textContent = formatNumber(total);
    document.getElementById("checkoutButton").hidden = available.length === 0;
    document.getElementById("cartTopupButton").hidden = true;
  }

  function createCartRow(listing) {
    const row = document.createElement("article");
    row.className = `compact-cart-item${listing.status === "sold" ? " is-sold" : ""}`;
    const visual = document.createElement("div");
    visual.className = "compact-cart-item__image";
    if (listing.images?.[0]) {
      const image = document.createElement("img");
      image.src = absoluteMediaUrl(listing.images[0]);
      image.alt = `${listing.brand} ${listing.model}`;
      visual.append(image);
    }
    const copy = document.createElement("div");
    copy.className = "compact-cart-item__copy";
    const title = document.createElement("strong");
    title.textContent = `${listing.brand} ${listing.model}`;
    const price = document.createElement("span");
    price.append(document.createTextNode(`${formatNumber(listing.effective_price_af_coins ?? listing.price_af_coins)} `), coin("af-coin--small"));
    const status = document.createElement("small");
    status.textContent = listing.status === "sold" ? "Уже продано" : statusLabel(listing.status);
    copy.append(title, price, status);
    const remove = document.createElement("button");
    remove.className = "compact-cart-item__remove";
    remove.dataset.cartRemove = listing.id;
    remove.textContent = "×";
    remove.setAttribute("aria-label", "Удалить");
    row.append(visual, copy, remove);
    return row;
  }

  async function checkout() {
    try {
      const deals = await api.request("/cart/checkout", { method: "POST" });
      await refreshMarketplace();
      notify("Средства зарезервированы. Сделка создана");
      if (deals[0]) {
        const conversation = state.profile?.conversations?.find((item) => item.deal?.id === deals[0].id) || (await api.request("/conversations")).find((item) => item.deal?.id === deals[0].id);
        if (conversation) await openConversation(conversation.id);
      }
    } catch (error) {
      if (error.status === 402) {
        document.getElementById("cartTopupButton").hidden = false;
        notify("Недостаточно средств");
      } else {
        notify(error.message);
        await refreshMarketplace().catch(() => {});
      }
    }
  }

  async function submitListing(event) {
    event.preventDefault();
    if (!state.serverAvailable) return notify("Сервер недоступен");
    const form = elements.carForm;
    const formData = new FormData(form);
    const button = form.querySelector("button[type=submit]");
    if (button.disabled) return;
    button.disabled = true;
    try {
      const imageUrls = [];
      for (const file of state.photoFiles) {
        const uploaded = await api.upload(file);
        imageUrls.push(uploaded.url);
      }
      const payload = {
        brand: String(formData.get("brand")).trim(),
        model: String(formData.get("model")).trim(),
        power_hp: Number(formData.get("power_hp")),
        max_speed_kph: Number(formData.get("max_speed_kph")),
        description: String(formData.get("description") || "").trim(),
        price_af_coins: Number(formData.get("price_af_coins")),
      };
      if (!state.editingListingId && imageUrls.length !== 1) throw new Error("Добавьте одну фотографию автомобиля");
      if (!state.editingListingId || imageUrls.length) payload.image_urls = imageUrls;
      const promotionSelected = formData.get("promote_for_24h") === "on";
      const shouldPromote = promotionSelected && (state.listingMode === "unique" || await confirmAction("Закрепить объявление за 15 AF Coins?"));
      const path = state.editingListingId ? `/listings/${state.editingListingId}` : state.listingMode === "unique" ? "/admin/listings/unique" : "/listings";
      if (state.listingMode === "unique") payload.pinned = shouldPromote;
      const savedListing = await api.request(path, { method: state.editingListingId ? "PATCH" : "POST", body: JSON.stringify(payload) });
      let promotionError = null;
      if (shouldPromote && !savedListing.pinned) {
        try {
          const promotionPath = state.listingMode === "unique" ? `/admin/listings/${savedListing.id}/promote` : `/listings/${savedListing.id}/promote`;
          await api.request(promotionPath, { method: "POST" });
        } catch (error) { promotionError = error; }
      }
      form.reset();
      elements.photoPreview.replaceChildren();
      state.photoFiles = [];
      const wasEditing = Boolean(state.editingListingId);
      state.editingListingId = null;
      await refreshMarketplace();
      navigate(state.listingMode === "unique" ? "unique" : "market");
      if (promotionError) notify(`Объявление опубликовано бесплатно, но не закреплено: ${promotionError.message}`);
      else notify(wasEditing ? "Объявление обновлено бесплатно" : "Объявление опубликовано бесплатно");
    } catch (error) { notify(error.message); }
    finally { button.disabled = false; }
  }

  function findListing(id) { return [...state.regular, ...state.unique, ...(state.profile?.active_listings || [])].find((item) => item.id === id); }

  async function openListingDetails(id) {
    try {
      const listing = await api.request(`/listings/${id}`);
      const existing = document.getElementById("listingDetailsModal");
      if (existing) existing.remove();
      const dialog = document.createElement("dialog");
      dialog.className = "modal";
      dialog.id = "listingDetailsModal";
      const head = document.createElement("div");
      head.className = "modal-head";
      const heading = document.createElement("div");
      const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow"; eyebrow.textContent = listing.listing_type === "unique" ? "Уникальная машина" : "Объявление";
      const title = document.createElement("h2"); title.textContent = `${listing.brand} ${listing.model}`;
      heading.append(eyebrow, title);
      const close = document.createElement("button"); close.type = "button"; close.textContent = "×"; close.addEventListener("click", () => dialog.close());
      head.append(heading, close);
      const description = document.createElement("p"); description.textContent = listing.description;
      const stats = document.createElement("p"); stats.textContent = `${listing.power_hp} л.с. · ${listing.max_speed_kph} км/ч · ${listing.views_count} просмотров`;
      const price = document.createElement("p"); price.append(document.createTextNode(`${formatNumber(listing.effective_price_af_coins ?? listing.price_af_coins)} `), coin("af-coin--small"));
      dialog.append(head, description, stats, price);
      if (listing.seller_id !== state.me?.user.id) {
        const message = document.createElement("button"); message.className = "publish-button"; message.type = "button"; message.textContent = "Написать продавцу";
        message.addEventListener("click", async () => { dialog.close(); await startConversation(listing.id); });
        dialog.append(message);
      }
      document.body.append(dialog);
      dialog.addEventListener("close", () => dialog.remove(), { once: true });
      openDialog(dialog);
      const local = findListing(id); if (local) local.views_count = listing.views_count;
    } catch (error) { notify(error.message); }
  }

  function editListing(id) {
    const listing = findListing(id); if (!listing) return;
    state.listingMode = listing.listing_type;
    state.editingListingId = id;
    state.photoFiles = [];
    elements.carForm.reset(); elements.photoPreview.replaceChildren();
    elements.brandInput.value = listing.brand; elements.modelInput.value = listing.model; elements.modelInput.disabled = false;
    elements.carForm.elements.power_hp.value = listing.power_hp; elements.carForm.elements.max_speed_kph.value = listing.max_speed_kph; elements.carForm.elements.description.value = listing.description; elements.priceInput.value = listing.price_af_coins;
    document.getElementById("listingType").value = listing.listing_type;
    document.getElementById("addTitle").textContent = "Редактировать объявление";
    const freeAdminPromotion = state.me.user.role === "admin" && listing.listing_type === "unique";
    document.getElementById("promoteLabel").textContent = freeAdminPromotion ? "📌 Закрепить бесплатно" : "📌 Закрепить — 15 AF Coins";
    document.getElementById("promotionNote").hidden = freeAdminPromotion;
    openSecondary("add");
  }

  async function deleteListing(id) {
    if (!(await confirmAction("Удалить объявление? Это действие нельзя отменить."))) return;
    try { await api.request(`/listings/${id}`, { method: "DELETE" }); await refreshMarketplace(); notify("Объявление удалено"); }
    catch (error) { notify(error.message); }
  }

  async function promoteListing(id) {
    const source = findListing(id);
    const freeAdminPromotion = state.me?.user.role === "admin" && source?.listing_type === "unique";
    if (!freeAdminPromotion && !(await confirmAction("Закрепить объявление за 15 AF Coins?"))) return;
    try { const listing = await api.request(freeAdminPromotion ? `/admin/listings/${id}/promote` : `/listings/${id}/promote`, { method: "POST" }); await refreshMarketplace(); notify(`Объявление закреплено до ${formatDate(listing.pinned_until)}`); }
    catch (error) { notify(error.message); }
  }

  function previewPhotos(event) {
    const file = event.target.files?.[0];
    if (!file) { state.photoFiles = []; elements.photoPreview.replaceChildren(); return; }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      event.target.value = "";
      state.photoFiles = [];
      return notify("Разрешены только JPG, PNG и WEBP");
    }
    if (file.size > 5 * 1024 * 1024) {
      event.target.value = "";
      state.photoFiles = [];
      return notify("Фотография не должна превышать 5 МБ");
    }
    state.photoFiles = [file];
    elements.photoPreview.replaceChildren(...state.photoFiles.map((file, index) => {
      const image = document.createElement("img");
      image.src = URL.createObjectURL(file);
      image.alt = `Фотография ${index + 1}`;
      return image;
    }));
  }

  function selectPrice(button) {
    document.querySelectorAll("[data-price]").forEach((item) => item.classList.toggle("is-active", item === button));
    elements.priceInput.value = button.dataset.price;
  }

  async function loadCatalog() {
    if (state.catalog.brands?.length) return;
    state.catalog = await fetch("data/vehicle_catalog.json").then((response) => response.json());
  }

  async function updateBrandSuggestions() {
    await loadCatalog();
    const query = elements.brandInput.value.trim().toLowerCase();
    const matches = state.catalog.brands.filter((brand) => brand.name.toLowerCase().startsWith(query));
    fillDatalist("brandSuggestions", matches.map((brand) => brand.name));
    const exact = state.catalog.brands.find((brand) => brand.name.toLowerCase() === query);
    elements.modelInput.disabled = !exact;
    elements.modelInput.value = exact ? elements.modelInput.value : "";
    elements.modelInput.placeholder = exact ? "Начните вводить модель" : "Сначала выберите марку";
    updateModelSuggestions();
  }

  function updateModelSuggestions() {
    const brand = state.catalog.brands.find((item) => item.name.toLowerCase() === elements.brandInput.value.trim().toLowerCase());
    if (!brand) return fillDatalist("modelSuggestions", []);
    const query = elements.modelInput.value.trim().toLowerCase();
    fillDatalist("modelSuggestions", brand.models.filter((model) => model.toLowerCase().startsWith(query)));
  }

  function fillDatalist(id, values) {
    const list = document.getElementById(id);
    list.replaceChildren(...values.map((value) => new Option(value, value)));
  }

  function updateFilterOptions() {
    setSelectOptions(elements.brandFilter, "Марка", uniqueValues(state.regular.map((item) => item.brand)));
    setSelectOptions(elements.modelFilter, "Модель", uniqueValues(state.regular.map((item) => item.model)));
  }

  function setSelectOptions(select, placeholder, values) {
    const current = select.value;
    select.replaceChildren(new Option(placeholder, ""), ...values.map((value) => new Option(value, value)));
    if (values.includes(current)) select.value = current;
  }

  function toggleExtraFilters() {
    const open = elements.extraFilters.hidden;
    elements.extraFilters.hidden = !open;
    elements.extraFiltersButton.setAttribute("aria-expanded", String(open));
  }

  function resetFilters() {
    [elements.brandFilter, elements.modelFilter, elements.priceFilter, elements.powerFilter, elements.speedFilter].forEach((control) => { control.value = ""; });
    renderListings();
  }

  function renderProfile() {
    const profile = state.profile;
    if (!profile) return;
    document.getElementById("activeCount").textContent = profile.active_listings.length;
    document.getElementById("soldCount").textContent = profile.sold_listings.length;
    document.getElementById("purchaseCount").textContent = profile.purchases.length;
    renderMiniListings(elements.profileActive, profile.active_listings, "Активных объявлений пока нет", true);
    renderMiniListings(elements.profileSold, profile.sold_listings, "Проданных товаров пока нет");
    renderMiniListings(elements.profilePurchases, profile.purchases, "Покупок пока нет");
    renderHistory(profile.wallet_transactions);
    renderWithdrawalHistory(profile.withdrawals);
    renderDeals(profile.active_deals);
    renderConversations(profile.conversations || []);
    document.getElementById("frozenBalance").textContent = Number(profile.wallet.frozen_balance).toFixed(2);
    document.getElementById("totalEarned").textContent = Number(profile.wallet.total_earned).toFixed(2);
  }

  function renderMiniListings(container, listings, emptyText, ownerControls = false) {
    if (!listings.length) {
      const empty = document.createElement("div");
      empty.className = "history-empty";
      empty.textContent = emptyText;
      container.replaceChildren(empty);
      return;
    }
    container.replaceChildren(...listings.map((listing) => {
      const row = document.createElement("div");
      row.className = "profile-mini-card";
      const image = document.createElement(listing.images?.[0] ? "img" : "div");
      if (listing.images?.[0]) { image.src = absoluteMediaUrl(listing.images[0]); image.alt = `${listing.brand} ${listing.model}`; }
      else image.className = "profile-mini-placeholder";
      const copy = document.createElement("div");
      const title = document.createElement("strong"); title.textContent = `${listing.brand} ${listing.model}`;
      const meta = document.createElement("small"); meta.textContent = statusLabel(listing.status);
      copy.append(title, meta);
      const price = document.createElement("b"); price.append(document.createTextNode(`${formatNumber(listing.effective_price_af_coins ?? listing.price_af_coins)} `), coin("af-coin--small"));
      row.append(image, copy, price);
      if (ownerControls) {
        const actions = document.createElement("div"); actions.className = "profile-card-actions";
        const edit = document.createElement("button"); edit.dataset.editListing = listing.id; edit.textContent = "Изменить";
        const promote = document.createElement("button"); promote.dataset.promoteListing = listing.id; promote.textContent = listing.pinned ? "Закреплено" : "Закрепить"; promote.disabled = listing.pinned;
        const remove = document.createElement("button"); remove.dataset.deleteListing = listing.id; remove.textContent = "Удалить"; remove.className = "is-danger";
        actions.append(edit, promote, remove); row.append(actions);
      }
      return row;
    }));
  }

  function renderHistory(transactions) {
    document.getElementById("historyEmpty").hidden = transactions.length > 0;
    elements.history.replaceChildren(...transactions.map((item) => {
      const row = document.createElement("div"); row.className = "history-item";
      const copy = document.createElement("div");
      const title = document.createElement("strong"); title.textContent = item.description;
      const date = document.createElement("span"); date.textContent = formatDate(item.created_at);
      copy.append(title, date);
      const amount = document.createElement("b"); if (Number(item.amount) < 0) amount.className = "is-negative";
      amount.append(document.createTextNode(`${Number(item.amount) > 0 ? "+" : ""}${formatNumber(item.amount)} `), coin("af-coin--small"));
      row.append(copy, amount); return row;
    }));
  }

  function renderWithdrawalHistory(withdrawals) {
    if (!withdrawals.length) {
      const empty = document.createElement("div"); empty.className = "history-empty"; empty.textContent = "Заявок на вывод пока нет";
      elements.withdrawalHistory.replaceChildren(empty); return;
    }
    elements.withdrawalHistory.replaceChildren(...withdrawals.map((item) => {
      const row = document.createElement("div"); row.className = "history-item withdrawal-history-item";
      const copy = document.createElement("div");
      const title = document.createElement("strong"); title.textContent = `${formatNumber(item.amount)} AF Coins · ${withdrawalStatusLabel(item.status)}`;
      const date = document.createElement("span"); date.textContent = formatDate(item.created_at); copy.append(title, date);
      row.append(copy);
      if (item.status === "pending") { const cancel = document.createElement("button"); cancel.dataset.cancelWithdrawal = item.id; cancel.textContent = "Отменить"; row.append(cancel); }
      return row;
    }));
  }

  async function cancelOwnWithdrawal(id) {
    try { await api.request(`/withdrawals/${id}/cancel`, { method: "POST" }); await refreshMarketplace(); notify("Заявка отменена, AF Coins возвращены"); }
    catch (error) { notify(error.message); }
  }

  function renderDeals(deals) {
    document.getElementById("dealsEmpty").hidden = deals.length > 0;
    elements.activeDeals.replaceChildren(...deals.map((deal) => {
      const conversation = state.profile?.conversations?.find((item) => item.deal?.id === deal.id);
      const button = document.createElement("button"); button.className = "deal-row"; if (conversation) button.dataset.openConversation = conversation.id;
      const copy = document.createElement("div"); const title = document.createElement("strong"); title.textContent = `Сделка ${deal.id.slice(0, 8)}`;
      const date = document.createElement("small"); date.textContent = formatDate(deal.created_at); copy.append(title, date);
      const status = document.createElement("b"); status.textContent = dealStatusLabel(deal.status); button.append(copy, status); return button;
    }));
  }

function renderConversations(conversations) {
  const hiddenIds = getHiddenConversationIds();

  const visibleConversations = conversations.filter(
    (conversation) => !hiddenIds.includes(String(conversation.id))
  );

  const empty = document.getElementById("conversationsEmpty");

  empty.hidden = visibleConversations.length > 0;
  elements.conversationList.replaceChildren();

  visibleConversations.forEach((conversation) => {
    const row = document.createElement("div");
    row.className = "conversation-row";

    const open = document.createElement("button");
    open.type = "button";
    open.className = "conversation-open";
    open.dataset.openConversation = conversation.id;

    const name = document.createElement("strong");
    name.className = "conversation-name";
    name.textContent =
      conversation.counterparty.name ||
      conversation.counterparty.username ||
      "Пользователь";

    open.append(name);

    const unreadSummary = state.unreadConversations.find(
      (item) => String(item.conversation_id) === String(conversation.id)
    );
    const unreadCount = Number(
      conversation.unread_count || unreadSummary?.unread_count || 0
    );

    if (unreadCount > 0) {
      const badge = document.createElement("span");
      badge.className = "conversation-unread";
      badge.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
      open.append(badge);
    }

    const del = document.createElement("button");
    del.className = "conversation-delete";
    del.dataset.hideConversation = conversation.id;
    del.textContent = "🗑";

    row.append(open, del);
    elements.conversationList.append(row);
  });
}
function getHiddenConversationIds() {
  try {
    const saved = JSON.parse(
      localStorage.getItem("hiddenConversationIds") || "[]"
    );

    return Array.isArray(saved) ? saved.map(String) : [];
  } catch {
    return [];
  }
}

function saveHiddenConversationIds(ids) {
  localStorage.setItem(
    "hiddenConversationIds",
    JSON.stringify(ids.map(String))
  );
}

function hideConversation(conversationId) {
  const hiddenIds = getHiddenConversationIds();
  const id = String(conversationId);

  if (!hiddenIds.includes(id)) {
    hiddenIds.push(id);
    saveHiddenConversationIds(hiddenIds);
  }

  renderConversations(state.profile?.conversations || []);
  notify("Диалог удалён из вашего списка");
}
  function openFrozenDeals() {
    switchProfileTab("deals");
    const frozen = Number(state.profile?.wallet.frozen_balance || 0);
    notify(frozen > 0 ? "Средства заморожены в активных сделках или заявках на вывод" : "Замороженных средств сейчас нет");
  }

  function switchProfileTab(tabName) {
    document.querySelectorAll("[data-profile-tab]").forEach((button) => button.classList.toggle("is-active", button.dataset.profileTab === tabName));
    document.querySelectorAll("[data-profile-panel]").forEach((panel) => { panel.hidden = panel.dataset.profilePanel !== tabName; });
  }

  function toggleProfileSection(section) {
    elements.profileActive.hidden = section !== "active";
    elements.profileSold.hidden = section !== "sold";
    elements.profilePurchases.hidden = section !== "purchases";
  }

  async function startConversation(listingId) {
    try { const conversation = await api.request(`/conversations/listing/${listingId}`, { method: "POST" }); await openConversation(conversation.id); }
    catch (error) { notify(error.message); }
  }

  async function openConversation(id) {
    try {
      const [conversation, messages] = await Promise.all([api.request(`/conversations/${id}`), api.request(`/conversations/${id}/messages`)]);
      state.currentConversation = conversation;
      state.messages = messages;
      state.previousView = state.currentView === "profile" ? "profile" : "market";
      renderConversation();
      navigate("deal-chat");
    } catch (error) { notify(error.message); }
  }

  function renderConversation() {
    const details = state.currentConversation; if (!details) return;
    const other = details.counterparty;
    document.getElementById("chatName").textContent = other.name || other.username || "Пользователь";
    document.getElementById("chatActivity").textContent = other.mini_app_last_active_at ? `В Mini App: ${formatDate(other.mini_app_last_active_at)}` : "Активность в Mini App неизвестна";
    document.getElementById("chatStatus").textContent = details.deal ? dealStatusLabel(details.deal.status) : "Переписка";
    document.getElementById("chatAvatar").textContent = (other.name || other.username || "A").slice(0, 1).toUpperCase();
    elements.chatListing.replaceChildren();
    const title = document.createElement("strong"); title.textContent = `${details.listing.brand} ${details.listing.model}`;
    const price = document.createElement("span"); price.append(document.createTextNode(`${formatNumber(details.accepted_price_af_coins ?? details.listing.price_af_coins)} `), coin("af-coin--small"));
    elements.chatListing.append(title, price);
    elements.dealMessages.replaceChildren(...state.messages.map((message) => {
      const bubble = document.createElement("div"); bubble.className = `message${message.sender_id === state.me.user.id ? " is-own" : ""}${message.message_type === "system" ? " is-system" : ""}`;
      bubble.append(document.createTextNode(message.body)); const time = document.createElement("small"); time.textContent = formatDate(message.created_at); bubble.append(time); return bubble;
    }));
    renderOffers();
    renderDealControls();
    requestAnimationFrame(() => { elements.dealMessages.scrollTop = elements.dealMessages.scrollHeight; });
  }

  function renderOffers() {
    const conversation = state.currentConversation; elements.offerPanel.replaceChildren(); if (!conversation || conversation.deal) return;
    const latest = [...conversation.offers].reverse().find((item) => item.status === "pending");
    if (latest) {
      const text = document.createElement("span"); text.append(document.createTextNode(`Предложение: ${formatNumber(latest.amount_af_coins)} `), coin("af-coin--small")); elements.offerPanel.append(text);
      if (latest.offered_by_id !== state.me.user.id) {
        const accept = document.createElement("button"); accept.dataset.offerAction = "accept"; accept.dataset.offerId = latest.id; accept.textContent = "Принять";
        const reject = document.createElement("button"); reject.dataset.offerAction = "reject"; reject.dataset.offerId = latest.id; reject.textContent = "Отклонить";
        const counter = document.createElement("button"); counter.dataset.offerAction = "counter"; counter.dataset.offerId = latest.id; counter.textContent = "Своя цена"; elements.offerPanel.append(accept, reject, counter);
      }
    } else {
      const button = document.createElement("button"); button.dataset.newOffer = ""; button.textContent = "Предложить цену"; elements.offerPanel.append(button);
    }
  }

  function renderDealControls() {
    const deal = state.currentConversation?.deal;
    elements.dealControls.replaceChildren();
    if (!deal || ["completed", "cancelled"].includes(deal.status)) return;
    const isBuyer = deal.buyer_id === state.me.user.id;
    const isSeller = deal.seller_id === state.me.user.id;
    if (isSeller && ["paid", "seller_contacted"].includes(deal.status)) {
      if (deal.status === "paid") {
        const contacted = document.createElement("button"); contacted.className = "deal-secondary"; contacted.dataset.dealAction = "seller-contacted"; contacted.textContent = "Я на связи"; elements.dealControls.append(contacted);
      }
      const transfer = document.createElement("button"); transfer.className = "deal-confirm"; transfer.dataset.dealAction = "transfer"; transfer.textContent = "Передали машину"; elements.dealControls.append(transfer);
    }
   if (isBuyer && deal.status === "transfer_in_progress") {
  const warning = document.createElement("p");
  warning.textContent =
    "Подтверждайте получение только после того, как действительно получили машину.";

  const timer = document.createElement("p");
  timer.className = "deal-timer";

  const confirm = document.createElement("button");
  confirm.className = "deal-confirm";
  confirm.dataset.dealAction = "confirm";
  confirm.textContent = "Машина передана мне";
  confirm.hidden = true;

  const availableAt =
    new Date(deal.transfer_started_at).getTime() + 60 * 1000;

  const updateTimer = () => {
    const remainingMs = availableAt - Date.now();
    const remainingSeconds = Math.max(
      0,
      Math.ceil(remainingMs / 1000)
    );

    if (remainingSeconds > 0) {
      timer.textContent =
        `Подтвердить получение можно через ${remainingSeconds} сек.`;
      confirm.hidden = true;
      return;
    }

    timer.textContent = "Теперь можно подтвердить получение машины.";
    confirm.hidden = false;
    clearInterval(timer.intervalId);
  };

  updateTimer();
  timer.intervalId = window.setInterval(updateTimer, 1000);

  elements.dealControls.append(warning, timer, confirm);
}
    const dispute = document.createElement("button"); dispute.className = "deal-dispute"; dispute.dataset.dealAction = "dispute"; dispute.textContent = "Возникла проблема"; elements.dealControls.append(dispute);
    if (["paid", "seller_contacted"].includes(deal.status)) {
      const cancel = document.createElement("button"); cancel.className = "deal-secondary"; cancel.dataset.dealAction = "cancel"; cancel.textContent = "Отменить сделку"; elements.dealControls.append(cancel);
    }
  }

  async function runDealAction(action) {
    const id = state.currentConversation?.deal?.id;
    if (!id) return;
    const endpoint = action === "seller-contacted" ? "seller-contacted" : action === "transfer" ? "transfer" : action === "confirm" ? "confirm" : action === "cancel" ? "cancel" : "dispute";
    try { await api.request(`/deals/${id}/${endpoint}`, { method: "POST" }); await openConversation(state.currentConversation.id); await refreshMarketplace(); }
    catch (error) { notify(error.message); }
  }

  async function sendChatMessage(event) {
    event.preventDefault();
    const input = document.getElementById("chatInput");
    if (!state.currentConversation || !input.value.trim()) return;
    try {
      await api.request(`/conversations/${state.currentConversation.id}/messages`, { method: "POST", body: JSON.stringify({ body: input.value.trim() }) });
      input.value = "";
      await openConversation(state.currentConversation.id);
    } catch (error) { notify(error.message); }
  }

  async function createOffer() {
    const value = window.prompt("Предложите цену в AF Coins (минимум 100)", String(state.currentConversation?.listing.price_af_coins || 100));
    if (!value) return;
    try { await api.request(`/conversations/${state.currentConversation.id}/offers`, { method: "POST", body: JSON.stringify({ amount_af_coins: Number(value) }) }); await openConversation(state.currentConversation.id); }
    catch (error) { notify(error.message); }
  }

  async function runOfferAction(button) {
    try {
      if (button.dataset.offerAction === "counter") {
        const value = window.prompt("Встречная цена в AF Coins", "100"); if (!value) return;
        await api.request(`/conversations/${state.currentConversation.id}/offers/counter`, { method: "POST", body: JSON.stringify({ amount_af_coins: Number(value), parent_offer_id: button.dataset.offerId }) });
      } else await api.request(`/offers/${button.dataset.offerId}/${button.dataset.offerAction}`, { method: "POST" });
      await openConversation(state.currentConversation.id);
    } catch (error) { notify(error.message); }
  }

  async function requestStarInvoice(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("button[type=submit]");
    if (button.disabled) return;
    elements.paymentResult.textContent = "";
    if (!telegram?.initData || typeof telegram.openInvoice !== "function") {
      elements.paymentResult.className = "payment-result is-error";
      elements.paymentResult.textContent = "Откройте AUTOFLOW MARKET внутри Telegram, чтобы оплатить счёт";
      return;
    }
    button.disabled = true;
    try {
      const amount = Number(document.getElementById("topupAmount").value);
      const intent = await api.request("/wallet/star-payments/intent", { method: "POST", body: JSON.stringify({ amount }) });
      elements.paymentResult.className = "payment-result";
      elements.paymentResult.textContent = "Счёт открыт в Telegram";
      const invoiceStatus = await new Promise((resolve, reject) => {
        try { telegram.openInvoice(intent.invoice_url, resolve); }
        catch (error) { reject(error); }
      });
      if (invoiceStatus === "cancelled") {
        elements.paymentResult.className = "payment-result is-cancelled";
        elements.paymentResult.textContent = "Оплата отменена. Баланс не изменён";
        return;
      }
      if (invoiceStatus === "failed") {
        elements.paymentResult.className = "payment-result is-error";
        elements.paymentResult.textContent = "Telegram не завершил оплату. Баланс не изменён";
        return;
      }
      const payment = await waitForStarPayment(intent.id);
      if (payment.status !== "paid") throw new Error("Подтверждение оплаты ещё не получено сервером. Проверьте баланс через несколько секунд");
      state.me.wallet = payment.wallet;
      await refreshMarketplace();
      elements.paymentResult.className = "payment-result is-success";
      elements.paymentResult.textContent = "Оплата успешно завершена";
    } catch (error) {
      elements.paymentResult.className = "payment-result is-error";
      elements.paymentResult.textContent = error.message;
    } finally { button.disabled = false; }
  }

  async function waitForStarPayment(intentId) {
    let status = null;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      status = await api.request(`/wallet/star-payments/intents/${intentId}`);
      if (status.status !== "pending") return status;
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
    return status;
  }

  async function createWithdrawal(event) {
    event.preventDefault(); const form = new FormData(elements.withdrawForm);
    try {
      await api.request("/withdrawals", { method: "POST", body: JSON.stringify({ amount: Number(form.get("amount")), payout_method: form.get("payout_method"), details: form.get("details") }) });
      elements.withdrawForm.reset(); await refreshMarketplace(); navigate("profile"); notify("Заявка создана, сумма заморожена");
    } catch (error) { notify(error.message); }
  }

  async function submitAccountListing(event) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const button = formElement.querySelector("button[type=submit]"); if (button.disabled) return; button.disabled = true;
    try {
      let imageUrl = null; const photo = form.get("photo"); if (photo?.size) imageUrl = (await api.upload(photo)).url;
      if (!imageUrl) throw new Error("Добавьте одну фотографию аккаунта");
      await api.request("/admin/accounts", { method: "POST", body: JSON.stringify({ title: form.get("title"), level: Number(form.get("level")), cars_count: Number(form.get("cars_count")), game_currency: form.get("game_currency"), extra_currency: form.get("extra_currency") || null, game_assets: form.get("game_assets") || null, email_binding: form.get("email_binding"), auto_delivery: form.get("auto_delivery") === "on", description: form.get("description"), price_af_coins: Number(form.get("price_af_coins")), image_url: imageUrl }) });
      formElement.reset(); await refreshMarketplace(); navigate("accounts"); notify("Аккаунт опубликован без хранения учётных данных");
    } catch (error) { notify(error.message); } finally { button.disabled = false; }
  }

  async function deleteAccountListing(id) {
    if (!(await confirmAction("Удалить объявление аккаунта?"))) return;
    try { await api.request(`/admin/accounts/${id}`, { method: "DELETE" }); await refreshMarketplace(); notify("Объявление аккаунта удалено"); }
    catch (error) { notify(error.message); }
  }

  async function submitSupportTicket(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const data = new FormData(formElement);
    const button = formElement.querySelector("button[type=submit]");
    if (button.disabled) return;
    button.disabled = true;
    try {
      const screenshot = data.get("screenshot");
      let screenshotUrl = null;
      if (screenshot?.size) screenshotUrl = (await api.upload(screenshot)).url;
      await api.request("/support/tickets", {
        method: "POST",
        body: JSON.stringify({ topic: data.get("topic"), message: data.get("message"), screenshot_url: screenshotUrl }),
      });
      formElement.reset();
      state.supportTickets = await api.request("/support/tickets");
      renderSupportTickets();
      notify("Обращение отправлено");
    } catch (error) { notify(error.message); }
    finally { button.disabled = false; }
  }

  function renderSupportTickets() {
    if (!state.supportTickets.length) {
      elements.supportTickets.textContent = "Обращений пока нет";
      return;
    }
    elements.supportTickets.replaceChildren(...state.supportTickets.map((ticket) => createSupportTicketCard(ticket, false)));
  }

  function createSupportTicketCard(ticket, adminMode) {
    const card = document.createElement("article"); card.className = "support-ticket";
    const head = document.createElement("div"); head.className = "support-ticket__head";
    const title = document.createElement("strong"); title.textContent = ticket.topic;
    const status = document.createElement("small"); status.textContent = supportStatusLabel(ticket.status);
    head.append(title, status); card.append(head);
    ticket.messages.forEach((item) => {
      const message = document.createElement("div");
      const isAdminMessage = adminMode ? item.sender_id === state.me?.user.id : item.sender_id !== state.me?.user.id;
      message.className = `support-message${isAdminMessage ? " is-admin" : ""}`;
      message.textContent = item.body;
      card.append(message);
    });
    const actions = document.createElement("div"); actions.className = "support-ticket__actions";
    if (ticket.status !== "closed") {
      const reply = document.createElement("button"); reply.type = "button"; reply.dataset.supportReply = ticket.id; reply.dataset.adminReply = String(adminMode); reply.textContent = "Ответить"; actions.append(reply);
    }
    if (adminMode) {
      ["resolved", "closed"].forEach((nextStatus) => { const button = document.createElement("button"); button.type = "button"; button.dataset.supportStatus = nextStatus; button.dataset.ticketId = ticket.id; button.textContent = nextStatus === "resolved" ? "Решено" : "Закрыть"; actions.append(button); });
    }
    card.append(actions);
    return card;
  }

  async function replySupportTicket(ticketId, adminMode) {
    const message = window.prompt("Введите ответ");
    if (!message?.trim()) return;
    const path = adminMode ? `/admin/support/tickets/${ticketId}/messages` : `/support/tickets/${ticketId}/messages`;
    try {
      await api.request(path, { method: "POST", body: JSON.stringify({ message: message.trim() }) });
      if (adminMode) await loadAdminSupport();
      else { state.supportTickets = await api.request("/support/tickets"); renderSupportTickets(); }
    } catch (error) { notify(error.message); }
  }

  async function setSupportTicketStatus(ticketId, status) {
    try {
      await api.request(`/admin/support/tickets/${ticketId}`, { method: "PATCH", body: JSON.stringify({ status }) });
      await loadAdminSupport();
    } catch (error) { notify(error.message); }
  }

  async function loadAdminSupport() {
    const tickets = await api.request("/admin/support/tickets");
    if (!tickets.length) { elements.adminSupportTickets.textContent = "Обращений пока нет"; return; }
    elements.adminSupportTickets.replaceChildren(...tickets.map((ticket) => createSupportTicketCard(ticket, true)));
  }

  async function loadAdvertisementAdmin() {
    const advertisement = await api.request("/admin/advertisement");
    state.advertisement = advertisement;
    const form = elements.advertisementForm;
    form.elements.link_url.value = advertisement?.link_url || "";
    form.elements.is_active.checked = advertisement?.is_active ?? true;
    renderAdvertisementAdmin(advertisement);
    renderAdvertisement();
  }

  function renderAdvertisementAdmin(advertisement) {
    if (!advertisement?.image_url) {
      elements.advertisementPreview.textContent = "Баннер пока не загружен";
      return;
    }
    const image = document.createElement("img"); image.src = absoluteMediaUrl(advertisement.image_url); image.alt = "Предпросмотр рекламы";
    elements.advertisementPreview.replaceChildren(image);
  }

  async function submitAdvertisement(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const data = new FormData(formElement);
    const button = formElement.querySelector("button[type=submit]");
    if (button.disabled) return;
    button.disabled = true;
    try {
      let imageUrl = state.advertisement?.image_url || null;
      const image = data.get("image");
      if (image?.size) imageUrl = (await api.upload(image, "/admin/advertisement/upload")).url;
      if (!imageUrl) throw new Error("Загрузите рекламное изображение");
      state.advertisement = await api.request("/admin/advertisement", {
        method: "PUT",
        body: JSON.stringify({ image_url: imageUrl, link_url: data.get("link_url") || null, is_active: data.get("is_active") === "on" }),
      });
      formElement.elements.image.value = "";
      renderAdvertisementAdmin(state.advertisement);
      renderAdvertisement();
      notify("Реклама сохранена");
    } catch (error) { notify(error.message); }
    finally { button.disabled = false; }
  }

  async function deleteAdvertisement() {
    if (!(await confirmAction("Удалить рекламный баннер?"))) return;
    try {
      await api.request("/admin/advertisement", { method: "DELETE" });
      state.advertisement = null;
      elements.advertisementForm.reset();
      renderAdvertisementAdmin(null);
      renderAdvertisement();
      notify("Реклама удалена");
    } catch (error) { notify(error.message); }
  }

  async function loadAdminWithdrawals() { renderAdminWithdrawals(await api.request("/admin/withdrawals")); }

  async function loadAdminUsers(q = "") {
    const users = await api.request(`/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`);
    elements.adminUsers.replaceChildren(...users.map((item) => {
      const card = document.createElement("div"); card.className = "admin-record";
      const title = document.createElement("strong"); title.textContent = `${item.user.first_name}${item.user.username ? ` · @${item.user.username}` : ""}`;
      const meta = document.createElement("small"); meta.textContent = `Telegram ID ${item.user.telegram_id} · ${item.listings_count} объявл. · ${item.deals_count} сделок`;
      const balance = document.createElement("span"); balance.textContent = `Баланс ${formatNumber(item.wallet.available_balance)} AF`;
      const actions = document.createElement("div"); actions.className = "admin-record__actions";
      const history = document.createElement("button"); history.dataset.financialHistory = item.user.id; history.textContent = "История";
      const block = document.createElement("button"); block.dataset.adminUserAction = item.user.is_blocked ? "unblock" : "block"; block.dataset.userId = item.user.id; block.textContent = item.user.is_blocked ? "Разблокировать" : "Заблокировать"; actions.append(history, block);
      card.append(title, meta, balance, actions); return card;
    }));
  }

  async function searchAdminUsers(event) { event.preventDefault(); try { await loadAdminUsers(new FormData(event.currentTarget).get("q").trim()); } catch (error) { notify(error.message); } }

  async function adminUserAction(button) {
    if (!(await confirmAction(`${button.textContent} пользователя?`))) return;
    try { await api.request(`/admin/users/${button.dataset.userId}/${button.dataset.adminUserAction}`, { method: "POST" }); await loadAdminUsers(); notify("Статус пользователя обновлён"); }
    catch (error) { notify(error.message); }
  }

  async function loadAdminListings() {
    const listings = await api.request("/admin/listings");
    elements.adminListings.replaceChildren(...listings.map((listing) => {
      const card = document.createElement("div"); card.className = "admin-record";
      const title = document.createElement("strong"); title.textContent = `${listing.brand} ${listing.model} · ${listing.listing_type}`;
      const meta = document.createElement("small"); meta.textContent = `${statusLabel(listing.status)} · ${formatNumber(listing.price_af_coins)} AF Coins`;
      const actions = document.createElement("div"); actions.className = "admin-record__actions";
      const promotion = document.createElement("button"); promotion.dataset.adminListingAction = "promote"; promotion.dataset.listingId = listing.id; promotion.textContent = listing.pinned ? "Закреплено" : "Закрепить"; promotion.disabled = listing.pinned;
      const publication = document.createElement("button"); publication.dataset.adminListingAction = listing.status === "paused" ? "publish" : "unpublish"; publication.dataset.listingId = listing.id; publication.textContent = listing.status === "paused" ? "Опубликовать" : "Снять";
      const remove = document.createElement("button"); remove.dataset.adminListingAction = "delete"; remove.dataset.listingId = listing.id; remove.textContent = "Удалить"; actions.append(promotion, publication, remove); card.append(title, meta, actions); return card;
    }));
  }

  async function adminListingAction(button) {
    const action = button.dataset.adminListingAction; if ((action === "delete" || action === "unpublish") && !(await confirmAction(`${button.textContent} объявление?`))) return;
    try { if (action === "delete") await api.request(`/admin/listings/${button.dataset.listingId}`, { method: "DELETE" }); else await api.request(`/admin/listings/${button.dataset.listingId}/${action}`, { method: "POST" }); await loadAdminListings(); await refreshMarketplace(); notify("Объявление обновлено"); }
    catch (error) { notify(error.message); }
  }

  async function loadAdminDeals() {
    const deals = await api.request("/admin/deals");
    elements.adminDeals.replaceChildren(...deals.map((deal) => {
      const card = document.createElement("div"); card.className = "admin-record";
      const title = document.createElement("strong"); title.textContent = `Сделка ${deal.id.slice(0, 8)} · ${dealStatusLabel(deal.status)}`;
      const meta = document.createElement("small"); meta.textContent = `${formatNumber(deal.price_af_coins)} AF Coins · ${formatDate(deal.created_at)}`; card.append(title, meta);
      if (deal.status === "disputed") { const actions = document.createElement("div"); actions.className = "admin-record__actions"; ["complete", "refund"].forEach((outcome) => { const button = document.createElement("button"); button.dataset.resolveDeal = outcome; button.dataset.dealId = deal.id; button.textContent = outcome === "complete" ? "Завершить продавцу" : "Вернуть покупателю"; actions.append(button); }); card.append(actions); }
      return card;
    }));
  }

  async function resolveAdminDeal(button) {
    const reason = window.prompt("Обязательная причина решения спора"); if (!reason) return;
    try { await api.request(`/admin/deals/${button.dataset.dealId}/resolve`, { method: "POST", body: JSON.stringify({ outcome: button.dataset.resolveDeal, reason }) }); await loadAdminDeals(); notify("Спор разрешён и записан в историю"); }
    catch (error) { notify(error.message); }
  }

  function switchAdminTab(tab) {
    document.querySelectorAll("[data-admin-tab]").forEach((button) => button.classList.toggle("is-active", button.dataset.adminTab === tab));
    document.querySelectorAll("[data-admin-panel]").forEach((panel) => { panel.hidden = panel.dataset.adminPanel !== tab; });
  }

  function renderAdminWithdrawals(withdrawals) {
    if (!withdrawals.length) { elements.adminWithdrawals.textContent = "Заявок пока нет"; return; }
    elements.adminWithdrawals.replaceChildren(...withdrawals.map((item) => {
      const card = document.createElement("div"); card.className = "admin-withdrawal";
      const title = document.createElement("strong"); title.textContent = `${formatNumber(item.amount)} AF Coins · ${item.status}`;
      const user = document.createElement("span"); user.textContent = `${item.user_name || "Пользователь"} · Telegram ID ${item.user_telegram_id}`;
      const details = document.createElement("small"); details.textContent = item.details;
      const actions = document.createElement("div"); actions.className = "admin-withdrawal__actions";
      if (item.status === "pending") actions.append(adminActionButton(item.id, "approve", "Одобрить"), adminActionButton(item.id, "reject", "Отклонить"));
      if (item.status === "approved") actions.append(adminActionButton(item.id, "paid", "Отметить выплаченной"), adminActionButton(item.id, "reject", "Отклонить"));
      const history = document.createElement("button"); history.dataset.financialHistory = item.user_id; history.textContent = "Финансовая история"; actions.append(history);
      card.append(title, user, details, actions); return card;
    }));
  }

  function adminActionButton(id, action, label) { const button = document.createElement("button"); button.dataset.withdrawalAction = action; button.dataset.withdrawalId = id; button.textContent = label; return button; }

  async function adminWithdrawalAction(button) {
    let reason = null;
    if (button.dataset.withdrawalAction === "reject") { reason = window.prompt("Укажите причину отклонения"); if (!reason) return; }
    try {
      await api.request(`/admin/withdrawals/${button.dataset.withdrawalId}/${button.dataset.withdrawalAction}`, { method: "POST", body: JSON.stringify({ reason }) });
      renderAdminWithdrawals(await api.request("/admin/withdrawals")); notify("Статус заявки обновлён");
    } catch (error) { notify(error.message); }
  }

  async function loadAdminFinancialHistory(userId) {
    try {
      const history = await api.request(`/admin/users/${userId}/financial-history`);
      elements.adminUserHistory.hidden = false;
      const title = document.createElement("strong"); title.textContent = `${history.user.name} · Telegram ID ${history.user.telegram_id}`;
      const balance = document.createElement("p"); balance.textContent = `Доступно ${formatNumber(history.wallet.available_balance)}, заморожено ${formatNumber(history.wallet.frozen_balance)}, заработано ${formatNumber(history.wallet.total_earned)} AF Coins`;
      const counts = document.createElement("small"); counts.textContent = `Пополнений: ${history.star_payments.length} · операций: ${history.wallet_transactions.length} · выводов: ${history.withdrawals.length}`;
      elements.adminUserHistory.replaceChildren(title, balance, counts);
    } catch (error) { notify(error.message); }
  }

  async function createBalanceAdjustment(event) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    try {
      await api.request("/admin/balance-adjustments", { method: "POST", body: JSON.stringify({ user_id: form.get("user_id"), amount: Number(form.get("amount")), reason: form.get("reason") }) });
      formElement.reset(); notify("Корректировка записана отдельной транзакцией");
    } catch (error) { notify(error.message); }
  }

  function renderBalance() {
    const value = Number(state.me?.wallet.available_balance || 0).toFixed(2);
    document.querySelectorAll("[data-balance]").forEach((node) => { node.textContent = value; });
  }

  function renderUser() {
    const user = state.me?.user; if (!user) return;
    const name = [user.first_name, user.last_name].filter(Boolean).join(" ");
    document.getElementById("profileName").textContent = name;
    document.getElementById("profileUsername").textContent = user.username ? `@${user.username}` : "Username не указан";
    document.getElementById("profileTelegramId").textContent = `Telegram ID: ${user.telegram_id}`;
    [document.getElementById("headerAvatarFallback"), document.getElementById("profileAvatarFallback")].forEach((node) => { node.textContent = name.slice(0, 1).toUpperCase(); });
    if (user.photo_url) {
      [document.getElementById("headerAvatarImage"), document.getElementById("profileAvatarImage")].forEach((image) => { image.src = user.photo_url; image.hidden = false; image.previousElementSibling.hidden = true; });
    }
  }

  function showServerState(error) {
    const existing = document.querySelector(".server-state"); if (existing) existing.remove();
    const notice = document.createElement("div"); notice.className = "server-state";
    notice.textContent = `Сервер API не подключён: ${error.message}. Запустите PostgreSQL и backend по инструкции.`;
    document.querySelector('[data-view="market"]').prepend(notice);
  }

  function openDialog(dialog) { typeof dialog.showModal === "function" ? dialog.showModal() : dialog.setAttribute("open", ""); }
  function confirmAction(message) {
    return new Promise((resolve) => {
      if (telegram?.initData && telegram.showConfirm) telegram.showConfirm(message, resolve);
      else resolve(window.confirm(message));
    });
  }
  function notify(message) { if (telegram?.initData && telegram.showAlert) return telegram.showAlert(message); elements.toast.textContent = message; elements.toast.classList.add("is-visible"); clearTimeout(notify.timeout); notify.timeout = setTimeout(() => elements.toast.classList.remove("is-visible"), 2600); }
  function coin(extraClass = "") { const item = document.createElement("i"); item.className = `af-coin ${extraClass}`.trim(); item.setAttribute("aria-label", "AF Coins"); return item; }
  function absoluteMediaUrl(url) { return url.startsWith("/") ? `${api.baseUrl.replace(/\/api$/, "")}${url}` : url; }
  function formatNumber(value) { return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value)); }
  function formatDate(value) { return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(value)); }
  function uniqueValues(values) { return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru")); }
  function statusLabel(status) { return ({ active: "Доступно", reserved: "Зарезервировано", sold: "Уже продано", paused: "Снято с публикации", deleted: "Удалено" })[status] || status; }
  function dealStatusLabel(status) { return ({ pending_payment: "Ожидает оплаты", paid: "Оплачено", seller_contacted: "Продавец на связи", transfer_in_progress: "Передача", buyer_confirmed: "Получение подтверждено", completed: "Завершена", disputed: "Спор", cancelled: "Отменена" })[status] || status; }
  function withdrawalStatusLabel(status) { return ({ pending: "Ожидает проверки", approved: "Одобрена", paid: "Выплачена", rejected: "Отклонена", cancelled: "Отменена" })[status] || status; }
  function supportStatusLabel(status) { return ({ open: "Открыто", in_progress: "В работе", resolved: "Решено", closed: "Закрыто" })[status] || status; }
})();
