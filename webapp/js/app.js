(function () {
  "use strict";

  const api = window.AutoFlowApi;
  let telegram = window.Telegram?.WebApp || null;
  const launchParams = new URLSearchParams(window.location.search);
  const state = {
    currentView: "market",
    previousView: "market",
    listingMode: "regular",
    me: null,
    regular: [],
    unique: [],
    training: [],
    contentUnseen: { training: { unseen_count: 0, marker: 0 }, unique: { unseen_count: 0, marker: 0 } },
    trainingPurchases: [],
    selectedTraining: null,
    adminTraining: [],
    adminTrainingStats: null,
    adminTrainingFilter: "all",
    adminTrainingPurchases: [],
    adminTrainingOrders: [],
    adminTrainingOrderFilter: "new",
    adminTrainingMaterials: [],
    selectedAdminTrainingId: null,
    trainingUploadCache: new Map(),
    trainingUploadRows: new Map(),
    trainingInboxUploads: [],
    selectedTrainingInboxUpload: null,
    pendingTrainingPublish: null,
    pendingTrainingRequestId: null,
    pendingTrainingCoverUrl: null,
    trainingCoverObjectUrl: null,
    advertisement: null,
    supportTickets: [],
    adminSupportFilter: "active",
    adminBroadcasts: [],
    broadcastPollingId: null,
    pendingBroadcastRequestId: null,
    profile: null,
    catalog: { brands: [] },
    photoFiles: [],
    currentConversation: null,
    selectedListing: null,
    editingListingId: null,
    messages: [],
    notifications: [],
    failedOptional: new Set(),
    optionalRecoveryUsed: false,
    unreadConversations: [],
    totalUnread: 0,
    messagePollingId: null,
    messagePollingFailureReported: false,
    activeTopupIntentId: null,
    confirmedTopupPayments: new Set(),
    adminBalanceUser: null,
    adminBalanceDirection: "credit",
    purchaseFlow: null,
    listingViewObserver: null,
    listingViewTimers: new Map(),
    listingViewRequests: new Set(),
    listingLikeRequests: new Set(),
    dealTimerId: null,
    pendingListingRequestId: null,
    hiddenAt: null,
    pendingDealDeepLink: launchParams.get("deal_id"),
    pendingDealBuyerEntry: launchParams.get("buyer_entry") === "1",
    pendingSupportDealDeepLink: launchParams.get("support_deal_id"),
    pendingConversationDeepLink: launchParams.get("conversation_id"),
    pendingListingDeepLink: launchParams.get("conversation_id") ? null : launchParams.get("listing_id"),
    pendingTrainingDeepLink: launchParams.get("training_id") || launchParams.get("startapp") || window.Telegram?.WebApp?.initDataUnsafe?.start_param || null,
    pendingAdminUserDeepLink: launchParams.get("admin_user_id"),
    pendingAdminUnpublishSellerDeepLink: launchParams.get("admin_unpublish_seller_id"),
    openingDealDeepLink: false,
    openingAdminSellerDeepLink: false,
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
    trainingCards: document.getElementById("trainingCards"),
    trainingEmpty: document.getElementById("trainingEmptyState"),
    trainingContentBadge: document.getElementById("trainingContentBadge"),
    uniqueContentBadge: document.getElementById("uniqueContentBadge"),
    personalTrainingPurchases: document.getElementById("personalTrainingPurchases"),
    automaticTrainingPurchases: document.getElementById("automaticTrainingPurchases"),
    adminTrainingStats: document.getElementById("adminTrainingStats"),
    adminTrainingProducts: document.getElementById("adminTrainingProducts"),
    adminTrainingDetail: document.getElementById("adminTrainingDetail"),
    adminTrainingBuyers: document.getElementById("adminTrainingBuyers"),
    adminTrainingMaterials: document.getElementById("adminTrainingMaterials"),
    brandFilter: document.getElementById("brandFilter"),
    priceMinFilter: document.getElementById("priceMinFilter"),
    priceMaxFilter: document.getElementById("priceMaxFilter"),
    powerFilter: document.getElementById("powerFilter"),
    speedFilter: document.getElementById("speedFilter"),
    extraFilters: document.getElementById("extraFilters"),
    extraFiltersButton: document.getElementById("extraFiltersButton"),
    carForm: document.getElementById("carForm"),
    carPhotos: document.getElementById("carPhotos"),
    photoPreview: document.getElementById("photoPreview"),
    brandInput: document.getElementById("brandInput"),
    priceInput: document.getElementById("priceInput"),
    infoModal: document.getElementById("infoModal"),
    toast: document.getElementById("toast"),
    paymentResult: document.getElementById("paymentResult"),
    adminBalanceLookupMessage: document.getElementById("adminBalanceLookupMessage"),
    adminBalanceUserCard: document.getElementById("adminBalanceUserCard"),
    adminBalanceResult: document.getElementById("adminBalanceResult"),
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
    dealDeliveryPanel: document.getElementById("dealDeliveryPanel"),
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
    startupStatus: document.getElementById("startupStatus"),
    startupSpinner: document.getElementById("startupSpinner"),
    startupTitle: document.getElementById("startupTitle"),
    startupMessage: document.getElementById("startupMessage"),
    startupRetry: document.getElementById("startupRetry"),
    syncStatus: document.getElementById("syncStatus"),
    syncStatusText: document.getElementById("syncStatusText"),
    syncRetry: document.getElementById("syncRetry"),
    floatingChatButton: document.getElementById("floatingChatButton"),
    chatUnreadBadge: document.getElementById("chatUnreadBadge"),
    chatNotification: document.getElementById("chatNotification"),
    chatNotificationText: document.getElementById("chatNotificationText"),
    successOverlay: document.getElementById("successOverlay"),
    successTitle: document.getElementById("successTitle"),
    successText: document.getElementById("successText"),
    purchaseModal: document.getElementById("purchaseModal"),
    purchaseModalTitle: document.getElementById("purchaseModalTitle"),
    purchaseModalText: document.getElementById("purchaseModalText"),
    purchaseModalAmount: document.getElementById("purchaseModalAmount"),
    purchaseModalNote: document.getElementById("purchaseModalNote"),
    purchaseModalAction: document.getElementById("purchaseModalAction"),
    frontendBuildInfo: document.getElementById("frontendBuildInfo"),
    trainingUploadStatus: document.getElementById("trainingUploadStatus"),
    trainingCoverInput: document.getElementById("trainingCoverInput"),
    trainingCoverPreview: document.getElementById("trainingCoverPreview"),
    trainingCoverPreviewImage: document.getElementById("trainingCoverPreviewImage"),
    listingPageImage: document.getElementById("listingPageImage"),
    listingPageImagePlaceholder: document.getElementById("listingPageImagePlaceholder"),
    listingPageSold: document.getElementById("listingPageSold"),
    listingPageKind: document.getElementById("listingPageKind"),
    listingPageTitle: document.getElementById("listingPageTitle"),
    listingPageBrand: document.getElementById("listingPageBrand"),
    listingPagePrice: document.getElementById("listingPagePrice"),
    listingPageDescription: document.getElementById("listingPageDescription"),
    listingPageSpecs: document.getElementById("listingPageSpecs"),
    listingPageViews: document.getElementById("listingPageViews"),
    listingPageLike: document.getElementById("listingPageLike"),
    listingPageBuy: document.getElementById("listingPageBuy"),
    listingPageChat: document.getElementById("listingPageChat"),
    listingPageOfferButton: document.getElementById("listingPageOfferButton"),
    listingPageOffer: document.getElementById("listingPageOffer"),
    listingOfferForm: document.getElementById("listingOfferForm"),
    listingOfferAmount: document.getElementById("listingOfferAmount"),
  };

  let bootstrapPromise = null;
  let criticalRecoveryUsed = false;
  let optionalRecoveryTimer = null;
  let startupRecoveryTimer = null;
  let initializedTelegram = null;

  function createRequestId() {
    if (typeof window.crypto?.randomUUID === "function") return window.crypto.randomUUID();
    const bytes = new Uint8Array(16);
    if (typeof window.crypto?.getRandomValues === "function") window.crypto.getRandomValues(bytes);
    else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  function createErrorId() {
    return `AF-${createRequestId().replace(/-/g, "").slice(0, 7).toUpperCase()}`;
  }

  function safeArray(value) {
    return Array.isArray(value) ? value : [];
  }

  installGlobalErrorHandlers();
  startApplication();

  function startApplication() {
    try {
      const telegramSdk = document.getElementById("telegramSdk");
      telegramSdk?.addEventListener("load", () => {
        telegram = window.Telegram?.WebApp || null;
        initTelegram();
        if (!state.me) void bootstrap({ automatic: true });
      });
      telegramSdk?.addEventListener("error", () => reportClientError("telegram_sdk_load", new Error("Telegram SDK load failed")));
      initTelegram();
      bindEvents();
      renderFrontendBuildInfo();
      installChatViewport();
      renderAll();
      void bootstrap();
    } catch (error) {
      const errorId = reportClientError("startup", error);
      showStartupError(`Не удалось запустить интерфейс. Код: ${errorId}`, true);
    }
  }

  function initTelegram() {
    if (!telegram || initializedTelegram === telegram) return;
    initializedTelegram = telegram;
    state.pendingTrainingDeepLink ||= telegram.initDataUnsafe?.start_param || null;
    safeTelegramCall("ready", () => telegram.ready());
    safeTelegramCall("expand", () => telegram.expand());
    safeTelegramCall("viewport", () => telegram.onEvent?.("viewportChanged", updateChatViewport));
    safeTelegramCall("theme", () => {
      if (typeof telegram.isVersionAtLeast !== "function" || telegram.isVersionAtLeast("6.1")) {
        telegram.setHeaderColor?.("#030912");
        telegram.setBackgroundColor?.("#030912");
      }
    });
    reportStartupStage("telegram_ready");
    renderFrontendBuildInfo();
  }

  function renderFrontendBuildInfo() {
    if (!elements.frontendBuildInfo) return;
    const build = document.querySelector('meta[name="autoflow-build"]')?.content || "unknown";
    const platform = telegram?.platform || "browser";
    const label = platform === "ios" ? "iPhone build" : ["tdesktop", "macos", "web", "weba", "webk"].includes(platform) ? "Desktop build" : `${platform} build`;
    const title = document.createElement("strong"); title.textContent = `${label}: ${build}`;
    const location = document.createElement("small"); location.textContent = `URL: ${window.location.origin}${window.location.pathname}`;
    elements.frontendBuildInfo.replaceChildren(title, location);
  }

  function bindEvents() {
    ensureBroadcastAdminUi();
    const trainingForm = document.getElementById("trainingForm");
    const trainingVideoInput = ensureTrainingVideoInput(trainingForm);
    ensureTrainingTelegramUploadUi();
    ["title", "short_description", "full_description"].forEach((name) => {
      trainingForm?.elements[name]?.removeAttribute("maxlength");
      trainingForm?.elements[name]?.setAttribute("minlength", "1");
    });
    trainingForm?.elements.price_af_coins?.setAttribute("min", "0.01");
    document.getElementById("trainingMaterialForm")?.elements.title?.removeAttribute("maxlength");
    document.addEventListener("click", handleClick);
    bind(document.getElementById("infoButton"), "click", () => openDialog(elements.infoModal), "infoButton");
    bind(document.getElementById("settingsButton"), "click", () => notify("Настройки появятся в следующей версии"), "settingsButton");
    bind(elements.extraFiltersButton, "click", toggleExtraFilters, "extraFiltersButton");
    bind(document.getElementById("resetFiltersButton"), "click", resetFilters, "resetFiltersButton");
    bind(document.getElementById("applyFiltersButton"), "click", renderListings, "applyFiltersButton");
    bind(elements.brandFilter, "change", renderListings, "brandFilter");
    [elements.priceMinFilter, elements.priceMaxFilter].forEach((control, index) => {
      bind(control, "input", renderListings, `priceFilter${index}`);
      bind(control, "keydown", finishPriceFilterInput, `priceFilterDone${index}`);
      bind(control, "focus", beginPriceFilterInput, `priceFilterFocus${index}`);
      bind(control, "blur", endPriceFilterInput, `priceFilterBlur${index}`);
    });
    bind(elements.brandInput, "input", updateBrandSuggestions, "brandInput");
    bind(elements.carPhotos, "change", previewPhotos, "carPhotos");
    bind(elements.carForm, "submit", submitListing, "carForm");
    bind(document.getElementById("topupForm"), "submit", requestStarInvoice, "topupForm");
    bind(elements.chatForm, "submit", sendChatMessage, "chatForm");
    bind(document.getElementById("chatHideButton"), "click", hideCurrentConversation, "chatHideButton");
    bind(document.getElementById("chatInput"), "input", resizeChatInput, "chatInput");
    bind(elements.chatListing, "click", openChatListing, "chatListing");
    bind(elements.listingPageLike, "click", likeSelectedListing, "listingPageLike");
    bind(elements.listingPageBuy, "click", buySelectedListing, "listingPageBuy");
    bind(elements.listingPageChat, "click", chatFromSelectedListing, "listingPageChat");
    bind(elements.listingPageOfferButton, "click", showListingOfferForm, "listingPageOfferButton");
    bind(elements.listingOfferForm, "submit", submitListingOffer, "listingOfferForm");
    bind(elements.withdrawForm, "submit", createWithdrawal, "withdrawForm");
    bind(document.getElementById("trainingForm"), "submit", submitTrainingProduct, "trainingForm");
    bind(trainingForm?.elements.product_type, "change", toggleAutomaticMaterialFields, "trainingProductType");
    bind(trainingVideoInput, "change", previewTrainingMaterials, "trainingVideo");
    bind(trainingForm?.elements.automatic_material, "change", previewTrainingMaterials, "trainingMaterials");
    bind(elements.trainingOpenUploadBot, "click", openTrainingUploadBot, "trainingOpenUploadBot");
    bind(elements.trainingRefreshUploads, "click", refreshTrainingInboxUploads, "trainingRefreshUploads");
    bind(elements.trainingCoverInput, "change", previewTrainingCover, "trainingCover");
    bind(document.getElementById("trainingBuyButton"), "click", () => buyTrainingProduct(), "trainingBuyButton");
    bind(document.getElementById("trainingMaterialForm"), "submit", saveTrainingMaterial, "trainingMaterialForm");
    const adminMaterialFile = document.getElementById("trainingMaterialForm")?.elements.file;
    if (adminMaterialFile) {
      adminMaterialFile.accept = "video/mp4,video/quicktime,video/webm,image/jpeg,image/png,image/webp,application/pdf,text/plain,application/zip,.mp4,.mov,.webm,.jpg,.jpeg,.png,.webp,.pdf,.txt,.zip";
      const labelText = adminMaterialFile.parentElement?.firstChild;
      if (labelText?.nodeType === Node.TEXT_NODE) labelText.textContent = "Добавить небольшой файл";
    }
    bind(elements.supportForm, "submit", submitSupportTicket, "supportForm");
    bind(elements.advertisementForm, "submit", submitAdvertisement, "advertisementForm");
    bind(document.getElementById("broadcastForm"), "submit", submitAdminBroadcast, "broadcastForm");
    bind(document.getElementById("deleteAdvertisementButton"), "click", deleteAdvertisement, "deleteAdvertisementButton");
    bind(document.getElementById("balanceAdjustmentForm"), "submit", createBalanceAdjustment, "balanceAdjustmentForm");
    bind(document.getElementById("adminBalanceLookupForm"), "submit", findAdminBalanceUser, "adminBalanceLookupForm");
    bind(document.getElementById("adminUserSearch"), "submit", searchAdminUsers, "adminUserSearch");
    bind(elements.startupRetry, "click", () => void bootstrap({ manual: true }), "startupRetry");
    bind(elements.syncRetry, "click", () => void retryFailedOptional(), "syncRetry");
    bind(elements.floatingChatButton, "click", openFloatingChat, "floatingChatButton");
    bind(elements.purchaseModalAction, "click", runPurchaseFlowAction, "purchaseModalAction");
  }

  function bootstrap(options = {}) {
    if (bootstrapPromise) return bootstrapPromise;
    bootstrapPromise = runBootstrap(options).finally(() => { bootstrapPromise = null; });
    return bootstrapPromise;
  }

  async function runBootstrap(options) {
    showStartupLoading(options.automatic ? "Восстанавливаем соединение…" : "Загрузка…");
    if (!api) return showStartupError("Не удалось загрузить приложение. Попробуйте ещё раз.", true);
    if (!telegram?.initData) await waitForTelegramSdk(6000);
    if (telegram?.initData) initTelegram();
    if (!telegram?.initData && window.AUTO_FLOW_ALLOW_BROWSER_DEV !== true) {
      state.serverAvailable = false;
      const telegramLaunch = hasTelegramLaunchHint();
      reportStartupStage("auth_missing_init_data", { telegram_launch_hint: telegramLaunch });
      showStartupError(
        telegramLaunch ? "Не удалось подтвердить запуск через Telegram. Закройте Mini App и откройте снова." : "Откройте AutoFlow Market через Telegram.",
        telegramLaunch,
      );
      return;
    }
    reportStartupStage("auth_started");
    try {
      state.me = await authenticateCurrentUser();
    } catch (error) {
      state.serverAvailable = false;
      const errorId = reportClientError("bootstrap_me", error);
      const unauthorized = error.status === 401;
      const forbidden = error.status === 403;
      const retryable = !unauthorized && !forbidden;
      const message = unauthorized
        ? "Не удалось подтвердить вход через Telegram. Закройте Mini App и откройте снова."
        : forbidden
          ? "Доступ к приложению ограничен."
          : `Не удалось подключиться к серверу. Проверьте интернет и попробуйте снова. Код: ${errorId}`;
      showStartupError(message, retryable || unauthorized);
      if (retryable && !criticalRecoveryUsed && !options.manual) {
        criticalRecoveryUsed = true;
        window.clearTimeout(startupRecoveryTimer);
        startupRecoveryTimer = window.setTimeout(() => void bootstrap({ automatic: true }), 5000);
      }
      return;
    }
    reportStartupStage("auth_success");
    reportStartupStage("me_loaded");
    state.serverAvailable = true;
    state.optionalRecoveryUsed = false;
    criticalRecoveryUsed = false;
    applyRole();
    renderUser();
    renderBalance();
    renderAll();
    updateFloatingChatVisibility();
    startMessagePolling();
    hideStartup();
    reportStartupStage("shell_rendered");
    reportStartupStage("market_loading");
    void loadOptionalData();
    void openTrainingProductDeepLink();
    void openTrainingOrderDeepLink();
    void openSupportCaseDeepLink();
    void openDealSupportDeepLink();
    void openDealDeepLink();
    void openConversationDeepLink();
    void openListingDeepLink();
    void openInactiveSellerAdminDeepLink();
  }

  async function authenticateCurrentUser() {
    const delays = [0, 1200, 2600];
    let lastError;
    for (let attempt = 0; attempt < delays.length; attempt += 1) {
      if (delays[attempt]) {
        showStartupLoading("Сервер запускается. Восстанавливаем соединение…");
        await new Promise((resolve) => window.setTimeout(resolve, delays[attempt]));
      }
      try {
        return await api.request("/me", { timeoutMs: 18000, retries: 0 });
      } catch (error) {
        lastError = error;
        reportClientError(`bootstrap_me_attempt_${attempt + 1}`, error);
        const retryable = error?.errorType === "timeout" || error?.errorType === "network" || [408, 429, 500, 502, 503, 504].includes(Number(error?.status || 0));
        if (!retryable) throw error;
      }
    }
    throw lastError;
  }

  const optionalLoaders = {
    catalog: async () => {
      const catalog = await api.resource("data/vehicle_catalog.json", { timeoutMs: 8000, retries: 1 });
      state.catalog = { ...(catalog && typeof catalog === "object" ? catalog : {}), brands: safeArray(catalog?.brands) };
    },
    regular: async () => { state.regular = safeArray(await api.request("/listings?type=regular")); },
    unique: async () => { state.unique = safeArray(await api.request("/listings?type=unique")); },
    training: async () => { state.training = safeArray(await api.request(state.me?.user.role === "admin" ? "/admin/training" : "/training")); },
    contentUnseen: async () => { state.contentUnseen = await api.request("/content/unseen"); },
    trainingPurchases: async () => { state.trainingPurchases = safeArray(await api.request("/training/mine")); },
    profile: async () => { state.profile = await api.request("/profile"); },
    advertisement: async () => { state.advertisement = await api.request("/advertisement", { timeoutMs: 8000 }); },
    notifications: async () => { state.notifications = safeArray(await api.request("/notifications")); },
  };

  async function loadOptionalData(keys = Object.keys(optionalLoaders), options = {}) {
    if (!state.serverAvailable) return [];
    const tasks = keys.map(async (key) => {
      try {
        await optionalLoaders[key]();
        state.failedOptional.delete(key);
        if (key === "regular") reportStartupStage("market_loaded");
        updateFilterOptions();
        renderAll();
      } catch (error) {
        state.failedOptional.add(key);
        reportClientError(`optional_${key}`, error);
        throw error;
      }
    });
    const results = await Promise.allSettled(tasks);
    updateSyncStatus();
    if (state.failedOptional.size && options.allowRecovery !== false && !state.optionalRecoveryUsed) {
      state.optionalRecoveryUsed = true;
      window.clearTimeout(optionalRecoveryTimer);
      optionalRecoveryTimer = window.setTimeout(() => void retryFailedOptional(), 4000);
    }
    return results;
  }

  async function retryFailedOptional() {
    const keys = [...state.failedOptional];
    if (!keys.length) return updateSyncStatus();
    elements.syncStatusText.textContent = "Восстанавливаем данные…";
    await loadOptionalData(keys, { allowRecovery: false });
  }

  async function refreshMarketplace() {
    if (!state.serverAvailable) return;
    await loadOptionalData(["regular", "unique", "training", "trainingPurchases", "profile", "advertisement"], { allowRecovery: false });
  }

  function hasTelegramLaunchHint() {
    return /tgWebApp(Data|Version|Platform)/.test(window.location.href);
  }

  function waitForTelegramSdk(timeoutMs) {
    return new Promise((resolve) => {
      const deadline = Date.now() + timeoutMs;
      const check = () => {
        telegram = window.Telegram?.WebApp || null;
        if (telegram?.initData || Date.now() >= deadline) return resolve(telegram);
        window.setTimeout(check, 100);
      };
      check();
    });
  }

function handleClick(event) {
  const target = event.target;

  const navButton = target.closest("[data-nav-target]");
  if (navButton) {
    return void navigate(navButton.dataset.navTarget);
  }

  const copyGameId = target.closest("[data-copy-game-id]");
  if (copyGameId) return void copyBuyerGameId(copyGameId.dataset.copyGameId);

  if (target.closest("[data-open-add]")) {
    return void openListingForm("regular");
  }

  if (target.closest("[data-open-unique]")) {
    return void openListingForm("unique");
  }

  if (target.closest("[data-open-training]")) {
    return void openTrainingEditor();
  }

  if (target.closest("[data-open-topup]")) {
    return void openSecondary("topup");
  }

  if (target.closest("[data-open-withdraw]")) {
    return void openSecondary("withdraw");
  }

  if (target.closest("[data-open-support]")) {
    return void openSupport();
  }

  if (target.closest("[data-open-admin]")) {
    return void openAdminPanel();
  }

  if (target.closest("[data-open-frozen]")) {
    return void openFrozenDeals();
  }

  if (target.closest("[data-open-info]")) {
    return void openDialog(elements.infoModal);
  }

  if (target.closest("[data-close-purchase]")) {
    return void closePurchaseFlow();
  }

  if (target.closest("[data-close-listing-offer]")) {
    elements.listingPageOffer.hidden = true;
    elements.listingPageOfferButton.hidden = false;
    return;
  }

  if (target.closest("[data-open-topup-info]")) {
    return void openDialog(
      document.getElementById("topupInfoModal")
    );
  }

  const topupAmount = target.closest("[data-topup-amount]");

  if (topupAmount) {
    const amount = Number(topupAmount.dataset.topupAmount);
    const input = document.getElementById("topupAmount");

    if (amount < 10 || amount > 1000) {
      return void notify("Сумма должна быть от 10 до 1000 Stars");
    }

    input.value = String(amount);
    return;
  }

  if (
    target.closest("[data-ad-banner]") &&
    !state.advertisement?.link_url
  ) {
    event.preventDefault();
    return void notify("Для баннера не указана ссылка");
  }

  if (target.closest("[data-back]")) {
    return void navigate(state.previousView || "market");
  }

    const closeDialog = target.closest("[data-close-dialog]");
    if (closeDialog) return void document.getElementById(closeDialog.dataset.closeDialog).close();
    const preset = target.closest("[data-price]");
    if (preset) return void selectPrice(preset);
    const listingLike = target.closest("[data-listing-like]");
    if (listingLike) return void toggleListingLike(listingLike.dataset.listingLike);
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
    const listingCard = target.closest("[data-listing-card]");
    if (listingCard && !target.closest("button,a,input,select,textarea,label")) {
      return void openListingDetails(listingCard.dataset.listingCard);
    }
    const profileTab = target.closest("[data-profile-tab]");
    if (profileTab) return void switchProfileTab(profileTab.dataset.profileTab);
    const profileSection = target.closest("[data-profile-section]");
    if (profileSection) return void toggleProfileSection(profileSection.dataset.profileSection);
    const conversationButton = target.closest("[data-open-conversation]");
    if (conversationButton) {
      return void openConversation(conversationButton.dataset.openConversation);
    }
    const dealChatButton = target.closest("[data-open-deal-chat]");
    if (dealChatButton) return void openDealConversation(dealChatButton.dataset.openDealChat);

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
    const trainingOpen = target.closest("[data-open-training-product]");
    if (trainingOpen) return void openTrainingProduct(trainingOpen.dataset.openTrainingProduct);
    const trainingBuy = target.closest("[data-buy-training]");
    if (trainingBuy) return void buyTrainingProduct(trainingBuy.dataset.buyTraining);
    const trainingEdit = target.closest("[data-edit-training]");
    if (trainingEdit) return void openTrainingEditor(trainingEdit.dataset.editTraining);
    const trainingDelete = target.closest("[data-delete-training]");
    if (trainingDelete) return void deleteTrainingProduct(trainingDelete.dataset.deleteTraining);
    const trainingFilter = target.closest("[data-training-filter]");
    if (trainingFilter) return void loadAdminTraining(trainingFilter.dataset.trainingFilter);
    const trainingAdminAction = target.closest("[data-training-admin-action]");
    if (trainingAdminAction) return void runTrainingAdminAction(trainingAdminAction);
    const trainingPurchaseAction = target.closest("[data-training-purchase-action]");
    if (trainingPurchaseAction) return void updatePersonalTrainingStatus(trainingPurchaseAction);
    const trainingOrderFilter = target.closest("[data-training-order-filter]");
    if (trainingOrderFilter) { state.adminTrainingOrderFilter = trainingOrderFilter.dataset.trainingOrderFilter; renderAdminTrainingOrders(); return; }
    const trainingNotify = target.closest("[data-training-notify]");
    if (trainingNotify) return void retryPersonalTrainingNotification(trainingNotify);
    const trainingAdminRedeliver = target.closest("[data-training-admin-redeliver]");
    if (trainingAdminRedeliver) return void adminRedeliverTraining(trainingAdminRedeliver);
    const trainingBuyerChat = target.closest("[data-training-buyer-username]");
    if (trainingBuyerChat) {
      const url = `https://t.me/${encodeURIComponent(trainingBuyerChat.dataset.trainingBuyerUsername)}`;
      return void (telegram?.openTelegramLink ? telegram.openTelegramLink(url) : window.open(url, "_blank", "noopener"));
    }
    const trainingMaterialAction = target.closest("[data-training-material-action]");
    if (trainingMaterialAction) return void runTrainingMaterialAction(trainingMaterialAction);
    const inboxUpload = target.closest("[data-training-inbox-upload]");
    if (inboxUpload) return void selectTrainingInboxUpload(inboxUpload.dataset.trainingInboxUpload);
    const redeliverTraining = target.closest("[data-training-redeliver]");
    if (redeliverTraining) return void redeliverTrainingMaterials(redeliverTraining);
    if (target.closest("[data-close-training-detail]")) return void closeAdminTrainingDetail();
    const adminTab = target.closest("[data-admin-tab]");
    if (adminTab) return void switchAdminTab(adminTab.dataset.adminTab);
    const userAction = target.closest("[data-admin-user-action]");
    if (userAction) return void adminUserAction(userAction);
    const paymentRetry = target.closest("[data-payment-retry]");
    if (paymentRetry) return void checkStarPaymentStatus(paymentRetry.dataset.paymentRetry);
    const balanceDirection = target.closest("[data-balance-direction]");
    if (balanceDirection) return void setAdminBalanceDirection(balanceDirection.dataset.balanceDirection);
    const listingAction = target.closest("[data-admin-listing-action]");
    if (listingAction) return void adminListingAction(listingAction);
    const supportReply = target.closest("[data-support-reply]");
    if (supportReply) return void replySupportTicket(supportReply.dataset.supportReply, supportReply.dataset.adminReply === "true");
    const supportStatus = target.closest("[data-support-status]");
    if (supportStatus) return void setSupportTicketStatus(supportStatus.dataset.ticketId, supportStatus.dataset.supportStatus);
    const supportFilter = target.closest("[data-support-filter]");
    if (supportFilter) return void loadAdminSupport(supportFilter.dataset.supportFilter);
    const supportResolution = target.closest("[data-support-resolution]");
    if (supportResolution) return void resolveSupportCase(supportResolution);
  }

  async function navigate(viewName) {
    const next = elements.views.find((view) => view.dataset.view === viewName);
    if (!next) return;
    state.currentView = viewName;
    document.body.classList.toggle("chat-open", viewName === "deal-chat");
    if (viewName !== "deal-chat") document.body.classList.remove("deal-details-required");
    document.body.classList.toggle("admin-open", viewName === "admin");
    if (viewName === "deal-chat") updateChatViewport();
    updateFloatingChatVisibility();
    elements.views.forEach((view) => {
      const active = view === next;
      view.hidden = !active;
      view.classList.toggle("is-active", active);
    });
    const navView = ["add", "deal-chat", "listing-detail"].includes(viewName) ? "market" : viewName === "training-detail" || viewName === "training-editor" ? "training" : ["topup", "withdraw"].includes(viewName) ? "profile" : ["admin", "support"].includes(viewName) ? "more" : viewName;
    elements.navButtons.forEach((button) => {
      const active = button.dataset.navTarget === navView;
      button.classList.toggle("is-active", active);
      active ? button.setAttribute("aria-current", "page") : button.removeAttribute("aria-current");
    });
    elements.shell.classList.toggle("is-focused", ["add", "topup", "profile", "deal-chat", "withdraw", "support", "training-editor", "training-detail", "listing-detail", "admin"].includes(viewName));
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (state.serverAvailable && ["market", "unique", "training", "profile"].includes(viewName)) {
      try {
        if (["unique", "training"].includes(viewName)) await openContentSection(viewName);
        else await refreshMarketplace();
      } catch (error) { notify(error.message); }
    }
  }

  async function openContentSection(section) {
    const snapshot = await api.request("/content/unseen");
    state.contentUnseen = snapshot;
    renderContentBadges();
    await refreshMarketplace();
    if (state.failedOptional.has(section)) {
      throw new Error(section === "training" ? "Не удалось загрузить обучение" : "Не удалось загрузить уникальные машины");
    }
    const result = await api.request(`/content/${section}/mark-seen`, {
      method: "POST",
      body: JSON.stringify({ marker: Number(snapshot?.[section]?.marker || 0) }),
    });
    state.contentUnseen[section] = result;
    renderContentBadges();
  }
  async function refreshUnreadMessages() {
  if (!state.serverAvailable || document.hidden) return;

  try {
    const summary = await api.request("/conversations/unread-summary");
    state.messagePollingFailureReported = false;

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
    if (!state.messagePollingFailureReported) {
      state.messagePollingFailureReported = true;
      reportClientError("message_polling", error);
    }
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

  const dealId = state.currentConversation?.deal?.id;
  const [messagesResult, dealResult] = await Promise.allSettled([
    api.request(`/conversations/${conversationId}/messages`),
    dealId ? api.request(`/deals/${dealId}`) : Promise.resolve(null),
  ]);
  if (messagesResult.status === "rejected" && dealResult.status === "rejected") throw messagesResult.reason;
  const messages = messagesResult.status === "fulfilled" ? safeArray(messagesResult.value) : safeArray(state.messages);
  const dealDetails = dealResult.status === "fulfilled" ? dealResult.value : null;

  const oldLastMessageId = state.messages.length ? state.messages[state.messages.length - 1]?.id : null;
  const newLastMessageId = messages.length ? messages[messages.length - 1]?.id : null;

  const previousDeal = state.currentConversation?.deal;
  const refreshedDeal = dealDetails?.deal || null;
  const dealChanged = refreshedDeal && (
    previousDeal?.status !== refreshedDeal.status ||
    previousDeal?.buyer_game_id !== refreshedDeal.buyer_game_id ||
    previousDeal?.preferred_delivery_time !== refreshedDeal.preferred_delivery_time
  );
  if (refreshedDeal) state.currentConversation.deal = refreshedDeal;

  if (oldLastMessageId !== newLastMessageId || dealChanged) {
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
    4000
  );
  }

  function updateFloatingChatVisibility() {
  const visibleViews = ["market", "unique", "training", "profile"];
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
    state.previousView = ["add", "topup", "deal-chat", "withdraw", "support", "training-editor", "training-detail", "listing-detail", "admin"].includes(state.currentView) ? "market" : state.currentView;
    navigate(viewName);
  }

  function openListingForm(mode) {
    if (mode === "unique" && state.me?.user.role !== "admin") return notify("Только администратор может создавать уникальные машины");
    state.listingMode = mode;
    state.editingListingId = null;
    state.pendingListingRequestId = null;
    state.photoFiles = [];
    elements.carForm.reset();
    elements.photoPreview.replaceChildren();
    document.getElementById("listingType").value = mode;
    document.getElementById("addTitle").textContent = mode === "unique" ? "Добавить уникальную машину" : "Добавить автомобиль";
    document.getElementById("publicationNote").textContent = mode === "unique" ? "Уникальная машина публикуется администратором бесплатно." : "Публикация, редактирование и удаление объявлений всегда бесплатны.";
    configurePromotionOption(mode === "unique");
    elements.carForm.elements.promote_for_24h.checked = true;
    openSecondary("add");
  }

  function configurePromotionOption(freeAdminPromotion) {
    document.getElementById("promoteLabel").textContent = "✨ Закрепить объявление";
    document.getElementById("promotePrice").textContent = freeAdminPromotion ? "Бесплатно" : "5 AF";
    document.getElementById("promotionNote").textContent = "Объявление будет находиться выше остальных в течение 24 часов.";
  }

  function chooseInitialPromotion() {
    const modal = document.getElementById("promotionChoiceModal");
    const paid = document.getElementById("promotionChoicePaid");
    const free = document.getElementById("promotionChoiceFree");
    return new Promise((resolve) => {
      let settled = false;
      const finish = (choice) => {
        if (settled) return;
        settled = true;
        paid.removeEventListener("click", choosePaid);
        free.removeEventListener("click", chooseFree);
        modal.removeEventListener("cancel", chooseFree);
        if (modal.open) modal.close();
        resolve(choice);
      };
      const choosePaid = () => finish(true);
      const chooseFree = (event) => { event?.preventDefault?.(); finish(false); };
      paid.addEventListener("click", choosePaid);
      free.addEventListener("click", chooseFree);
      modal.addEventListener("cancel", chooseFree);
      openDialog(modal);
    });
  }

  async function openSupport() {
    elements.supportForm.elements.deal_id.value = "";
    elements.supportForm.elements.topic.closest("label").hidden = false;
    elements.supportForm.elements.screenshot.required = false;
    document.getElementById("supportScreenshotLabel").textContent = "Скриншот, не более одного";
    document.getElementById("supportDealContext").hidden = true;
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
    const results = await Promise.allSettled([loadAdminUsers(), loadAdminListings(), loadAdminDeals(), loadAdminWithdrawals(), loadAdminSupport(), loadAdvertisementAdmin(), loadAdminTraining(state.adminTrainingFilter), loadAdminBroadcasts()]);
    const rejected = results.filter((result) => result.status === "rejected");
    rejected.forEach((result) => reportClientError("admin_optional", result.reason));
    if (rejected.length) notify("Часть данных админ-панели временно недоступна");
  }

  function applyRole() {
    const isAdmin = state.me?.user.role === "admin";
    document.querySelectorAll("[data-admin-only]").forEach((element) => { element.hidden = !isAdmin; });
  }

  function renderAll() {
    renderListings();
    renderTraining();
    renderProfile();
    renderBalance();
    renderAdvertisement();
    renderContentBadges();
  }

  function renderContentBadges() {
    [["training", elements.trainingContentBadge], ["unique", elements.uniqueContentBadge]].forEach(([section, badge]) => {
      if (!badge) return;
      const count = Math.max(0, Number(state.contentUnseen?.[section]?.unseen_count || 0));
      badge.hidden = count === 0;
      badge.textContent = count > 99 ? "99+" : String(count);
      badge.parentElement?.setAttribute("aria-label", count ? `${count} новых` : "Новых публикаций нет");
    });
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
    const hasMinPrice = elements.priceMinFilter.value !== "";
    const hasMaxPrice = elements.priceMaxFilter.value !== "";
    const minPrice = hasMinPrice ? Number(elements.priceMinFilter.value) : null;
    const maxPrice = hasMaxPrice ? Number(elements.priceMaxFilter.value) : null;
    const pricesInvalid = (minPrice !== null && minPrice < 0) || (maxPrice !== null && maxPrice < 0)
      || (minPrice !== null && maxPrice !== null && minPrice > maxPrice);
    elements.priceMinFilter.setAttribute("aria-invalid", String(pricesInvalid));
    elements.priceMaxFilter.setAttribute("aria-invalid", String(pricesInvalid));
    const minPower = Number(elements.powerFilter.value || 0);
    const minSpeed = Number(elements.speedFilter.value || 0);
    if (pricesInvalid) return [];
    return state.regular.filter((listing) => {
      if (brand && listing.brand !== brand) return false;
      if (minPower && Number(listing.power_hp) < minPower) return false;
      if (minSpeed && Number(listing.max_speed_kph) < minSpeed) return false;
      if (minPrice !== null && Number(listing.price_af_coins) < minPrice) return false;
      if (maxPrice !== null && Number(listing.price_af_coins) > maxPrice) return false;
      return true;
    });
  }

  function renderListings() {
    const regular = getFilteredRegular();
    elements.marketCars.replaceChildren(...regular.map(createListingCard));
    elements.uniqueCars.replaceChildren(...state.unique.map(createListingCard));
    elements.marketEmpty.hidden = regular.length > 0;
    elements.uniqueEmpty.hidden = state.unique.length > 0;
    observeVisibleListingCards();
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
      image.alt = listingTitle(listing);
      image.loading = "lazy";
      media.append(image);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "car-placeholder";
      placeholder.textContent = "◇";
      media.append(placeholder);
    }
    if (listing.status !== "active") {
      media.classList.add("is-sold");
      const sold = document.createElement("div");
      sold.className = "car-card__sold";
      sold.textContent = "ПРОДАНО";
      media.append(sold);
    }
    const body = document.createElement("div");
    body.className = "car-card__body";
    const title = document.createElement("h3");
    title.textContent = listingTitle(listing);
    const price = document.createElement("div");
    price.className = "car-price";
    const effectivePrice = listing.effective_price_af_coins ?? listing.price_af_coins;
    price.append(document.createTextNode(`${formatNumber(effectivePrice)} `), coin("af-coin--small"));
    if (listing.effective_price_af_coins) {
      const oldPrice = document.createElement("del"); oldPrice.textContent = formatNumber(listing.price_af_coins); price.append(oldPrice);
    }
    const stats = document.createElement("div");
    stats.className = "car-stats";
    [`${listing.power_hp} л.с.`, `${listing.max_speed_kph} км/ч`, `Передача: ${deliveryTimeLabel(listing.delivery_time_estimate)}`, statusLabel(listing.status)].forEach((value) => {
      const chip = document.createElement("span");
      chip.textContent = value;
      stats.append(chip);
    });
    const engagement = document.createElement("div");
    engagement.className = "car-engagement";
    engagement.dataset.listingEngagement = listing.id;
    const views = document.createElement("span");
    views.className = "car-engagement__views";
    views.dataset.listingViews = listing.id;
    views.textContent = `👁 ${Number(listing.views_count || 0)}`;
    const like = document.createElement("button");
    like.type = "button";
    like.className = `car-engagement__like${listing.liked_by_me ? " is-liked" : ""}`;
    like.dataset.listingLike = listing.id;
    like.setAttribute("aria-pressed", listing.liked_by_me ? "true" : "false");
    like.textContent = `${listing.liked_by_me ? "♥" : "♡"} ${Number(listing.likes_count || 0)}`;
    const isOwner = state.me?.user.id === listing.seller_id;
    if (isOwner) {
      like.disabled = true;
      like.title = "Нельзя поставить лайк собственному объявлению";
    }
    engagement.append(views, like);
    const actions = document.createElement("div");
    actions.className = "card-actions";
    if (!isOwner) {
      const buy = document.createElement("button");
      buy.className = "card-buy";
      buy.dataset.buyNow = listing.id;
      buy.textContent = listing.status === "active" ? `Купить за ${formatNumber(effectivePrice)} AF` : "Продано";
      buy.disabled = listing.status !== "active";
      actions.append(buy);
    }
    if (isOwner) {
      const ownerActions = document.createElement("div"); ownerActions.className = "owner-actions";
      const edit = document.createElement("button"); edit.dataset.editListing = listing.id; edit.textContent = "Изменить";
      const promote = document.createElement("button"); promote.dataset.promoteListing = listing.id; promote.textContent = listing.pinned ? "Закреплено" : (state.me.user.role === "admin" && listing.listing_type === "unique" ? "Закрепить бесплатно" : "Закрепить · 5 AF"); promote.disabled = listing.pinned || listing.status !== "active";
      const remove = document.createElement("button"); remove.dataset.deleteListing = listing.id; remove.textContent = "Удалить"; remove.className = "is-danger";
      ownerActions.append(edit, promote, remove); actions.append(ownerActions);
    }
    body.append(title, price, stats, engagement, actions);
    card.append(media, body);
    card.dataset.listingCard = listing.id;
    return card;
  }

  function observeVisibleListingCards() {
    state.listingViewObserver?.disconnect();
    state.listingViewTimers.forEach((timer) => window.clearTimeout(timer));
    state.listingViewTimers.clear();
    if (!("IntersectionObserver" in window)) return;
    state.listingViewObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        const id = entry.target.dataset.listingCard;
        const visible = entry.isIntersecting && entry.intersectionRatio >= 0.5;
        if (!visible) {
          window.clearTimeout(state.listingViewTimers.get(id));
          state.listingViewTimers.delete(id);
          return;
        }
        if (state.listingViewRequests.has(id) || state.listingViewTimers.has(id)) return;
        const timer = window.setTimeout(() => {
          state.listingViewTimers.delete(id);
          if (entry.target.isConnected) void recordListingView(id);
        }, 750);
        state.listingViewTimers.set(id, timer);
      });
    }, { threshold: [0.5] });
    document.querySelectorAll("[data-listing-card]").forEach((card) => {
      const listing = findListing(card.dataset.listingCard);
      if (listing && listing.seller_id !== state.me?.user.id) state.listingViewObserver.observe(card);
    });
  }

  async function recordListingView(id) {
    if (state.listingViewRequests.has(id) || !state.serverAvailable) return;
    state.listingViewRequests.add(id);
    try {
      const engagement = await api.request(`/listings/${id}/view`, { method: "POST" });
      applyListingEngagement(id, engagement);
    } catch (error) {
      state.listingViewRequests.delete(id);
      reportClientError("listing_view", error);
    }
  }

  async function toggleListingLike(id) {
    const listing = findListing(id);
    if (!listing || state.listingLikeRequests.has(id)) return;
    if (listing.seller_id === state.me?.user.id) return notify("Нельзя поставить лайк собственному объявлению");
    state.listingLikeRequests.add(id);
    try {
      const engagement = await api.request(`/listings/${id}/like`, { method: listing.liked_by_me ? "DELETE" : "POST" });
      applyListingEngagement(id, engagement);
    } catch (error) { notify(error.message); }
    finally { state.listingLikeRequests.delete(id); }
  }

  function applyListingEngagement(id, engagement) {
    [state.regular, state.unique, state.profile?.active_listings, state.profile?.sold_listings, state.profile?.purchases]
      .filter(Boolean)
      .forEach((items) => items.forEach((item) => {
        if (String(item.id) === String(id)) Object.assign(item, {
          views_count: Number(engagement.views_count || 0),
          likes_count: Number(engagement.likes_count || 0),
          liked_by_me: Boolean(engagement.liked_by_me),
        });
      }));
    if (String(state.selectedListing?.id) === String(id)) {
      Object.assign(state.selectedListing, {
        views_count: Number(engagement.views_count || 0),
        likes_count: Number(engagement.likes_count || 0),
        liked_by_me: Boolean(engagement.liked_by_me),
      });
      if (state.currentView === "listing-detail") renderListingPage();
    }
    document.querySelectorAll(`[data-listing-views="${CSS.escape(String(id))}"]`).forEach((node) => { node.textContent = `👁 ${Number(engagement.views_count || 0)}`; });
    document.querySelectorAll(`[data-listing-like="${CSS.escape(String(id))}"]`).forEach((button) => {
      button.classList.toggle("is-liked", Boolean(engagement.liked_by_me));
      button.setAttribute("aria-pressed", engagement.liked_by_me ? "true" : "false");
      button.textContent = `${engagement.liked_by_me ? "♥" : "♡"} ${Number(engagement.likes_count || 0)}`;
    });
  }

  function renderTraining() {
    elements.trainingCards.replaceChildren(...state.training.map((product) => {
      const card = document.createElement("article"); card.className = `training-card${product.pinned ? " is-pinned" : ""}${!product.published ? " is-draft" : ""}`;
      const open = document.createElement("button"); open.type = "button"; open.className = "training-card__open"; open.dataset.openTrainingProduct = product.id;
      const media = document.createElement("div"); media.className = "training-card__media"; const image = document.createElement("img"); image.src = absoluteMediaUrl(product.cover_url); image.alt = product.title; media.append(image);
      const badge = document.createElement("span"); badge.className = "premium-mark"; badge.textContent = product.pinned ? "PREMIUM · PINNED" : "PREMIUM";
      const body = document.createElement("div"); body.className = "training-card__body";
      const type = document.createElement("span"); type.className = "training-type"; type.textContent = trainingTypeLabel(product.product_type);
      const title = document.createElement("h3"); title.textContent = product.title;
      const description = document.createElement("p"); description.textContent = product.short_description;
      const footer = document.createElement("div"); footer.className = "training-card__footer"; const price = document.createElement("strong"); price.append(document.createTextNode(`${formatNumber(product.price_af_coins)} `), coin("af-coin--small")); const arrow = document.createElement("span"); arrow.textContent = "Подробнее ›"; footer.append(price, arrow);
      body.append(badge, type, title, description, footer); open.append(media, body); card.append(open);
      const purchase = state.trainingPurchases.find((item) => String(item.product_id) === String(product.id));
      if (state.me?.user.id !== product.admin_id) {
        const buy = document.createElement("button"); buy.type = "button"; buy.className = "training-card__buy"; buy.dataset.buyTraining = product.id;
        buy.disabled = Boolean(purchase) || product.availability !== "available";
        buy.textContent = purchase ? "Уже куплено" : product.availability === "available" ? "Купить" : trainingAvailabilityLabel(product.availability);
        card.append(buy);
      }
      if (state.me?.user.role === "admin") { const actions = document.createElement("div"); actions.className = "training-admin-actions"; const edit = document.createElement("button"); edit.dataset.editTraining = product.id; edit.textContent = "Изменить"; const remove = document.createElement("button"); remove.dataset.deleteTraining = product.id; remove.textContent = "Удалить"; actions.append(edit, remove); card.append(actions); }
      return card;
    }));
    elements.trainingEmpty.hidden = state.training.length > 0;
  }

  async function buyNowFlow(id) {
    const listing = [...state.regular, ...state.unique, state.selectedListing].filter(Boolean).find((item) => String(item.id) === String(id));
    if (!listing) return notify("Объявление не найдено");
    if (listing.status !== "active") return notify("Объявление уже недоступно");
    if (state.me?.user.id === listing.seller_id) return notify("Нельзя купить собственное объявление");
    const price = Number(listing.effective_price_af_coins ?? listing.price_af_coins);
    state.purchaseFlow = { listing, stage: "confirm", busy: false, intentId: null };
    elements.purchaseModalTitle.textContent = "Покупка автомобиля";
    elements.purchaseModalText.textContent = `Цена: ${formatNumber(price)} AF Coins`;
    elements.purchaseModalAmount.replaceChildren(document.createTextNode(`${formatNumber(price)} `), coin("af-coin--small"));
    elements.purchaseModalNote.textContent = "Деньги будут под защитой до получения автомобиля. Продавец получит их только после того, как вы подтвердите, что получили машину.";
    elements.purchaseModalAction.textContent = "Подтвердить покупку";
    elements.purchaseModalAction.disabled = false;
    openDialog(elements.purchaseModal);
  }

  function closePurchaseFlow() {
    if (state.purchaseFlow?.busy) return;
    if (elements.purchaseModal?.open) elements.purchaseModal.close();
    state.purchaseFlow = null;
  }

  async function runPurchaseFlowAction() {
    const flow = state.purchaseFlow;
    if (!flow || flow.busy) return;
    if (flow.kind === "listing-promotion-topup") return payListingPromotionShortfall(flow);
    if (flow.kind === "offer-topup") {
      const input = document.getElementById("topupAmount");
      if (input) input.value = String(flow.topupAmount);
      closePurchaseFlow();
      return openSecondary("topup");
    }
    if (flow.kind === "training") {
      if (flow.stage === "confirm") return executeTrainingPurchase(flow);
      if (flow.stage === "topup") return payTrainingShortfall(flow);
    }
    if (flow.stage === "confirm") return executeSafeListingPurchase(flow);
    if (flow.stage === "topup") return payListingShortfall(flow);
    closePurchaseFlow();
  }

  async function executeSafeListingPurchase(flow) {
    flow.busy = true; elements.purchaseModalAction.disabled = true; elements.purchaseModalAction.textContent = "Проверяем…";
    try {
      const deal = await api.request(`/listings/${flow.listing.id}/purchase`, { method: "POST" });
      await finishListingPurchase(deal);
    } catch (error) {
      if (Number(error.status) === 402 && error.detail?.code === "insufficient_af_coins") {
        const missing = Number(error.detail.missing_af_coins || 0);
        flow.stage = "topup"; flow.busy = false;
        elements.purchaseModalTitle.textContent = "Нужна точная доплата";
        elements.purchaseModalText.textContent = `Для покупки не хватает ${formatNumber(missing)} AF Coins`;
        elements.purchaseModalAmount.textContent = `${Math.ceil(missing)} Telegram Stars`;
        elements.purchaseModalNote.textContent = "AF Coins начисляются только после подтверждения оплаты Telegram. Затем покупка продолжится автоматически.";
        elements.purchaseModalAction.textContent = `Пополнить ${Math.ceil(missing)} ⭐ и купить`;
        elements.purchaseModalAction.disabled = false;
      } else {
        flow.busy = false; elements.purchaseModalAction.disabled = false; elements.purchaseModalAction.textContent = "Подтвердить покупку";
        elements.purchaseModalText.textContent = error.message;
        await refreshMarketplace().catch((refreshError) => reportClientError("refresh_after_purchase", refreshError));
      }
    }
  }

  async function payListingShortfall(flow) {
    if (!telegram?.initData || typeof telegram.openInvoice !== "function") {
      elements.purchaseModalNote.textContent = "Откройте AUTOFLOW MARKET внутри Telegram, чтобы оплатить счёт.";
      return;
    }
    flow.busy = true; elements.purchaseModalAction.disabled = true; elements.purchaseModalAction.textContent = "Создаём счёт…";
    try {
      const intent = await api.request(`/listings/${flow.listing.id}/purchase-topup-intent`, { method: "POST" });
      flow.intentId = intent.id;
      elements.purchaseModalAction.textContent = "Счёт открыт в Telegram";
      const invoiceStatus = await new Promise((resolve, reject) => {
        try { telegram.openInvoice(intent.invoice_url, resolve); }
        catch (error) { reject(error); }
      });
      if (invoiceStatus === "cancelled" || invoiceStatus === "failed") {
        flow.busy = false; elements.purchaseModalAction.disabled = false;
        elements.purchaseModalAction.textContent = `Пополнить ${intent.amount} ⭐ и купить`;
        elements.purchaseModalNote.textContent = invoiceStatus === "cancelled" ? "Оплата отменена. Баланс не изменён." : "Telegram не завершил оплату. Баланс не изменён.";
        return;
      }
      elements.purchaseModalText.textContent = "Telegram подтвердил оплату. Завершаем безопасную покупку…";
      const payment = await waitForStarPayment(intent.id);
      if (payment.status !== "paid") throw new Error("Сервер ещё не получил подтверждение оплаты. Попробуйте проверить через несколько секунд.");
      const result = await api.request(`/wallet/star-payments/intents/${intent.id}/resume-checkout`, { method: "POST" });
      state.me.wallet = result.wallet;
      if (result.checkout_status === "completed") return await finishListingPurchase({ id: result.deal_id });
      flow.stage = "done"; flow.busy = false; elements.purchaseModalAction.disabled = false; elements.purchaseModalAction.textContent = "Закрыть";
      elements.purchaseModalTitle.textContent = result.checkout_status === "listing_unavailable" ? "Объявление уже недоступно" : "Покупка не завершена";
      elements.purchaseModalText.textContent = result.message || "Пополненные AF Coins сохранены на вашем балансе.";
      elements.purchaseModalAmount.textContent = "AF Coins сохранены";
      elements.purchaseModalNote.textContent = "Средства не потеряны и доступны в вашем внутреннем балансе.";
      await refreshMarketplace();
    } catch (error) {
      flow.busy = false; elements.purchaseModalAction.disabled = false; elements.purchaseModalAction.textContent = "Повторить"; elements.purchaseModalText.textContent = error.message;
    }
  }

  async function payListingPromotionShortfall(flow) {
    if (!telegram?.initData || typeof telegram.openInvoice !== "function") {
      elements.purchaseModalNote.textContent = "Откройте AUTOFLOW MARKET внутри Telegram, чтобы пополнить баланс.";
      return;
    }
    flow.busy = true;
    elements.purchaseModalAction.disabled = true;
    try {
      if (!flow.intentId) {
        elements.purchaseModalAction.textContent = "Создаём счёт…";
        const amount = Math.ceil(flow.missing);
        const intent = await api.request("/wallet/star-payments/intent", {
          method: "POST",
          body: JSON.stringify({ amount, purpose: "listing_promotion_topup" }),
        });
        flow.intentId = intent.id;
        const invoiceStatus = await new Promise((resolve, reject) => {
          try { telegram.openInvoice(intent.invoice_url, resolve); }
          catch (error) { reject(error); }
        });
        if (["cancelled", "failed"].includes(invoiceStatus)) {
          flow.busy = false;
          flow.intentId = null;
          elements.purchaseModalAction.disabled = false;
          elements.purchaseModalAction.textContent = `Пополнить ${amount} AF`;
          elements.purchaseModalNote.textContent = "Оплата не завершена. Объявление и баланс не изменены.";
          return;
        }
      }
      elements.purchaseModalTitle.textContent = "⏳ Платёж подтверждается";
      elements.purchaseModalText.textContent = "Не закрывайте приложение. Обычно это занимает несколько секунд.";
      elements.purchaseModalAction.textContent = "Проверяем…";
      const payment = await waitForStarPayment(flow.intentId);
      if (payment?.status !== "paid") {
        flow.busy = false;
        elements.purchaseModalAction.disabled = false;
        elements.purchaseModalAction.textContent = "Проверить снова";
        elements.purchaseModalNote.textContent = "Баланс изменится только после подтверждения backend.";
        return;
      }
      state.me = await api.request("/me");
      renderBalance();
      elements.purchaseModalTitle.textContent = "✅ AF Coins зачислены";
      elements.purchaseModalText.textContent = flow.submission ? "Публикуем и закрепляем объявление…" : "Закрепляем объявление…";
      let listing;
      if (flow.submission) {
        listing = await api.request(flow.submission.path, {
          method: flow.submission.method,
          body: JSON.stringify(flow.submission.payload),
        });
      } else {
        listing = await api.request(`/listings/${flow.listingId}/promote`, { method: "POST" });
      }
      if (elements.purchaseModal?.open) elements.purchaseModal.close();
      state.purchaseFlow = null;
      if (flow.submission) await finishListingSubmission(flow.submission);
      else {
        await refreshMarketplace();
        notify(`Объявление закреплено до ${formatDate(listing.pinned_until)}`);
      }
    } catch (error) {
      flow.busy = false;
      elements.purchaseModalAction.disabled = false;
      if (Number(error.status) === 402 && error.detail?.purpose === "listing_promotion") {
        flow.missing = Number(error.detail.missing_af_coins || flow.missing || 0);
        flow.intentId = null;
        elements.purchaseModalTitle.textContent = "Недостаточно AF Coins";
        elements.purchaseModalText.textContent = `Для закрепления не хватает ${formatNumber(flow.missing)} AF.`;
        elements.purchaseModalAction.textContent = `Пополнить ${Math.ceil(flow.missing)} AF`;
        elements.purchaseModalNote.textContent = "Баланс изменился до завершения публикации. Можно доплатить новую точную разницу.";
        return;
      }
      elements.purchaseModalAction.textContent = flow.intentId ? "Повторить публикацию" : `Пополнить ${Math.ceil(flow.missing)} AF`;
      elements.purchaseModalNote.textContent = error.message;
    }
  }

  async function finishListingPurchase(deal) {
    if (elements.purchaseModal?.open) elements.purchaseModal.close();
    state.purchaseFlow = null;
    await refreshMarketplace();
    showPurchaseSuccess(
      "✅ Машина куплена",
      "Укажите данные, чтобы продавец смог передать вам автомобиль.",
    );
    if (!deal?.id) return;
    await openDealConversation(deal.id);
  }

  function showPurchaseSuccess(title, message) {
    elements.successTitle.textContent = title; elements.successText.textContent = message; elements.successOverlay.hidden = false;
    window.setTimeout(() => { elements.successOverlay.hidden = true; }, 2200);
  }

  async function submitListing(event) {
    event.preventDefault();
    if (!state.serverAvailable) return notify("Сервер недоступен");
    const form = elements.carForm;
    const formData = new FormData(form);
    const button = form.querySelector("button[type=submit]");
    if (button.disabled) return;
    const originalButtonText = button.textContent;
    let listingSubmission = null;
    button.disabled = true;
    try {
      const payload = {
        brand: String(formData.get("brand")).trim(),
        power_hp: Number(formData.get("power_hp")),
        max_speed_kph: Number(formData.get("max_speed_kph")),
        delivery_time_estimate: String(formData.get("delivery_time_estimate")),
        description: String(formData.get("description") || "").trim(),
        price_af_coins: Number(formData.get("price_af_coins")),
      };
      if (!state.editingListingId) {
        state.pendingListingRequestId ||= createRequestId();
        payload.client_request_id = state.pendingListingRequestId;
      }
      if (!payload.brand) throw new Error("Введите название автомобиля");
      if (!Number.isInteger(payload.power_hp) || payload.power_hp <= 0) throw new Error("Мощность должна быть положительным целым числом");
      if (!Number.isInteger(payload.max_speed_kph) || payload.max_speed_kph <= 0) throw new Error("Максимальная скорость должна быть положительным целым числом");
      if (!payload.description) throw new Error("Добавьте описание автомобиля");
      if (!Number.isFinite(payload.price_af_coins) || payload.price_af_coins < 1) throw new Error("Цена должна быть не меньше 1 AF Coin");
      if (!state.editingListingId && state.photoFiles.length < 1) throw new Error("Добавьте хотя бы одну фотографию автомобиля");
      if (state.photoFiles.length > 10) throw new Error("Можно добавить не более 10 фотографий");
      const promotionSelected = formData.get("promote_for_24h") === "on";
      let shouldPromote = promotionSelected;
      if (promotionSelected && state.listingMode === "regular") {
        shouldPromote = state.editingListingId
          ? await confirmAction("Закрепить объявление за 5 AF Coins?")
          : await chooseInitialPromotion();
      }
      const imageUrls = [];
      for (const [index, file] of state.photoFiles.entries()) {
        button.textContent = `Загрузка фото ${index + 1} из ${state.photoFiles.length}…`;
        try {
          const uploaded = await api.upload(file);
          imageUrls.push(uploaded.url);
        } catch (error) {
          error.message = `Не удалось загрузить фотографию ${index + 1}: ${error.message}`;
          error.photoIndex = index + 1;
          throw error;
        }
      }
      if (!state.editingListingId || imageUrls.length) payload.image_urls = imageUrls;
      const path = state.editingListingId ? `/listings/${state.editingListingId}` : state.listingMode === "unique" ? "/admin/listings/unique" : "/listings";
      if (state.listingMode === "unique") payload.pinned = shouldPromote;
      else if (!state.editingListingId) payload.promote_for_24h = shouldPromote;
      listingSubmission = {
        payload,
        path,
        method: state.editingListingId ? "PATCH" : "POST",
        wasEditing: Boolean(state.editingListingId),
        targetView: state.listingMode === "unique" ? "unique" : "market",
      };
      button.textContent = state.editingListingId ? "Сохраняем…" : "Публикуем…";
      const savedListing = await api.request(path, { method: listingSubmission.method, body: JSON.stringify(payload) });
      let promotionError = null;
      if (shouldPromote && !savedListing.pinned && (state.editingListingId || state.listingMode === "unique")) {
        try {
          const promotionPath = state.listingMode === "unique" ? `/admin/listings/${savedListing.id}/promote` : `/listings/${savedListing.id}/promote`;
          await api.request(promotionPath, { method: "POST" });
        } catch (error) { promotionError = error; }
      }
      await finishListingSubmission(listingSubmission, promotionError);
    } catch (error) {
      if (
        listingSubmission
        && listingSubmission.method === "POST"
        && Number(error.status) === 402
        && error.detail?.purpose === "listing_promotion"
      ) {
        return openListingPromotionTopup(listingSubmission, error);
      }
      const errorId = error?.photoIndex ? reportClientError("listing_photo_upload", error) : null;
      notify(`${error.message}${errorId ? ` Код: ${errorId}` : ""}`);
    }
    finally { button.disabled = false; button.textContent = originalButtonText; }
  }

  async function finishListingSubmission(submission, promotionError = null) {
    elements.carForm.reset();
    elements.photoPreview.replaceChildren();
    state.photoFiles = [];
    state.editingListingId = null;
    state.pendingListingRequestId = null;
    await refreshMarketplace();
    await navigate(submission.targetView);
    if (promotionError) notify(`Объявление сохранено, но не закреплено: ${promotionError.message}`);
    else notify(submission.wasEditing ? "Объявление обновлено бесплатно" : "Объявление опубликовано");
  }

  function openListingPromotionTopup(submission, error, listingId = null) {
    const available = Number(error.detail?.available_af_coins || 0);
    const missing = Number(error.detail?.missing_af_coins || 0);
    state.purchaseFlow = {
      kind: "listing-promotion-topup",
      stage: "topup",
      busy: false,
      intentId: null,
      missing,
      submission,
      listingId,
    };
    elements.purchaseModalTitle.textContent = "Недостаточно AF Coins";
    elements.purchaseModalText.textContent = `На балансе: ${formatNumber(available)} AF. Для закрепления не хватает ${formatNumber(missing)} AF.`;
    elements.purchaseModalAmount.replaceChildren(document.createTextNode(`${formatNumber(missing)} `), coin("af-coin--small"));
    elements.purchaseModalNote.textContent = "После подтверждения оплаты объявление будет опубликовано или закреплено автоматически.";
    elements.purchaseModalAction.textContent = `Пополнить ${Math.ceil(missing)} AF`;
    elements.purchaseModalAction.disabled = false;
    openDialog(elements.purchaseModal);
  }

  function findListing(id) { return [...state.regular, ...state.unique, ...(state.profile?.active_listings || [])].find((item) => item.id === id); }

  async function openListingDetails(id) {
    try {
      const listing = await api.request(`/listings/${id}`);
      state.selectedListing = listing;
      state.previousView = state.currentView === "listing-detail" ? state.previousView : state.currentView;
      renderListingPage();
      await navigate("listing-detail");
      window.setTimeout(() => { if (state.selectedListing?.id === id && state.currentView === "listing-detail") void recordListingView(id); }, 750);
    } catch (error) { notify(error.message); }
  }

  function renderListingPage() {
    const listing = state.selectedListing;
    if (!listing) return;
    const imageUrl = safeArray(listing.images)[0];
    const sold = listing.status !== "active";
    elements.listingPageImage.parentElement.classList.toggle("is-sold", sold);
    elements.listingPageSold.hidden = !sold;
    elements.listingPageImage.hidden = sold || !imageUrl;
    elements.listingPageImagePlaceholder.hidden = sold || Boolean(imageUrl);
    if (imageUrl) elements.listingPageImage.src = imageUrl;
    else elements.listingPageImage.removeAttribute("src");
    elements.listingPageKind.textContent = listing.listing_type === "unique" ? "Уникальная машина" : "Объявление";
    elements.listingPageTitle.textContent = listingTitle(listing);
    elements.listingPageBrand.textContent = listing.brand || "Автомобиль";
    const effectivePrice = listing.effective_price_af_coins ?? listing.price_af_coins;
    elements.listingPagePrice.textContent = formatNumber(effectivePrice);
    elements.listingPageDescription.textContent = listing.description || "Описание не указано";
    elements.listingPageSpecs.replaceChildren(...[
      `Мощность: ${listing.power_hp} л.с.`,
      `Максимальная скорость: ${listing.max_speed_kph} км/ч`,
      `Передача: ${deliveryTimeLabel(listing.delivery_time_estimate)}`,
      `Статус: ${statusLabel(listing.status)}`,
    ].map((value) => { const item = document.createElement("span"); item.textContent = value; return item; }));
    elements.listingPageViews.textContent = `👁 ${Number(listing.views_count || 0)} просмотров`;
    elements.listingPageLike.textContent = `${listing.liked_by_me ? "♥" : "♡"} ${Number(listing.likes_count || 0)} лайков`;
    elements.listingPageLike.classList.toggle("is-liked", Boolean(listing.liked_by_me));
    const isOwner = listing.seller_id === state.me?.user.id;
    elements.listingPageLike.disabled = isOwner;
    elements.listingPageBuy.hidden = isOwner;
    elements.listingPageChat.hidden = isOwner;
    elements.listingPageOfferButton.hidden = isOwner;
    elements.listingPageOffer.hidden = true;
    elements.listingPageBuy.disabled = listing.status !== "active";
    elements.listingPageBuy.textContent = `Купить за ${formatNumber(effectivePrice)} AF`;
    elements.listingOfferAmount.value = formatNumber(effectivePrice);
  }

  async function likeSelectedListing() {
    if (!state.selectedListing) return;
    await toggleListingLike(state.selectedListing.id);
    const refreshed = await api.request(`/listings/${state.selectedListing.id}`);
    state.selectedListing = refreshed;
    renderListingPage();
  }

  function buySelectedListing() {
    if (state.selectedListing) void buyNowFlow(state.selectedListing.id);
  }

  function chatFromSelectedListing() {
    if (state.selectedListing) void startConversation(state.selectedListing.id);
  }

  function showListingOfferForm() {
    elements.listingPageOffer.hidden = false;
    elements.listingPageOfferButton.hidden = true;
    window.setTimeout(() => elements.listingOfferAmount.focus({ preventScroll: true }), 30);
  }

  async function submitListingOffer(event) {
    event.preventDefault();
    if (!state.selectedListing) return;
    const amount = Number(elements.listingOfferAmount.value);
    if (!Number.isFinite(amount) || amount < 1) return notify("Цена предложения должна быть не меньше 1 AF");
    await createOffer(amount, state.selectedListing.id);
  }

  function editListing(id) {
    const listing = findListing(id); if (!listing) return;
    state.listingMode = listing.listing_type;
    state.editingListingId = id;
    state.pendingListingRequestId = null;
    state.photoFiles = [];
    elements.carForm.reset(); elements.photoPreview.replaceChildren();
    elements.brandInput.value = listing.brand;
    elements.carForm.elements.power_hp.value = listing.power_hp; elements.carForm.elements.max_speed_kph.value = listing.max_speed_kph; elements.carForm.elements.description.value = listing.description; elements.priceInput.value = listing.price_af_coins;
    elements.carForm.elements.delivery_time_estimate.value = listing.delivery_time_estimate || "up_to_1h";
    document.getElementById("listingType").value = listing.listing_type;
    document.getElementById("addTitle").textContent = "Редактировать объявление";
    const freeAdminPromotion = state.me.user.role === "admin" && listing.listing_type === "unique";
    configurePromotionOption(freeAdminPromotion);
    elements.carForm.elements.promote_for_24h.checked = !listing.pinned;
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
    if (!freeAdminPromotion && !(await confirmAction("Закрепить объявление за 5 AF Coins?"))) return;
    try { const listing = await api.request(freeAdminPromotion ? `/admin/listings/${id}/promote` : `/listings/${id}/promote`, { method: "POST" }); await refreshMarketplace(); notify(`Объявление закреплено до ${formatDate(listing.pinned_until)}`); }
    catch (error) {
      if (!freeAdminPromotion && Number(error.status) === 402 && error.detail?.purpose === "listing_promotion") {
        return openListingPromotionTopup(null, error, id);
      }
      notify(error.message);
    }
  }

  function previewPhotos(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) { state.photoFiles = []; elements.photoPreview.replaceChildren(); return; }
    if (files.length > 10) {
      event.target.value = "";
      state.photoFiles = [];
      return notify("Можно добавить не более 10 фотографий");
    }
    const supportedExtension = /\.(jpe?g|png|webp|heic|heif)$/i;
    const unsupported = files.find((file) => !(file.type || "").startsWith("image/") && !supportedExtension.test(file.name || ""));
    if (unsupported) {
      event.target.value = "";
      state.photoFiles = [];
      return notify(`Файл «${unsupported.name}» не является поддерживаемой фотографией`);
    }
    const oversized = files.find((file) => file.size > 30 * 1024 * 1024);
    if (oversized) {
      event.target.value = "";
      state.photoFiles = [];
      return notify(`Фотография «${oversized.name}» превышает 30 МБ`);
    }
    state.photoFiles = files;
    elements.photoPreview.replaceChildren(...state.photoFiles.map((file, index) => {
      const image = document.createElement("img");
      image.src = URL.createObjectURL(file);
      image.alt = `Фотография ${index + 1}`;
      image.addEventListener("load", () => URL.revokeObjectURL(image.src), { once: true });
      image.addEventListener("error", () => URL.revokeObjectURL(image.src), { once: true });
      return image;
    }));
  }

  function beginPriceFilterInput(event) {
    document.body.classList.add("filter-keyboard-open");
    window.setTimeout(() => event.currentTarget.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" }), 80);
  }

  function endPriceFilterInput() {
    document.body.classList.remove("filter-keyboard-open");
    renderListings();
  }

  function finishPriceFilterInput(event) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    renderListings();
    event.currentTarget.blur();
  }

  function selectPrice(button) {
    document.querySelectorAll("[data-price]").forEach((item) => item.classList.toggle("is-active", item === button));
    elements.priceInput.value = button.dataset.price;
  }

  async function loadCatalog() {
    if (state.catalog.brands?.length) return;
    try {
      state.catalog = await api.resource("data/vehicle_catalog.json", { timeoutMs: 8000, retries: 1 });
      state.failedOptional.delete("catalog");
    } catch (error) {
      state.failedOptional.add("catalog");
      reportClientError("catalog_suggestions", error);
      updateSyncStatus();
    }
  }

  async function updateBrandSuggestions() {
    await loadCatalog();
    const query = elements.brandInput.value.trim().toLowerCase();
    const matches = state.catalog.brands.filter((brand) => brand.name.toLowerCase().startsWith(query));
    fillDatalist("brandSuggestions", matches.map((brand) => brand.name));
  }

  function fillDatalist(id, values) {
    const list = document.getElementById(id);
    list.replaceChildren(...values.map((value) => new Option(value, value)));
  }

  function updateFilterOptions() {
    setSelectOptions(elements.brandFilter, "Автомобиль", uniqueValues(state.regular.map((item) => item.brand)));
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
    [elements.brandFilter, elements.priceMinFilter, elements.priceMaxFilter, elements.powerFilter, elements.speedFilter].forEach((control) => { control.value = ""; });
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
    renderTrainingLibrary();
    document.getElementById("frozenBalance").textContent = Number(profile.wallet.frozen_balance).toFixed(2);
    document.getElementById("purchasedBalance").textContent = Number(profile.wallet.purchased_balance).toFixed(2);
    document.getElementById("earnedBalance").textContent = Number(profile.wallet.earned_balance).toFixed(2);
  }

  function renderTrainingLibrary() {
    if (!elements.personalTrainingPurchases || !elements.automaticTrainingPurchases) return;
    const personal = state.trainingPurchases.filter((item) => item.product_type === "personal");
    const automatic = state.trainingPurchases.filter((item) => item.product_type === "automatic");
    elements.personalTrainingPurchases.replaceChildren(...personal.map(createTrainingLibraryCard));
    elements.automaticTrainingPurchases.replaceChildren(...automatic.map(createTrainingLibraryCard));
    document.getElementById("personalTrainingEmpty").hidden = personal.length > 0;
    document.getElementById("automaticTrainingEmpty").hidden = automatic.length > 0;
  }

  function createTrainingLibraryCard(purchase) {
    const card = document.createElement("article"); card.className = "training-library-card";
    const image = document.createElement("img"); image.src = absoluteMediaUrl(purchase.cover_url_snapshot); image.alt = purchase.title_snapshot;
    const copy = document.createElement("div");
    const title = document.createElement("strong"); title.textContent = purchase.title_snapshot;
    const date = document.createElement("small"); date.textContent = `Куплено ${formatDate(purchase.created_at)}`;
    const status = document.createElement("span");
    status.textContent = purchase.product_type === "personal" ? trainingPurchaseStatusLabel(purchase.status) : trainingDeliveryStatusLabel(purchase.delivery_status);
    copy.append(title, status, date); card.append(image, copy);
    if (purchase.product_type === "automatic" && purchase.status === "completed") {
      const repeat = document.createElement("button"); repeat.type = "button"; repeat.dataset.trainingRedeliver = purchase.id; repeat.textContent = purchase.delivery_status === "sending" ? "Отправляется…" : "Получить материалы повторно"; repeat.disabled = purchase.delivery_status === "sending";
      card.append(repeat);
    }
    return card;
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
      if (listing.images?.[0]) { image.src = absoluteMediaUrl(listing.images[0]); image.alt = listingTitle(listing); }
      else image.className = "profile-mini-placeholder";
      const copy = document.createElement("div");
      const title = document.createElement("strong"); title.textContent = listingTitle(listing);
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
      const row = document.createElement("article"); row.className = "deal-row";
      const copy = document.createElement("div"); const title = document.createElement("strong"); title.textContent = `Сделка ${deal.id.slice(0, 8)}`;
      const date = document.createElement("small"); date.textContent = formatDate(deal.created_at); copy.append(title, date);
      const meta = document.createElement("div"); meta.className = "deal-row__meta";
      const status = document.createElement("b"); status.textContent = dealStatusLabel(deal.status);
      const chat = document.createElement("button"); chat.type = "button"; chat.dataset.openDealChat = deal.id; chat.textContent = "💬 Открыть чат";
      meta.append(status, chat); row.append(copy, meta); return row;
    }));
  }

function renderConversations(conversations) {
  const visibleConversations = conversations;
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

    const avatar = document.createElement("span"); avatar.className = "conversation-avatar";
    const avatarFallback = document.createElement("span"); avatarFallback.textContent = (conversation.counterparty.name || conversation.counterparty.username || "A").slice(0, 1).toUpperCase(); avatar.append(avatarFallback);
    if (conversation.counterparty.photo_url) { const image = document.createElement("img"); image.src = conversation.counterparty.photo_url; image.alt = ""; image.addEventListener("load", () => { avatarFallback.hidden = true; }); avatar.append(image); }
    const primary = document.createElement("span"); primary.className = "conversation-primary";
    const name = document.createElement("strong"); name.textContent = conversation.counterparty.name || "Пользователь";
    const time = document.createElement("time"); time.textContent = formatMessageTime(conversation.last_message_at);
    primary.append(name, time);
    const secondary = document.createElement("span"); secondary.className = "conversation-secondary";
    const preview = document.createElement("span"); preview.className = "conversation-preview"; preview.textContent = conversation.last_message || "Сделка создана";
    const username = document.createElement("span"); username.className = "conversation-username"; username.textContent = conversation.counterparty.username ? `@${conversation.counterparty.username}` : "";
    secondary.append(preview, username);
    open.append(avatar, primary, secondary);

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
    del.textContent = "Скрыть";

    row.append(open, del);
    elements.conversationList.append(row);
  });
}

async function hideConversation(conversationId) {
  try {
    await api.request(`/conversations/${conversationId}/hide`, { method: "POST" });
    if (state.profile) state.profile.conversations = state.profile.conversations.filter((item) => String(item.id) !== String(conversationId));
    renderConversations(state.profile?.conversations || []);
    notify("Чат скрыт. Новое сообщение вернёт его в список");
  } catch (error) { notify(error.message); }
}

async function hideCurrentConversation() {
  if (!state.currentConversation?.id) return navigate(state.previousView || "market");
  await hideConversation(state.currentConversation.id);
  navigate("profile");
  switchProfileTab("chats");
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
    try {
      const conversation = await api.request(`/conversations/listing/${listingId}`, { method: "POST" });
      if (conversation.id) return await openConversation(conversation.id, conversation, state.currentView);
      state.currentConversation = conversation;
      state.messages = [];
      state.previousView = state.currentView;
      renderConversation();
      await navigate("deal-chat");
      document.getElementById("chatInput").focus({ preventScroll: true });
    }
    catch (error) { notify(error.message); }
  }

  async function openConversation(id, prefetched = null, returnView = null) {
    try {
      const [conversationResult, messagesResult] = await Promise.allSettled([
        prefetched ? Promise.resolve(prefetched) : api.request(`/conversations/${id}`),
        api.request(`/conversations/${id}/messages`),
      ]);
      if (conversationResult.status === "rejected") throw conversationResult.reason;
      const conversation = conversationResult.value;
      const messages = messagesResult.status === "fulfilled" ? safeArray(messagesResult.value) : [];
      if (messagesResult.status === "rejected") reportClientError("conversation_messages_initial", messagesResult.reason);
      state.currentConversation = conversation;
      state.messages = messages;
      state.previousView = returnView || (state.currentView === "profile" ? "profile" : "market");
      renderConversation();
      await navigate("deal-chat");
      try {
        await markConversationRead(id);
        state.messages = safeArray(await api.request(`/conversations/${id}/messages`));
        renderConversation();
      } catch (error) {
        reportClientError("conversation_read_refresh", error);
      }
      return true;
    } catch (error) { notify(error.message); return false; }
  }

  async function openDealConversation(dealId) {
    try {
      const conversation = await api.request(`/deals/${dealId}/conversation`, { method: "POST" });
      return await openConversation(conversation.id, conversation);
    } catch (error) { notify(error.message); return false; }
  }

  function renderConversation() {
    const details = state.currentConversation; if (!details) return;
    const other = details.counterparty;
    document.getElementById("chatName").textContent = other.name || "Пользователь";
    document.getElementById("chatActivity").textContent = [other.username ? `@${other.username}` : null, other.mini_app_last_active_at ? `в Mini App ${formatMessageTime(other.mini_app_last_active_at)}` : null].filter(Boolean).join(" · ") || "Активность неизвестна";
    document.getElementById("chatStatus").textContent = details.deal ? dealStatusLabel(details.deal.status) : "Переписка";
    const avatarFallback = document.getElementById("chatAvatarFallback"); const avatarImage = document.getElementById("chatAvatarImage");
    avatarFallback.textContent = (other.name || other.username || "A").slice(0, 1).toUpperCase();
    avatarImage.hidden = !other.photo_url; avatarFallback.hidden = Boolean(other.photo_url); if (other.photo_url) avatarImage.src = other.photo_url;
    document.getElementById("chatHideButton").hidden = !details.id;
    elements.chatListing.replaceChildren();
    if (details.listing.images?.[0]) { const image = document.createElement("img"); image.src = absoluteMediaUrl(details.listing.images[0]); image.alt = listingTitle(details.listing); elements.chatListing.append(image); }
    const listingCopy = document.createElement("div"); const title = document.createElement("strong"); title.textContent = listingTitle(details.listing);
    const priceValue = details.deal?.price_af_coins ?? details.accepted_price_af_coins ?? details.listing.price_af_coins;
    const price = document.createElement("small"); price.textContent = `${formatNumber(priceValue)} AF Coins`;
    const context = document.createElement("small"); context.textContent = `${details.deal ? dealStatusLabel(details.deal.status) : "Объявление"} · передача ${deliveryTimeLabel(details.listing.delivery_time_estimate)}`;
    listingCopy.append(title, price, context);
    const listingAction = document.createElement("span"); listingAction.textContent = "Открыть ›"; elements.chatListing.append(listingCopy, listingAction);
    const renderedMessages = []; let previousDay = "";
    state.messages.forEach((message) => {
      const day = new Date(message.created_at).toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
      if (day !== previousDay) { const divider = document.createElement("div"); divider.className = "message-day"; divider.textContent = day; renderedMessages.push(divider); previousDay = day; }
      const isOffer = message.message_type === "offer";
      const bubble = document.createElement("div"); bubble.className = `message${message.sender_id === state.me.user.id ? " is-own" : ""}${message.message_type === "system" ? " is-system" : ""}${isOffer ? " is-offer" : ""}`;
      if (isOffer) renderOfferMessage(bubble, message);
      else bubble.append(document.createTextNode(message.body));
      const meta = document.createElement("small"); meta.className = "message-meta"; const time = document.createElement("span"); time.textContent = formatMessageTime(message.created_at); meta.append(time);
      if (message.sender_id === state.me.user.id && message.message_type !== "system") { const receipt = document.createElement("span"); receipt.className = "message-receipt"; receipt.textContent = message.is_read ? "✓✓" : "✓"; receipt.title = message.is_read ? "Прочитано" : "Получено сервером"; meta.append(receipt); }
      bubble.append(meta); renderedMessages.push(bubble);
    });
    elements.dealMessages.replaceChildren(...renderedMessages);
    renderDealDeliveryPanel();
    renderOffers();
    renderDealControls();
    requestAnimationFrame(() => { elements.dealMessages.scrollTop = elements.dealMessages.scrollHeight; });
  }

  function renderOfferMessage(bubble, message) {
    const offer = safeArray(state.currentConversation?.offers).find(
      (item) => String(item.id) === String(message.price_offer_id || ""),
    );
    const fallbackAmount = String(message.body || "").match(/[\d]+(?:[.,][\d]+)?/)?.[0]?.replace(",", ".");
    const amount = offer?.amount_af_coins ?? fallbackAmount ?? "—";
    const heading = document.createElement("strong");
    heading.className = "offer-message__title";
    heading.textContent = "💰 Предложение цены";
    const price = document.createElement("span");
    price.className = "offer-message__price";
    price.textContent = `${formatNumber(amount)} AF`;
    const status = document.createElement("span");
    status.className = "offer-message__status";
    if (offer?.status === "accepted") status.textContent = `✅ Предложение принято — ${formatNumber(amount)} AF`;
    else if (offer?.status === "rejected") status.textContent = "❌ Предложение отклонено";
    else if (offer?.status === "countered") status.textContent = "↪️ Отправлено встречное предложение";
    else status.textContent = "Ожидается ответ продавца";
    bubble.append(heading, price, status);
    if (offer?.status === "pending" && offer.offered_by_id !== state.me.user.id) {
      const actions = document.createElement("div");
      actions.className = "offer-message__actions";
      const accept = document.createElement("button");
      accept.type = "button"; accept.dataset.offerAction = "accept"; accept.dataset.offerId = offer.id; accept.textContent = "Принять";
      const reject = document.createElement("button");
      reject.type = "button"; reject.dataset.offerAction = "reject"; reject.dataset.offerId = offer.id; reject.textContent = "Отклонить";
      actions.append(accept, reject);
      bubble.append(actions);
    }
  }

  function renderDealDeliveryPanel() {
    const panel = elements.dealDeliveryPanel;
    const deal = state.currentConversation?.deal;
    panel.replaceChildren();
    panel.hidden = !deal;
    if (!deal) return;
    const isBuyer = deal.buyer_id === state.me.user.id;
    const hasDetails = Boolean(deal.buyer_game_id && deal.buyer_server && deal.preferred_delivery_time && deal.delivery_timezone);
    const requiresDetails = isBuyer && !hasDetails && ["paid", "seller_contacted"].includes(deal.status);
    document.body.classList.toggle("deal-details-required", requiresDetails);

    const title = document.createElement("strong");
    const copy = document.createElement("p");
    if (deal.status === "completed") {
      title.textContent = isBuyer ? "✅ Покупка завершена" : "✅ Продажа завершена";
      copy.textContent = isBuyer ? "Автомобиль успешно получен." : "Деньги зачислены.";
      panel.append(title, copy);
      return;
    }
    if (deal.status === "transfer_in_progress") {
      title.textContent = isBuyer ? "🚗 Продавец сообщил о передаче" : "⏳ Ожидаем подтверждение покупателя";
      copy.textContent = isBuyer
        ? "Вы получили автомобиль?"
        : "Вы сообщили, что автомобиль передан.\nДеньги будут начислены после подтверждения покупателя.";
      panel.append(title, copy);
      return;
    }
    if (isBuyer && hasDetails) {
      title.textContent = "⏳ Ожидается передача автомобиля";
      copy.textContent = `Продавец получил ваши данные.\nID: ${deal.buyer_game_id}\nСервер: ${deal.buyer_server}\nВремя: ${deal.preferred_delivery_time} МСК\nЕсли необходимо что-то уточнить, используйте чат ниже.`;
      panel.append(title, copy);
      return;
    }
    if (!isBuyer && hasDetails) {
      title.textContent = "Передача автомобиля";
      copy.textContent = `Покупатель: ${state.currentConversation?.counterparty?.name || "Покупатель"}\nСервер: ${deal.buyer_server}\nВремя: ${deal.preferred_delivery_time} МСК`;
      const idButton = document.createElement("button");
      idButton.type = "button";
      idButton.className = "deal-delivery__copy-id";
      idButton.dataset.copyGameId = deal.buyer_game_id;
      idButton.textContent = `ID: ${deal.buyer_game_id}  ⧉`;
      panel.append(title, copy, idButton);
      return;
    }
    if (!isBuyer) {
      title.textContent = "⏳ Ожидаем данные покупателя";
      copy.textContent = "Покупатель ещё не указал игровой ID и удобное время передачи. Как только данные появятся, этот блок обновится.";
      panel.append(title, copy);
      return;
    }

    title.textContent = "✅ Машина куплена";
    copy.textContent = "Укажите данные, чтобы продавец смог передать вам автомобиль.";
    const form = document.createElement("form");
    form.className = "deal-delivery__form";
    form.innerHTML = `
      <label>Игровой ID<input name="buyer_game_id" type="text" inputmode="text" maxlength="128" autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck="false" placeholder="AB123456" required></label>
      <label>Сервер<input name="buyer_server" type="text" maxlength="128" autocomplete="off" placeholder="Введите сервер" required></label>
      <label class="deal-delivery__time">Удобное время сегодня<input name="preferred_time" type="time" required></label>
      <small>Время указывается по МСК</small>
      <button type="submit">Отправить продавцу</button>`;
    form.addEventListener("submit", submitDealDeliveryDetails);
    panel.append(title, copy, form);
  }

  async function submitDealDeliveryDetails(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const dealId = state.currentConversation?.deal?.id;
    const gameId = form.elements.buyer_game_id.value.trim();
    const server = form.elements.buyer_server.value.trim();
    const preferredTime = form.elements.preferred_time.value;
    if (!dealId || !gameId || !server || !preferredTime) return notify("Заполните игровой ID, сервер и время");
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const updated = await api.request(`/deals/${dealId}/delivery-details`, {
        method: "PUT",
        body: JSON.stringify({
          buyer_game_id: gameId,
          buyer_server: server,
          preferred_time: preferredTime,
        }),
      });
      state.currentConversation.deal = updated;
      state.messages = await api.request(`/conversations/${state.currentConversation.id}/messages`);
      renderConversation();
    } catch (error) {
      notify(error.message);
      button.disabled = false;
    }
  }

  async function copyBuyerGameId(value) {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
      else {
        const input = document.createElement("textarea");
        input.value = value; input.setAttribute("readonly", ""); input.style.position = "fixed"; input.style.opacity = "0";
        document.body.append(input); input.select();
        const copied = document.execCommand("copy");
        input.remove();
        if (!copied) throw new Error("copy_failed");
      }
      notify("✅ ID скопирован");
    } catch (_error) { notify("Не удалось скопировать ID"); }
  }

  function renderOffers() {
    const conversation = state.currentConversation; elements.offerPanel.replaceChildren(); if (!conversation || conversation.deal) return;
    const linkedOfferIds = new Set(safeArray(state.messages).map((message) => message.price_offer_id).filter(Boolean).map(String));
    const pending = safeArray(conversation.offers).filter((item) => item.status === "pending" && !linkedOfferIds.has(String(item.id)));
    pending.forEach((offer) => {
      const row = document.createElement("div"); row.className = "offer-panel__row"; row.dataset.offerId = offer.id;
      const text = document.createElement("span"); text.append(document.createTextNode(`Предложение: ${formatNumber(offer.amount_af_coins)} `), coin("af-coin--small")); row.append(text);
      if (offer.offered_by_id !== state.me.user.id) {
        const accept = document.createElement("button"); accept.dataset.offerAction = "accept"; accept.dataset.offerId = offer.id; accept.textContent = "Принять";
        const reject = document.createElement("button"); reject.dataset.offerAction = "reject"; reject.dataset.offerId = offer.id; reject.textContent = "Отклонить";
        const counter = document.createElement("button"); counter.dataset.offerAction = "counter"; counter.dataset.offerId = offer.id; counter.textContent = "Своя цена"; row.append(accept, reject, counter);
      }
      elements.offerPanel.append(row);
    });
    const button = document.createElement("button"); button.dataset.newOffer = ""; button.textContent = "Предложить свою цену"; elements.offerPanel.append(button);
  }

  function renderDealControls() {
    const deal = state.currentConversation?.deal;
    window.clearInterval(state.dealTimerId);
    state.dealTimerId = null;
    elements.dealControls.replaceChildren();
    if (!deal || ["completed", "cancelled"].includes(deal.status)) return;
    const isBuyer = deal.buyer_id === state.me.user.id;
    const isSeller = deal.seller_id === state.me.user.id;
    const hasDeliveryDetails = Boolean(deal.buyer_game_id && deal.buyer_server && deal.preferred_delivery_time && deal.delivery_timezone);
    if (isSeller && hasDeliveryDetails && ["paid", "seller_contacted"].includes(deal.status)) {
      const transfer = document.createElement("button");
      transfer.className = "deal-confirm";
      transfer.dataset.dealAction = "transfer";
      transfer.textContent = "✅ Машина передана";
      elements.dealControls.append(transfer);
    }
    if (isBuyer && deal.status === "transfer_in_progress") {
      const warning = document.createElement("p");
      warning.textContent = "Подтверждайте получение только после того, как действительно получили машину.";
      const timer = document.createElement("p");
      timer.className = "deal-timer";
      const confirm = document.createElement("button");
      confirm.className = "deal-confirm";
      confirm.dataset.dealAction = "confirm";
      confirm.textContent = "✅ Да, машина у меня";
      confirm.hidden = true;
      const availableAt = new Date(deal.transfer_started_at).getTime() + 60 * 1000;
      const updateTimer = () => {
        const remainingSeconds = Math.max(0, Math.ceil((availableAt - Date.now()) / 1000));
        if (remainingSeconds > 0) {
          timer.textContent = `Подтвердить получение можно через ${remainingSeconds} сек.`;
          confirm.hidden = true;
          return;
        }
        timer.textContent = "Теперь можно подтвердить получение машины.";
        confirm.hidden = false;
        window.clearInterval(state.dealTimerId);
        state.dealTimerId = null;
      };
      updateTimer();
      state.dealTimerId = window.setInterval(updateTimer, 1000);
      const support = document.createElement("button");
      support.className = "deal-support";
      support.dataset.dealAction = "support";
      support.textContent = "Написать в поддержку";
      elements.dealControls.append(warning, timer, confirm, support);
    }
    if (["paid", "seller_contacted"].includes(deal.status)) {
      const cancel = document.createElement("button"); cancel.className = "deal-secondary"; cancel.dataset.dealAction = "cancel"; cancel.textContent = "Отменить сделку"; elements.dealControls.append(cancel);
    }
  }

  async function runDealAction(action) {
    const id = state.currentConversation?.deal?.id;
    if (!id) return;
    if (action === "support") return openDealSupport(id);
    const endpoint = action === "seller-contacted" ? "seller-contacted" : action === "transfer" ? "transfer" : action === "confirm" ? "confirm" : action === "cancel" ? "cancel" : "dispute";
    try { await api.request(`/deals/${id}/${endpoint}`, { method: "POST" }); await openConversation(state.currentConversation.id); await refreshMarketplace(); }
    catch (error) { notify(error.message); }
  }

  function openDealSupport(dealId) {
    const form = elements.supportForm;
    const details = state.currentConversation;
    const deal = details?.deal;
    const isBuyer = deal?.buyer_id === state.me?.user.id;
    const currentName = [state.me?.user.first_name, state.me?.user.last_name].filter(Boolean).join(" ") || "Вы";
    const otherName = details?.counterparty?.name || (details?.counterparty?.username ? `@${details.counterparty.username}` : "Пользователь Telegram");
    form.reset();
    form.elements.deal_id.value = dealId;
    form.elements.topic.value = "deal";
    form.elements.topic.closest("label").hidden = true;
    form.elements.screenshot.required = true;
    document.getElementById("supportScreenshotLabel").textContent = "Скриншот (обязательно, не более одного)";
    const context = document.getElementById("supportDealContext");
    context.hidden = false;
    context.textContent = [
      `Обращение по сделке #${dealId.slice(0, 8)}`,
      `Автомобиль: ${listingTitle(details?.listing)}`,
      `Продавец: ${isBuyer ? otherName : currentName}`,
      `Покупатель: ${isBuyer ? currentName : otherName}`,
      "Деньги останутся под защитой до решения.",
    ].join("\n");
    openSecondary("support");
    window.setTimeout(() => form.elements.message.focus({ preventScroll: true }), 50);
  }

  async function sendChatMessage(event) {
    event.preventDefault();
    const input = document.getElementById("chatInput");
    if (!state.currentConversation || !input.value.trim()) return;
    const button = event.currentTarget.querySelector("button[type=submit]");
    if (button.disabled) return;
    const body = input.value.trim();
    const clientMessageId = createRequestId();
    button.disabled = true;
    try {
      const endpoint = state.currentConversation.id
        ? `/conversations/${state.currentConversation.id}/messages`
        : `/conversations/listing/${state.currentConversation.listing.id}/messages`;
      const dealId = state.currentConversation?.deal?.id || null;
      const message = await api.request(endpoint, {
        method: "POST",
        body: JSON.stringify({ body, client_message_id: clientMessageId, deal_id: dealId }),
      });
      input.value = "";
      resizeChatInput();
      if (message.deal_id) await openDealConversation(message.deal_id);
      else await openConversation(message.conversation_id);
    } catch (error) { input.value = body; resizeChatInput(); notify(`Сообщение не отправлено: ${error.message}`); }
    finally { button.disabled = false; }
  }

  function resizeChatInput() {
    const input = document.getElementById("chatInput");
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 112)}px`;
  }

  function installChatViewport() {
    updateChatViewport();
    window.visualViewport?.addEventListener("resize", updateChatViewport);
    window.visualViewport?.addEventListener("scroll", updateChatViewport);
    window.addEventListener("orientationchange", updateChatViewport);
  }

  function updateChatViewport() {
    const viewport = window.visualViewport;
    const visualHeight = Number(viewport?.height);
    const telegramHeight = Number(telegram?.viewportHeight);
    const fullHeight = Math.max(window.innerHeight, telegramHeight || 0, visualHeight || 0);
    const activeField = document.activeElement;
    const chatFieldFocused = Boolean(
      activeField?.closest?.(".chat-view")
      && ["INPUT", "TEXTAREA", "SELECT"].includes(activeField.tagName)
    );
    const keyboardOpen = chatFieldFocused && visualHeight > 0 && fullHeight - visualHeight > 80;
    const height = keyboardOpen ? visualHeight : fullHeight;
    const width = Number(viewport?.width) > 0 ? Number(viewport.width) : window.innerWidth;
    document.documentElement.style.setProperty("--chat-viewport-height", `${Math.round(height)}px`);
    document.documentElement.style.setProperty("--chat-viewport-top", `${Math.round(keyboardOpen ? viewport?.offsetTop || 0 : 0)}px`);
    document.documentElement.style.setProperty("--chat-viewport-width", `${Math.round(width)}px`);
    document.documentElement.style.setProperty("--chat-viewport-left", `${Math.round(viewport?.offsetLeft || 0)}px`);
    if (document.body.classList.contains("chat-open")) requestAnimationFrame(() => {
      elements.dealMessages.scrollTop = elements.dealMessages.scrollHeight;
    });
  }

  function openChatListing() {
    const listingId = state.currentConversation?.listing?.id;
    if (!listingId) return;
    void openListingDetails(listingId);
  }

  async function createOffer(explicitAmount = null, listingId = null) {
    const value = explicitAmount ?? window.prompt("Предложите цену в AF Coins (минимум 1)", String(state.currentConversation?.listing.price_af_coins || 1));
    if (value === null || value === "") return;
    const amount = Number(value);
    if (!Number.isFinite(amount) || amount < 1) return notify("Цена предложения должна быть не меньше 1 AF");
    const conversationId = listingId ? null : state.currentConversation?.id;
    const sourceListingId = listingId || state.currentConversation?.listing?.id;
    if (!conversationId && !sourceListingId) return notify("Объявление не найдено");
    try {
      const path = conversationId ? `/conversations/${conversationId}/offers` : `/conversations/listing/${sourceListingId}/offers`;
      const offer = await api.request(path, { method: "POST", body: JSON.stringify({ amount_af_coins: amount }) });
      elements.listingPageOffer.hidden = true;
      elements.listingPageOfferButton.hidden = false;
      await openConversation(offer.conversation_id, null, listingId ? "listing-detail" : null);
      notify("Предложение отправлено продавцу");
    }
    catch (error) {
      if (Number(error.status) === 402 && error.detail?.code === "insufficient_af_coins") {
        const available = Number(error.detail.available_af_coins || 0);
        const missing = Number(error.detail.missing_af_coins || 0);
        const minimumTopup = Number(document.getElementById("topupAmount")?.min || 1);
        const topupAmount = Math.max(minimumTopup, Math.ceil(missing));
        state.purchaseFlow = { kind: "offer-topup", stage: "topup", busy: false, missing, topupAmount };
        elements.purchaseModalTitle.textContent = "Недостаточно AF Coins";
        elements.purchaseModalText.textContent = `На балансе: ${formatNumber(available)} AF. Для предложения ${formatNumber(amount)} AF не хватает ${formatNumber(missing)} AF.`;
        elements.purchaseModalAmount.replaceChildren(document.createTextNode(`${formatNumber(missing)} `), coin("af-coin--small"));
        elements.purchaseModalNote.textContent = "При создании предложения деньги не списываются. Пополнение использует существующую оплату через Telegram Stars.";
        elements.purchaseModalAction.textContent = `Пополнить ${topupAmount} AF`;
        elements.purchaseModalAction.disabled = false;
        return openDialog(elements.purchaseModal);
      }
      notify(error.message);
    }
  }

  async function runOfferAction(button) {
    try {
      if (button.dataset.offerAction === "counter") {
        const value = window.prompt("Встречная цена в AF Coins (минимум 1)", "1"); if (!value) return;
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
    state.activeTopupIntentId = null;
    renderPaymentStatus("idle");
    if (!telegram?.initData || typeof telegram.openInvoice !== "function") {
      elements.paymentResult.className = "payment-result is-error";
      elements.paymentResult.textContent = "Откройте AUTOFLOW MARKET внутри Telegram, чтобы оплатить счёт";
      return;
    }
    button.disabled = true;
    try {
      const amount = Number(document.getElementById("topupAmount").value);
      const purpose = "topup";
      const intent = await api.request("/wallet/star-payments/intent", { method: "POST", body: JSON.stringify({ amount, purpose }) });
      state.activeTopupIntentId = intent.id;
      renderPaymentStatus("invoice_open");
      const invoiceStatus = await new Promise((resolve, reject) => {
        try { telegram.openInvoice(intent.invoice_url, resolve); }
        catch (error) { reject(error); }
      });
      if (invoiceStatus === "cancelled") {
        renderPaymentStatus("cancelled");
        return;
      }
      if (invoiceStatus === "failed") {
        renderPaymentStatus("failed");
        return;
      }
      await checkStarPaymentStatus(intent.id, { automatic: true, purpose });
    } catch (error) {
      renderPaymentStatus(state.activeTopupIntentId ? "verification_error" : "request_error", state.activeTopupIntentId);
    } finally { button.disabled = false; }
  }

  async function checkStarPaymentStatus(intentId = state.activeTopupIntentId, options = {}) {
    if (!intentId) return;
    renderPaymentStatus("checking");
    try {
      let payment = null;
      const attempts = options.automatic ? 6 : 1;
      for (let attempt = 0; attempt < attempts; attempt += 1) {
        payment = await api.request(`/wallet/star-payments/intents/${intentId}`);
        if (payment.status !== "pending") break;
        if (attempt < attempts - 1) await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
      if (payment.status === "paid") {
        const alreadyConfirmed = state.confirmedTopupPayments.has(intentId);
        state.me.wallet = payment.wallet;
        if (!alreadyConfirmed) await loadOptionalData(["profile"], { allowRecovery: false });
        renderBalance();
        state.confirmedTopupPayments.add(intentId);
        renderPaymentStatus("confirmed");
        return;
      }
      if (["cancelled", "failed", "expired"].includes(payment.status)) {
        renderPaymentStatus(payment.status === "cancelled" ? "cancelled" : "failed");
        return;
      }
      renderPaymentStatus("pending", intentId);
    } catch (_error) {
      renderPaymentStatus("verification_error", intentId);
    }
  }

  async function waitForStarPayment(intentId) {
    let payment = null;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      payment = await api.request(`/wallet/star-payments/intents/${intentId}`);
      if (payment.status !== "pending") return payment;
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
    return payment;
  }

  function renderPaymentStatus(kind, intentId = state.activeTopupIntentId) {
    const content = {
      idle: ["", ""],
      invoice_open: ["", "Счёт открыт в Telegram"],
      checking: ["is-pending", "⏳ Проверяем платёж…"],
      confirmed: ["is-success", "✅ Оплата подтверждена\nAF Coins зачислены"],
      pending: ["is-pending", "⏳ Платёж подтверждается\nНе закрывайте приложение. Обычно это занимает несколько секунд."],
      verification_error: ["is-error", "⚠️ Платёж получен, но баланс пока не обновился\nНажмите «Проверить снова» или обратитесь в поддержку."],
      request_error: ["is-error", "Не удалось открыть оплату. Попробуйте ещё раз."],
      cancelled: ["is-cancelled", "Оплата не завершена"],
      failed: ["is-cancelled", "Оплата не завершена"],
    }[kind] || ["", ""];
    elements.paymentResult.className = `payment-result ${content[0]}`.trim();
    const message = document.createElement("span");
    message.textContent = content[1];
    elements.paymentResult.replaceChildren(message);
    if (["pending", "verification_error"].includes(kind) && intentId) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.dataset.paymentRetry = intentId;
      retry.textContent = "Проверить снова";
      elements.paymentResult.append(retry);
    }
  }

  async function createWithdrawal(event) {
    event.preventDefault(); const form = new FormData(elements.withdrawForm);
    try {
      await api.request("/withdrawals", { method: "POST", body: JSON.stringify({ amount: Number(form.get("amount")), payout_method: form.get("payout_method"), details: form.get("details") }) });
      elements.withdrawForm.reset(); await refreshMarketplace(); navigate("profile"); notify("Заявка создана, сумма заморожена");
    } catch (error) { notify(error.message); }
  }

  async function openTrainingProduct(id) {
    try {
      const cached = state.training.find((item) => String(item.id) === String(id));
      const product = cached?.published === false ? cached : await api.request(`/training/${id}`);
      state.selectedTraining = product;
      document.getElementById("trainingDetailCover").src = absoluteMediaUrl(product.cover_url);
      document.getElementById("trainingDetailTitle").textContent = product.title;
      document.getElementById("trainingDetailDescription").textContent = product.full_description;
      document.getElementById("trainingDetailType").textContent = trainingTypeLabel(product.product_type);
      document.getElementById("trainingDetailAvailability").textContent = trainingAvailabilityLabel(product.availability);
      document.getElementById("trainingDetailPrice").textContent = formatNumber(product.price_af_coins);
      document.getElementById("trainingDetailViews").textContent = `👁 ${Number(product.views_count || 0)} просмотров`;
      const video = document.getElementById("trainingDetailVideo"); video.hidden = !product.promo_video_url; if (product.promo_video_url) video.src = product.promo_video_url;
      const purchase = state.trainingPurchases.find((item) => String(item.product_id) === String(product.id));
      const buyButton = document.getElementById("trainingBuyButton");
      buyButton.disabled = Boolean(purchase) || product.availability !== "available" || state.me?.user.id === product.admin_id;
      buyButton.textContent = purchase ? "Уже куплено" : product.availability === "available" ? "Купить обучение" : trainingAvailabilityLabel(product.availability);
      state.previousView = "training"; await navigate("training-detail");
      if (state.me?.user.id !== product.admin_id) {
        try {
          const engagement = await api.request(`/training/${product.id}/view`, { method: "POST" });
          product.views_count = Number(engagement.views_count || 0);
          document.getElementById("trainingDetailViews").textContent = `👁 ${product.views_count} просмотров`;
        } catch (error) { reportClientError("training_view", error); }
      }
      return true;
    } catch (error) {
      if (Number(error?.status) === 404) {
        notify("Обучение недоступно");
        await navigate("training");
      } else notify(error.message);
      return false;
    }
  }

  function normalizedTrainingDeepLink(value) {
    const raw = String(value || "").trim();
    const productId = raw.startsWith("training_") ? raw.slice("training_".length) : raw;
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(productId) ? productId : null;
  }

  async function openTrainingProductDeepLink() {
    const productId = normalizedTrainingDeepLink(state.pendingTrainingDeepLink);
    if (!productId || !state.me) return;
    state.pendingTrainingDeepLink = null;
    await openTrainingProduct(productId);
  }

  async function buyTrainingProduct(productId = null) {
    const product = productId
      ? state.training.find((item) => String(item.id) === String(productId))
      : state.selectedTraining;
    if (!product) return notify("Обучение не найдено");
    if (state.trainingPurchases.some((item) => String(item.product_id) === String(product.id))) return notify("Вы уже приобрели это обучение");
    const balance = Number(state.me?.wallet?.available_balance || 0);
    state.purchaseFlow = { kind: "training", product, stage: "confirm", busy: false, intentId: null };
    elements.purchaseModalTitle.textContent = `Купить «${product.title}»?`;
    elements.purchaseModalText.textContent = `Стоимость: ${formatNumber(product.price_af_coins)} AF Coins. Ваш баланс: ${formatNumber(balance)} AF Coins.`;
    elements.purchaseModalAmount.replaceChildren(document.createTextNode(`${formatNumber(product.price_af_coins)} `), coin("af-coin--small"));
    elements.purchaseModalNote.textContent = product.product_type === "personal"
      ? "Средства будут защищены до завершения обучения администратором."
      : "После покупки бот автоматически отправит подготовленные материалы.";
    elements.purchaseModalAction.textContent = `Оплатить ${formatNumber(product.price_af_coins)} AF Coins`;
    elements.purchaseModalAction.disabled = false;
    openDialog(elements.purchaseModal);
  }

  async function executeTrainingPurchase(flow) {
    flow.busy = true; elements.purchaseModalAction.disabled = true; elements.purchaseModalAction.textContent = "Проверяем баланс…";
    try {
      const purchase = await api.request(`/training/${flow.product.id}/purchase`, { method: "POST" });
      state.me = await api.request("/me");
      await loadOptionalData(["trainingPurchases", "profile"], { allowRecovery: false });
      if (elements.purchaseModal?.open) elements.purchaseModal.close();
      state.purchaseFlow = null;
      renderBalance(); renderTraining(); renderTrainingLibrary();
      const button = document.getElementById("trainingBuyButton");
      if (state.selectedTraining && String(state.selectedTraining.id) === String(flow.product.id)) { button.disabled = true; button.textContent = "Уже куплено"; }
      notify(purchase.product_type === "automatic" ? "✅ Обучение куплено. Материалы отправляются ботом" : "✅ Заказ создан. Статус: Ожидает обучения");
    } catch (error) {
      if (Number(error.status) === 402 && error.detail?.code === "insufficient_af_coins") {
        const missing = Number(error.detail.missing_af_coins || 0);
        flow.stage = "topup"; flow.busy = false; flow.missing = missing; flow.intentId = null;
        elements.purchaseModalTitle.textContent = "Недостаточно AF Coins";
        elements.purchaseModalText.textContent = `Недостаточно ${formatNumber(missing)} AF Coins`;
        elements.purchaseModalAmount.replaceChildren(document.createTextNode(`${formatNumber(missing)} `), coin("af-coin--small"));
        elements.purchaseModalNote.textContent = "Пополните недостающие AF Coins через Telegram Stars. После серверного подтверждения покупка продолжится.";
        elements.purchaseModalAction.textContent = `Пополнить ${Math.ceil(missing)} AF Coins`;
        elements.purchaseModalAction.disabled = false;
        return;
      }
      flow.busy = false; elements.purchaseModalAction.disabled = false; elements.purchaseModalAction.textContent = "Повторить"; elements.purchaseModalText.textContent = error.message;
    }
  }

  async function payTrainingShortfall(flow) {
    if (!telegram?.initData || typeof telegram.openInvoice !== "function") {
      elements.purchaseModalNote.textContent = "Откройте AUTOFLOW MARKET внутри Telegram, чтобы пополнить баланс.";
      return;
    }
    flow.busy = true; elements.purchaseModalAction.disabled = true;
    try {
      if (!flow.intentId) {
        elements.purchaseModalAction.textContent = "Создаём счёт…";
        const amount = Math.ceil(flow.missing);
        const intent = await api.request("/wallet/star-payments/intent", { method: "POST", body: JSON.stringify({ amount, purpose: "training_topup", training_product_id: flow.product.id }) });
        flow.intentId = intent.id;
        const invoiceStatus = await new Promise((resolve, reject) => {
          try { telegram.openInvoice(intent.invoice_url, resolve); }
          catch (error) { reject(error); }
        });
        if (["cancelled", "failed"].includes(invoiceStatus)) {
          flow.busy = false; flow.intentId = null; elements.purchaseModalAction.disabled = false;
          elements.purchaseModalAction.textContent = `Пополнить ${amount} AF Coins`;
          elements.purchaseModalNote.textContent = "Оплата не завершена. Баланс не изменён.";
          return;
        }
      }
      elements.purchaseModalTitle.textContent = "⏳ Платёж подтверждается";
      elements.purchaseModalText.textContent = "Не закрывайте приложение. Обычно это занимает несколько секунд.";
      elements.purchaseModalAction.textContent = "Проверяем…";
      const payment = await waitForStarPayment(flow.intentId);
      if (["cancelled", "failed", "expired"].includes(payment?.status)) {
        flow.busy = false; flow.intentId = null; elements.purchaseModalAction.disabled = false;
        elements.purchaseModalTitle.textContent = "Оплата не завершена";
        elements.purchaseModalAction.textContent = `Пополнить ${Math.ceil(flow.missing)} AF Coins`;
        elements.purchaseModalNote.textContent = "Баланс не изменён. Можно открыть новый счёт.";
        return;
      }
      if (payment?.status !== "paid") {
        flow.busy = false; elements.purchaseModalAction.disabled = false; elements.purchaseModalAction.textContent = "Проверить снова";
        elements.purchaseModalNote.textContent = "Баланс изменится только после подтверждения backend.";
        return;
      }
      state.me.wallet = payment.wallet; renderBalance(); flow.intentId = null; flow.stage = "confirm"; flow.busy = false;
      elements.purchaseModalTitle.textContent = "✅ AF Coins зачислены";
      elements.purchaseModalText.textContent = "Баланс подтверждён сервером. Завершаем покупку обучения…";
      return executeTrainingPurchase(flow);
    } catch (error) {
      flow.busy = false; elements.purchaseModalAction.disabled = false; elements.purchaseModalAction.textContent = "Проверить снова";
      elements.purchaseModalNote.textContent = "Платёж получен, но баланс пока не обновился. Проверьте снова.";
    }
  }

  async function redeliverTrainingMaterials(button) {
    if (button.disabled) return;
    button.disabled = true; button.textContent = "Запрашиваем…";
    try {
      const purchase = await api.request(`/training/purchases/${button.dataset.trainingRedeliver}/redeliver`, { method: "POST" });
      state.trainingPurchases = state.trainingPurchases.map((item) => item.id === purchase.id ? purchase : item);
      renderTrainingLibrary();
      notify("Материалы отправляются в чат с ботом");
    } catch (error) {
      button.disabled = false; button.textContent = "Получить материалы повторно"; notify(error.message);
    }
  }

  function openTrainingEditor(id = null) {
    if (state.me?.user.role !== "admin") return notify("Требуется роль администратора");
    const form = document.getElementById("trainingForm"); form.reset();
    state.trainingUploadCache.clear(); state.trainingUploadRows.clear(); state.pendingTrainingCoverUrl = null; state.pendingTrainingRequestId = null;
    elements.trainingUploadStatus?.replaceChildren();
    if (state.trainingCoverObjectUrl) URL.revokeObjectURL(state.trainingCoverObjectUrl);
    state.trainingCoverObjectUrl = null;
    const product = id ? [...state.training, ...state.adminTraining].find((item) => String(item.id) === String(id)) : null;
    form.elements.product_id.value = product?.id || "";
    document.getElementById("trainingEditorTitle").textContent = product ? "Изменить обучение" : "Создать обучение";
    if (product) {
      for (const field of ["title", "short_description", "full_description", "product_type", "availability", "price_af_coins", "promo_video_url"]) form.elements[field].value = product[field] ?? "";
      form.elements.published.checked = product.published; form.elements.pinned.checked = product.pinned;
      showTrainingCoverPreview(absoluteMediaUrl(product.cover_url));
    } else if (elements.trainingCoverPreview) {
      elements.trainingCoverPreview.hidden = true;
    }
    toggleAutomaticMaterialFields();
    openSecondary("training-editor");
  }

  function toggleAutomaticMaterialFields() {
    const form = document.getElementById("trainingForm");
    const fields = document.getElementById("automaticMaterialFields");
    if (form && fields) fields.hidden = form.elements.product_type.value !== "automatic";
  }

  function ensureTrainingVideoInput(formElement) {
    if (!formElement) return null;
    const existing = formElement.elements.automatic_video;
    if (existing) return existing;
    const fieldset = document.getElementById("automaticMaterialFields");
    const genericInput = formElement.elements.automatic_material;
    if (!fieldset || !genericInput) return null;
    const label = document.createElement("label");
    label.append(document.createTextNode("Добавить видео"));
    const input = document.createElement("input");
    input.name = "automatic_video";
    input.type = "file";
    input.multiple = true;
    input.accept = "video/*,video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm";
    label.append(input);
    fieldset.insertBefore(label, genericInput.closest("label"));
    return input;
  }

  function ensureTrainingTelegramUploadUi() {
    const fieldset = document.getElementById("automaticMaterialFields");
    if (!fieldset || document.getElementById("trainingTelegramUpload")) return;
    const help = fieldset.querySelector(".training-file-help");
    if (help) help.textContent = "Видео MP4, MOV или WebM — до 2 ГБ через Telegram, без ограничения длительности. Фото — до 10 МБ; остальные файлы — до 50 МБ.";
    const panel = document.createElement("div"); panel.id = "trainingTelegramUpload"; panel.className = "training-telegram-upload";
    const title = document.createElement("strong"); title.textContent = "Большое видео загружается через Telegram";
    const copy = document.createElement("small"); copy.textContent = "Выберите видео здесь, отправьте этот же файл боту один раз и вернитесь в Mini App.";
    const actions = document.createElement("div");
    const open = document.createElement("button"); open.type = "button"; open.id = "trainingOpenUploadBot"; open.textContent = "Отправить видео боту";
    const refresh = document.createElement("button"); refresh.type = "button"; refresh.id = "trainingRefreshUploads"; refresh.textContent = "Проверить загрузку";
    actions.append(open, refresh);
    const uploads = document.createElement("div"); uploads.id = "trainingInboxUploads";
    panel.append(title, copy, actions, uploads);
    fieldset.insertBefore(panel, document.getElementById("trainingUploadStatus"));
    elements.trainingOpenUploadBot = open; elements.trainingRefreshUploads = refresh; elements.trainingInboxUploads = uploads;
  }

  async function openTrainingUploadBot() {
    try {
      const result = await api.request("/admin/training/uploads/bot-link");
      automaticMaterialFiles(document.getElementById("trainingForm")).filter(isTrainingVideoFile)
        .forEach((file) => setTrainingUploadStatus(file, "Загрузка видео...", "indeterminate", "uploading"));
      if (telegram?.openTelegramLink) telegram.openTelegramLink(result.url);
      else window.open(result.url, "_blank", "noopener");
    } catch (error) { notify(error.message); }
  }

  async function refreshTrainingInboxUploads() {
    if (elements.trainingRefreshUploads) { elements.trainingRefreshUploads.disabled = true; elements.trainingRefreshUploads.textContent = "Проверяем…"; }
    try {
      state.trainingInboxUploads = await api.request("/admin/training/uploads");
      renderTrainingInboxUploads();
      const form = document.getElementById("trainingForm");
      const videos = automaticMaterialFiles(form).filter(isTrainingVideoFile);
      videos.forEach((file) => {
        const match = state.trainingInboxUploads.find((item) => item.file_size === file.size && (!item.file_name || item.file_name === file.name));
        if (match) {
          state.trainingUploadCache.set(trainingFileKey(file), { upload: { ...match, inbox_upload_id: match.id }, savedProductId: null });
          setTrainingUploadStatus(file, "✅ Видео загружено", 100, "success");
        }
      });
      if (!state.trainingInboxUploads.length) notify("Видео ещё не получено. Дождитесь сообщения бота и проверьте снова.");
    } catch (error) { notify(error.message); }
    finally { if (elements.trainingRefreshUploads) { elements.trainingRefreshUploads.disabled = false; elements.trainingRefreshUploads.textContent = "Проверить загрузку"; } }
  }

  function renderTrainingInboxUploads() {
    if (!elements.trainingInboxUploads) return;
    if (!state.trainingInboxUploads.length) { elements.trainingInboxUploads.replaceChildren(); return; }
    elements.trainingInboxUploads.replaceChildren(...state.trainingInboxUploads.map((upload) => {
      const row = document.createElement("button"); row.type = "button"; row.className = "training-inbox-upload"; row.dataset.trainingInboxUpload = upload.id;
      const name = document.createElement("strong"); name.textContent = upload.file_name;
      const meta = document.createElement("small"); meta.textContent = [formatFileSize(upload.file_size), upload.duration_seconds ? `${Math.floor(upload.duration_seconds / 60)} мин` : null].filter(Boolean).join(" · ");
      const action = document.createElement("span"); action.textContent = "Использовать";
      row.append(name, meta, action); return row;
    }));
  }

  function selectTrainingInboxUpload(uploadId) {
    const upload = state.trainingInboxUploads.find((item) => String(item.id) === String(uploadId));
    if (!upload) return;
    state.selectedTrainingInboxUpload = upload;
    const videos = automaticMaterialFiles(document.getElementById("trainingForm")).filter(isTrainingVideoFile);
    const target = videos.find((file) => file.size === upload.file_size) || videos[0];
    if (target) {
      state.trainingUploadCache.set(trainingFileKey(target), { upload: { ...upload, inbox_upload_id: upload.id }, savedProductId: null });
      setTrainingUploadStatus(target, "✅ Видео загружено", 100, "success");
    }
    notify(`Выбрано: ${upload.file_name}`);
  }

  function isTrainingVideoFile(file) {
    return String(file?.type || "").toLowerCase().startsWith("video/")
      || /\.(mp4|mov|webm)$/i.test(String(file?.name || ""));
  }

  function automaticMaterialFiles(formElement) {
    const files = [
      ...(formElement.elements.automatic_video?.files || []),
      ...(formElement.elements.automatic_material?.files || []),
    ];
    return [...new Map(files.map((file) => [trainingFileKey(file), file])).values()];
  }

  function hasAutomaticMaterialInput(formElement) {
    if (formElement.elements.product_type.value !== "automatic") return false;
    return Boolean(
      String(formElement.elements.automatic_text?.value || "").trim()
      || automaticMaterialFiles(formElement).length
      || state.selectedTrainingInboxUpload
    );
  }

  function trainingFileKey(file) {
    return [file.name, file.size, file.type, file.lastModified].join(":");
  }

  function setTrainingUploadStatus(file, message, percent = null, stateName = "") {
    if (!elements.trainingUploadStatus) return;
    const key = trainingFileKey(file);
    let row = state.trainingUploadRows.get(key);
    if (!row) {
      row = document.createElement("div"); row.className = "training-upload-row";
      const title = document.createElement("strong"); title.textContent = file.name || "Материал";
      const size = document.createElement("small"); size.textContent = formatFileSize(file.size);
      const status = document.createElement("span");
      const progress = document.createElement("progress"); progress.max = 100; progress.value = 0; progress.hidden = true;
      row.append(title, size, status, progress); elements.trainingUploadStatus.append(row);
      state.trainingUploadRows.set(key, row);
    }
    row.className = `training-upload-row${stateName ? ` is-${stateName}` : ""}`;
    row.querySelector("span").textContent = message;
    const progress = row.querySelector("progress"); progress.hidden = percent === null;
    if (typeof percent === "number") progress.value = percent;
    else if (percent === "indeterminate") progress.removeAttribute("value");
  }

  function previewTrainingMaterials(event) {
    state.trainingUploadCache.clear(); state.trainingUploadRows.clear(); state.selectedTrainingInboxUpload = null; elements.trainingUploadStatus?.replaceChildren();
    const formElement = event.currentTarget.form || document.getElementById("trainingForm");
    automaticMaterialFiles(formElement).forEach((file) => setTrainingUploadStatus(file, isTrainingVideoFile(file) ? "Видео выбрано — отправьте его боту" : "Файл выбран", null, "selected"));
  }

  function showTrainingCoverPreview(url) {
    if (!elements.trainingCoverPreview || !elements.trainingCoverPreviewImage || !url) return;
    elements.trainingCoverPreviewImage.src = url; elements.trainingCoverPreview.hidden = false;
  }

  function previewTrainingCover(event) {
    const file = event.currentTarget.files?.[0];
    state.pendingTrainingCoverUrl = null;
    if (state.trainingCoverObjectUrl) URL.revokeObjectURL(state.trainingCoverObjectUrl);
    state.trainingCoverObjectUrl = file ? URL.createObjectURL(file) : null;
    if (state.trainingCoverObjectUrl) showTrainingCoverPreview(state.trainingCoverObjectUrl);
    else if (elements.trainingCoverPreview) elements.trainingCoverPreview.hidden = true;
  }

  async function saveInitialAutomaticMaterials(productId, formElement, startPosition = 0) {
    if (formElement.elements.product_type.value !== "automatic") return { savedCount: 0, failures: [] };
    let position = startPosition;
    let savedCount = 0;
    const failures = [];
    const persist = async (label, material) => {
      try {
        await api.request(`/admin/training/${productId}/materials`, { method: "POST", body: JSON.stringify({ ...material, position }) });
        position += 1;
        savedCount += 1;
      } catch (error) {
        failures.push(`${label}: ${error.message}`);
        reportClientError("training_material_save", error);
      }
    };
    const textReference = String(formElement.elements.automatic_text?.value || "").trim();
    if (textReference) {
      await persist("Инструкция", { title: "Инструкция", material_type: "text", delivery_reference: textReference });
      if (!failures.length) formElement.elements.automatic_text.value = "";
    }
    const files = automaticMaterialFiles(formElement);
    if (state.selectedTrainingInboxUpload && !files.some(isTrainingVideoFile)) {
      const upload = state.selectedTrainingInboxUpload;
      try {
        await api.request(`/admin/training/${productId}/materials/from-upload/${upload.id}`, { method: "POST", body: JSON.stringify({ title: upload.file_name || "Видео", position }) });
        position += 1; savedCount += 1;
      } catch (error) {
        failures.push(`${upload.file_name || "Видео"}: ${error.message}`);
        reportClientError("training_video_attach", error);
      }
    }
    for (const file of files) {
      const key = trainingFileKey(file);
      const video = isTrainingVideoFile(file);
      const cached = state.trainingUploadCache.get(key);
      if (cached?.savedProductId === String(productId)) continue;
      try {
        let upload = cached?.upload;
        if (video && !upload && state.selectedTrainingInboxUpload && files.filter(isTrainingVideoFile).length === 1) {
          upload = { ...state.selectedTrainingInboxUpload, inbox_upload_id: state.selectedTrainingInboxUpload.id };
        }
        if (!upload) {
          if (video) throw new Error("Отправьте видео боту и нажмите «Проверить загрузку»");
          setTrainingUploadStatus(file, video ? "Загрузка видео — 0%" : "Загрузка файла — 0%", 0, "uploading");
          upload = await api.upload(file, "/admin/training/materials/upload?material_type=file", {
            kind: "training", prepareImage: false, maxBytes: 50 * 1024 * 1024, timeoutMs: 295000,
            onProgress: (percent) => setTrainingUploadStatus(file, `${video ? "Загрузка видео" : "Загрузка файла"} — ${percent}%`, percent, "uploading"),
          });
          state.trainingUploadCache.set(key, { upload, savedProductId: null });
          setTrainingUploadStatus(file, `${video ? "✅ Видео загружено" : "✅ Файл загружен"}. Сохраняем материал…`, 100, "uploaded");
        }
        const beforeFailures = failures.length;
        if (video && upload.inbox_upload_id) {
          try {
            await api.request(`/admin/training/${productId}/materials/from-upload/${upload.inbox_upload_id}`, { method: "POST", body: JSON.stringify({ title: file.name || upload.file_name || "Видео", position }) });
            position += 1; savedCount += 1;
          } catch (error) { failures.push(`${file.name || "Видео"}: ${error.message}`); reportClientError("training_video_attach", error); }
        } else {
          await persist(file.name || "Материал", {
            title: file.name || "Материал",
            material_type: upload.material_type || "document",
            delivery_reference: upload.delivery_reference,
            mime_type: upload.mime_type || null,
            file_size: upload.file_size || null,
            metadata_json: upload.metadata_json || {},
          });
        }
        if (failures.length === beforeFailures) {
          state.trainingUploadCache.set(key, { upload, savedProductId: String(productId) });
          setTrainingUploadStatus(file, video ? "✅ Видео загружено" : "✅ Материал сохранён", 100, "success");
        } else setTrainingUploadStatus(file, "Файл загружен, но материал не сохранён. Повторите.", 100, "error");
      } catch (error) {
        failures.push(`${file.name || "Материал"}: ${error.message}`);
        setTrainingUploadStatus(file, video ? "Не удалось загрузить видео. Попробуйте ещё раз." : error.message, null, "error");
        reportClientError("training_material_upload", error);
      }
    }
    return { savedCount, failures };
  }

  async function submitTrainingProduct(event) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const button = formElement.querySelector("button[type=submit]"); if (button.disabled) return; const defaultButtonText = "Сохранить обучение"; button.disabled = true; button.textContent = "Сохраняем обучение…";
    let retryNeeded = false;
    try {
      const id = form.get("product_id"); const wasExisting = Boolean(id); const existing = id ? [...state.training, ...state.adminTraining].find((item) => String(item.id) === String(id)) : null;
      if (state.pendingTrainingPublish && String(state.pendingTrainingPublish.productId) === String(id)) {
        button.textContent = "Повторяем публикацию…";
        const finalized = await finalizeTrainingPublish(id, state.pendingTrainingPublish.materialCount);
        state.pendingTrainingPublish = null;
        const upsertFinalized = (items) => [finalized, ...items.filter((item) => item.id !== finalized.id)];
        state.training = upsertFinalized(state.training);
        state.adminTraining = [{ purchase_count: 0, revenue_af_coins: 0, archived: false, ...existing, ...finalized }, ...state.adminTraining.filter((item) => item.id !== finalized.id)];
        resetTrainingEditor(formElement);
        renderTraining(); renderAdminTraining(); await navigate("admin"); switchAdminTab("training");
        notify("✅ Обучение опубликовано");
        return;
      }
      let coverUrl = state.pendingTrainingCoverUrl || existing?.cover_url || null; const cover = form.get("cover");
      if (cover?.size && !state.pendingTrainingCoverUrl) {
        button.textContent = "Загружаем обложку…";
        state.pendingTrainingCoverUrl = (await api.upload(cover)).url;
        coverUrl = state.pendingTrainingCoverUrl;
      }
      if (!coverUrl) throw new Error("Добавьте одну основную обложку");
      const automatic = form.get("product_type") === "automatic";
      const wantsPublished = form.get("published") === "on";
      let existingMaterials = [];
      if (automatic && id) existingMaterials = await api.request(`/admin/training/${id}/materials`);
      if (automatic && wantsPublished && !existingMaterials.length && !hasAutomaticMaterialInput(formElement)) {
        throw new Error("Для публикации автовыдачи добавьте хотя бы один материал");
      }
      const publishAfterMaterials = automatic && wantsPublished && !existing?.published;
      if (!id && !state.pendingTrainingRequestId) state.pendingTrainingRequestId = createRequestId();
      const payload = { client_request_id: id ? undefined : state.pendingTrainingRequestId, title: form.get("title"), short_description: form.get("short_description"), full_description: form.get("full_description"), cover_url: coverUrl, promo_video_url: form.get("promo_video_url") || null, product_type: form.get("product_type"), availability: form.get("availability"), price_af_coins: Number(form.get("price_af_coins")), published: publishAfterMaterials ? false : wantsPublished, pinned: form.get("pinned") === "on" };
      button.textContent = wasExisting ? "Сохраняем изменения…" : "Создаём обучение…";
      let saved = await api.request(id ? `/admin/training/${id}` : "/admin/training", { method: id ? "PATCH" : "POST", body: JSON.stringify(payload) });
      formElement.elements.product_id.value = saved.id;
      const upsert = (items) => [saved, ...items.filter((item) => item.id !== saved.id)];
      state.training = saved.published ? upsert(state.training) : state.training.filter((item) => item.id !== saved.id);
      const previousAdmin = state.adminTraining.find((item) => item.id === saved.id);
      state.adminTraining = [{ purchase_count: 0, revenue_af_coins: 0, archived: false, ...previousAdmin, ...saved }, ...state.adminTraining.filter((item) => item.id !== saved.id)];
      button.textContent = "Сохраняем материалы…";
      const materialResult = await saveInitialAutomaticMaterials(saved.id, formElement, existingMaterials.length);
      const materialCount = existingMaterials.length + materialResult.savedCount;
      if (publishAfterMaterials && materialCount && !materialResult.failures.length) {
        try {
          button.textContent = "Публикуем обучение…";
          saved = await finalizeTrainingPublish(saved.id, materialCount);
          state.pendingTrainingPublish = null;
        } catch (error) {
          state.pendingTrainingPublish = { productId: saved.id, materialCount };
          const code = reportClientError("training_publish_after_materials", error);
          const businessMessage = Number(error.status) > 0 && error.message && !/ошибка запроса|request failed/i.test(error.message) ? error.message : `Не удалось опубликовать обучение. Код: ${code}`;
          materialResult.failures.push(businessMessage);
        }
      } else if (publishAfterMaterials && !materialResult.savedCount) {
        materialResult.failures.push("Обучение оставлено скрытым: ни один материал не был сохранён");
      }
      state.training = saved.published ? upsert(state.training) : state.training.filter((item) => item.id !== saved.id);
      const savedAdmin = { purchase_count: 0, revenue_af_coins: 0, archived: false, ...previousAdmin, ...saved };
      state.adminTraining = [savedAdmin, ...state.adminTraining.filter((item) => item.id !== saved.id)];
      if (materialResult.failures.length) {
        retryNeeded = true;
        renderTraining(); renderAdminTraining();
        notify(`Обучение сохранено как черновик. ${materialResult.failures[0]}`);
        return;
      }
      try {
        await loadAdminTraining(state.adminTrainingFilter);
      } catch (refreshError) {
        reportClientError("training_refresh_after_save", refreshError);
      }
      resetTrainingEditor(formElement); renderTraining(); renderAdminTraining(); await navigate("admin"); switchAdminTab("training");
      notify(saved.published ? "✅ Обучение опубликовано" : wasExisting ? "✅ Обучение успешно изменено" : "✅ Обучение успешно создано");
    } catch (error) {
      retryNeeded = true;
      if (state.pendingTrainingPublish) {
        const code = reportClientError("training_publish_after_materials", error);
        notify(Number(error.status) > 0 && error.message && !/ошибка запроса|request failed/i.test(error.message) ? error.message : `Не удалось опубликовать обучение. Код: ${code}`);
      } else notify(error.message);
    } finally { button.disabled = false; button.textContent = state.pendingTrainingPublish ? "Повторить публикацию" : retryNeeded ? "Повторить загрузку" : defaultButtonText; }
  }

  async function finalizeTrainingPublish(productId, materialCount) {
    try {
      return await api.request(`/admin/training/${productId}/state/publish`, { method: "POST", timeoutMs: 20000, retries: 0 });
    } catch (error) {
      error.trainingId = String(productId);
      error.materialCount = Number(materialCount || 0);
      throw error;
    }
  }

  function resetTrainingEditor(formElement) {
    formElement.reset(); state.trainingUploadCache.clear(); state.trainingUploadRows.clear(); state.trainingInboxUploads = []; state.selectedTrainingInboxUpload = null; state.pendingTrainingPublish = null; state.pendingTrainingCoverUrl = null; state.pendingTrainingRequestId = null; elements.trainingUploadStatus?.replaceChildren(); elements.trainingInboxUploads?.replaceChildren(); toggleAutomaticMaterialFields();
  }

  async function deleteTrainingProduct(id) {
    if (!(await confirmAction("Удалить это обучение? Купленные заказы и финансовая история сохранятся."))) return;
    try {
      await api.request(`/admin/training/${id}`, { method: "DELETE" });
      state.training = state.training.filter((item) => String(item.id) !== String(id));
      state.adminTraining = state.adminTraining.filter((item) => String(item.id) !== String(id));
      if (String(state.selectedAdminTrainingId || "") === String(id)) {
        state.selectedAdminTrainingId = null;
        elements.adminTrainingDetail.hidden = true;
      }
      renderTraining(); renderAdminTraining();
      try { await loadAdminTraining(state.adminTrainingFilter); }
      catch (refreshError) { reportClientError("training_refresh_after_delete", refreshError); }
      notify("Обучение удалено");
    }
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
      const dealId = String(data.get("deal_id") || "").trim();
      if (dealId) {
        const screenshot = data.get("screenshot");
        if (!screenshot?.size) {
          throw new Error("Прикрепите хотя бы один скриншот, чтобы мы могли разобраться в ситуации.");
        }
        const screenshotUrl = (await api.upload(screenshot)).url;
        await api.request(`/deals/${dealId}/support`, {
          method: "POST",
          body: JSON.stringify({
            message: data.get("message"),
            screenshot_url: screenshotUrl,
            client_request_id: createRequestId(),
          }),
        });
      } else {
        const screenshot = data.get("screenshot");
        let screenshotUrl = null;
        if (screenshot?.size) screenshotUrl = (await api.upload(screenshot)).url;
        await api.request("/support/tickets", {
          method: "POST",
          body: JSON.stringify({ topic: data.get("topic"), message: data.get("message"), screenshot_url: screenshotUrl }),
        });
      }
      formElement.reset();
      formElement.elements.topic.closest("label").hidden = false;
      formElement.elements.screenshot.required = false;
      document.getElementById("supportScreenshotLabel").textContent = "Скриншот, не более одного";
      document.getElementById("supportDealContext").hidden = true;
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
    const title = document.createElement("strong"); title.textContent = ticket.case_type === "deal" ? `${ticket.listing_title || "Сделка"} · #${ticket.deal_id.slice(0, 8)}` : ticket.topic;
    const status = document.createElement("small"); status.textContent = supportStatusLabel(ticket.status);
    head.append(title, status); card.append(head);
    if (adminMode && ticket.conversation_messages?.length) {
      const history = document.createElement("details"); history.className = "support-conversation-history";
      const summary = document.createElement("summary"); summary.textContent = `История buyer/seller · ${ticket.conversation_messages.length}`; history.append(summary);
      ticket.conversation_messages.forEach((item) => { const row = document.createElement("div"); const role = item.sender_id === ticket.buyer_id ? "Покупатель" : item.sender_id === ticket.seller_id ? "Продавец" : "Участник"; row.textContent = `${role}: ${item.body}`; history.append(row); });
      card.append(history);
    }
    ticket.messages.forEach((item) => {
      const message = document.createElement("div");
      const isAdminMessage = adminMode ? item.sender_id === state.me?.user.id : ![ticket.buyer_id, ticket.seller_id, ticket.author_id].includes(item.sender_id);
      message.className = `support-message${isAdminMessage ? " is-admin" : ""}`;
      message.textContent = `${isAdminMessage ? "🛡 AutoFlow Support\n" : ""}${item.body}`;
      card.append(message);
    });
    const actions = document.createElement("div"); actions.className = "support-ticket__actions";
    if (ticket.status !== "closed") {
      const reply = document.createElement("button"); reply.type = "button"; reply.dataset.supportReply = ticket.id; reply.dataset.adminReply = String(adminMode); reply.textContent = "Ответить"; actions.append(reply);
    }
    if (adminMode) {
      if (ticket.case_type === "deal" && !["resolved", "closed"].includes(ticket.status)) {
        [["complete", "Передать средства продавцу"], ["refund", "Вернуть средства покупателю"]].forEach(([outcome, label]) => { const button = document.createElement("button"); button.type = "button"; button.dataset.supportResolution = outcome; button.dataset.ticketId = ticket.id; button.textContent = label; actions.append(button); });
      } else {
        ["resolved", "closed"].forEach((nextStatus) => { const button = document.createElement("button"); button.type = "button"; button.dataset.supportStatus = nextStatus; button.dataset.ticketId = ticket.id; button.textContent = nextStatus === "resolved" ? "Решено" : "Закрыть"; actions.append(button); });
      }
    }
    card.append(actions);
    return card;
  }

  async function replySupportTicket(ticketId, adminMode) {
    const message = window.prompt("Введите ответ");
    if (!message?.trim()) return;
    const path = adminMode ? `/admin/support/tickets/${ticketId}/messages` : `/support/tickets/${ticketId}/messages`;
    try {
      await api.request(path, { method: "POST", body: JSON.stringify({ message: message.trim(), client_request_id: createRequestId() }) });
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

  async function loadAdminSupport(filter = state.adminSupportFilter) {
    state.adminSupportFilter = filter;
    let filters = document.getElementById("adminSupportFilters");
    if (!filters) {
      filters = document.createElement("div"); filters.id = "adminSupportFilters"; filters.className = "support-admin-filters";
      [["active", "Новые"], ["in_progress", "В работе"], ["resolved", "Решённые"]].forEach(([value, label]) => { const button = document.createElement("button"); button.type = "button"; button.dataset.supportFilter = value; button.textContent = label; filters.append(button); });
      elements.adminSupportTickets.before(filters);
    }
    filters.querySelectorAll("button").forEach((button) => button.classList.toggle("is-active", button.dataset.supportFilter === filter));
    const query = filter === "active" ? "?status=new" : `?status=${encodeURIComponent(filter)}`;
    const tickets = await api.request(`/admin/support/tickets${query}`);
    if (!tickets.length) { elements.adminSupportTickets.textContent = "Обращений пока нет"; return; }
    elements.adminSupportTickets.replaceChildren(...tickets.map((ticket) => createSupportTicketCard(ticket, true)));
  }

  async function resolveSupportCase(button) {
    const outcome = button.dataset.supportResolution;
    const question = outcome === "complete" ? "Передать защищённые средства продавцу и завершить сделку?" : "Вернуть защищённые средства покупателю и отменить сделку?";
    if (!(await confirmAction(question))) return;
    const reason = window.prompt("Укажите обязательную причину решения");
    if (!reason?.trim()) return;
    button.disabled = true;
    try {
      await api.request(`/admin/support/tickets/${button.dataset.ticketId}/resolve`, { method: "POST", body: JSON.stringify({ outcome, reason: reason.trim() }) });
      await Promise.all([loadAdminSupport(), loadAdminDeals()]);
      notify("Решение выполнено и записано в историю");
    } catch (error) { notify(error.message); }
    finally { button.disabled = false; }
  }

  function ensureBroadcastAdminUi() {
    if (document.getElementById("broadcastForm")) return;
    const tabs = document.querySelector(".admin-tabs");
    const container = tabs?.parentElement;
    if (!tabs || !container) return;
    const tab = document.createElement("button");
    tab.type = "button";
    tab.dataset.adminTab = "broadcasts";
    tab.textContent = "Рассылки";
    tabs.append(tab);
    const panel = document.createElement("section");
    panel.dataset.adminPanel = "broadcasts";
    panel.hidden = true;
    panel.innerHTML = `<div class="broadcast-admin">
      <h2>Рассылка пользователям</h2>
      <p>Каждое сообщение автоматически содержит кнопку «🚘 Открыть Market».</p>
      <form id="broadcastForm">
        <label>Текст сообщения<textarea name="text" rows="5" maxlength="4096" placeholder="Введите текст или caption"></textarea></label>
        <label>Фотография (необязательно)<input name="photo" type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif"></label>
        <button class="publish-button" type="submit">Запустить рассылку</button>
      </form>
      <div class="broadcast-launch-status" id="broadcastLaunchStatus" role="status" aria-live="polite"></div>
      <h3>Последние рассылки</h3>
      <div class="broadcast-list" id="adminBroadcasts"></div>
    </div>`;
    container.append(panel);
  }

  async function submitAdminBroadcast(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const text = String(data.get("text") || "").trim();
    const photo = data.get("photo");
    const status = document.getElementById("broadcastLaunchStatus");
    if (!text && !photo?.size) {
      status.textContent = "Добавьте текст или фотографию";
      status.classList.add("is-error");
      return;
    }
    const button = form.querySelector("button[type=submit]");
    if (button.disabled) return;
    button.disabled = true;
    status.classList.remove("is-error");
    status.textContent = "Запускаем рассылку…";
    state.pendingBroadcastRequestId ||= createRequestId();
    try {
      const photoUrl = photo?.size ? (await api.upload(photo)).url : null;
      const broadcast = await api.request("/admin/broadcasts", {
        method: "POST",
        body: JSON.stringify({
          client_request_id: state.pendingBroadcastRequestId,
          text,
          photo_url: photoUrl,
        }),
      });
      state.pendingBroadcastRequestId = null;
      form.reset();
      status.textContent = `Рассылка запущена · #${broadcast.id.slice(0, 8)}`;
      await loadAdminBroadcasts();
    } catch (error) {
      status.classList.add("is-error");
      status.textContent = error.status === 409
        ? "Другая рассылка ещё отправляется. Дождитесь её завершения."
        : error.status === 422
          ? `❌ Не удалось запустить рассылку. ${error.message}`
          : "❌ Не удалось запустить рассылку. Проверьте соединение и попробуйте снова.";
    } finally {
      button.disabled = false;
    }
  }

  async function loadAdminBroadcasts() {
    const list = document.getElementById("adminBroadcasts");
    if (!list) return;
    state.adminBroadcasts = await api.request("/admin/broadcasts");
    renderAdminBroadcasts();
    const active = state.adminBroadcasts.some((item) => ["queued", "running"].includes(item.status));
    if (active && !state.broadcastPollingId) {
      state.broadcastPollingId = window.setInterval(() => {
        loadAdminBroadcasts().catch((error) => reportClientError("broadcast_status_poll", error));
      }, 2000);
    } else if (!active && state.broadcastPollingId) {
      window.clearInterval(state.broadcastPollingId);
      state.broadcastPollingId = null;
    }
  }

  function renderAdminBroadcasts() {
    const list = document.getElementById("adminBroadcasts");
    if (!list) return;
    if (!state.adminBroadcasts.length) {
      list.textContent = "Рассылок пока нет";
      return;
    }
    const labels = { draft: "Черновик", queued: "В очереди", running: "Отправляется…", completed: "✅ Рассылка завершена", failed: "❌ Ошибка рассылки" };
    list.replaceChildren(...state.adminBroadcasts.map((item) => {
      const card = document.createElement("article");
      card.className = `broadcast-card is-${item.status}`;
      const heading = document.createElement("strong");
      heading.textContent = `${labels[item.status] || item.status} · #${item.id.slice(0, 8)}`;
      const counters = document.createElement("p");
      counters.textContent = `Отправлено: ${item.sent_count}\nОшибок: ${item.failed_count}\nВсего: ${item.total_recipients}`;
      const content = document.createElement("small");
      content.textContent = `${item.content_type === "photo" ? "Фото + текст" : "Текст"} · ${new Date(item.created_at).toLocaleString("ru-RU")}`;
      card.append(heading, counters, content);
      if (item.status === "failed") {
        const error = document.createElement("span");
        error.textContent = "Рассылка остановлена из-за системной ошибки";
        card.append(error);
      }
      return card;
    }));
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

  async function findAdminBalanceUser(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const username = String(new FormData(form).get("username") || "").trim().replace(/^@+/, "");
    state.adminBalanceUser = null;
    elements.adminBalanceUserCard.hidden = true;
    document.getElementById("balanceAdjustmentForm").hidden = true;
    elements.adminBalanceResult.replaceChildren();
    if (!username) return setAdminBalanceLookupMessage("Введите username");
    setAdminBalanceLookupMessage("Ищем пользователя…");
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const users = await api.request(`/admin/users?q=${encodeURIComponent(username)}`);
      const found = users.find((item) => String(item.user.username || "").toLowerCase() === username.toLowerCase());
      if (!found) return setAdminBalanceLookupMessage("Пользователь не найден", true);
      state.adminBalanceUser = found;
      setAdminBalanceLookupMessage("");
      renderAdminBalanceUser(found);
    } catch (_error) {
      setAdminBalanceLookupMessage("Не удалось найти пользователя. Попробуйте снова.", true);
    } finally { button.disabled = false; }
  }

  function setAdminBalanceLookupMessage(message, isError = false) {
    elements.adminBalanceLookupMessage.textContent = message;
    elements.adminBalanceLookupMessage.classList.toggle("is-error", isError);
  }

  function renderAdminBalanceUser(item) {
    const user = item.user;
    const name = [user.first_name, user.last_name].filter(Boolean).join(" ") || "Без имени";
    const rows = [
      ["Имя", name],
      ["Username", user.username ? `@${user.username}` : "Не указан"],
      ["Telegram ID", String(user.telegram_id)],
      ["Текущий баланс", `${formatNumber(item.wallet.available_balance)} AF Coins`],
    ].map(([label, value]) => {
      const row = document.createElement("p");
      const title = document.createElement("span"); title.textContent = `${label}:`;
      const data = document.createElement("strong"); data.textContent = value;
      row.append(title, data); return row;
    });
    elements.adminBalanceUserCard.replaceChildren(...rows);
    elements.adminBalanceUserCard.hidden = false;
    document.getElementById("balanceAdjustmentForm").hidden = false;
  }

  function setAdminBalanceDirection(direction) {
    if (!["credit", "debit"].includes(direction)) return;
    state.adminBalanceDirection = direction;
    document.querySelectorAll("[data-balance-direction]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.balanceDirection === direction);
      button.setAttribute("aria-pressed", String(button.dataset.balanceDirection === direction));
    });
  }

  async function adminUserAction(button) {
    if (!(await confirmAction(`${button.textContent} пользователя?`))) return;
    try { await api.request(`/admin/users/${button.dataset.userId}/${button.dataset.adminUserAction}`, { method: "POST" }); await loadAdminUsers(); notify("Статус пользователя обновлён"); }
    catch (error) { notify(error.message); }
  }

  async function loadAdminListings() {
    const listings = await api.request("/admin/listings");
    elements.adminListings.replaceChildren(...listings.map((listing) => {
      const card = document.createElement("div"); card.className = "admin-record";
      const title = document.createElement("strong"); title.textContent = `${listingTitle(listing)} · ${listing.listing_type}`;
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
      if (deal.status === "disputed") { const note = document.createElement("small"); note.textContent = "Финансовое решение доступно в связанном обращении поддержки"; card.append(note); }
      return card;
    }));
  }

  async function loadAdminTraining(filter = "all") {
    if (state.me?.user.role !== "admin") return;
    state.adminTrainingFilter = filter;
    const [productsResult, statsResult, ordersResult] = await Promise.allSettled([
      api.request(`/admin/training/management?filter=${encodeURIComponent(filter)}`),
      api.request("/admin/training/stats"),
      api.request("/admin/training/purchases?product_type=personal"),
    ]);
    if (productsResult.status === "fulfilled") state.adminTraining = productsResult.value;
    else reportClientError("admin_training_products", productsResult.reason);
    if (statsResult.status === "fulfilled") state.adminTrainingStats = statsResult.value;
    else reportClientError("admin_training_stats", statsResult.reason);
    if (ordersResult.status === "fulfilled") state.adminTrainingOrders = ordersResult.value;
    else { state.adminTrainingOrders = []; reportClientError("admin_training_orders", ordersResult.reason); }
    document.querySelectorAll("[data-training-filter]").forEach((button) => button.classList.toggle("is-active", button.dataset.trainingFilter === filter));
    renderAdminTraining();
  }

  function renderAdminTraining() {
    const stats = state.adminTrainingStats;
    if (stats) {
      const values = [["Продажи", stats.total_sales], ["Выручка", `${formatNumber(stats.total_revenue_af_coins)} AF`], ["Персональные", stats.personal_sales], ["Автовыдача", stats.automatic_sales]];
      elements.adminTrainingStats.replaceChildren(...values.map(([label, value]) => { const node = document.createElement("div"); const strong = document.createElement("strong"); strong.textContent = value; const span = document.createElement("span"); span.textContent = label; node.append(strong, span); return node; }));
    }
    renderAdminTrainingOrders();
    if (!state.adminTraining.length) { const empty = document.createElement("div"); empty.className = "history-empty"; empty.textContent = "В этой категории обучений нет"; elements.adminTrainingProducts.replaceChildren(empty); return; }
    elements.adminTrainingProducts.replaceChildren(...state.adminTraining.map((product) => {
      const card = document.createElement("article"); card.className = "training-admin-card";
      const image = document.createElement("img"); image.src = absoluteMediaUrl(product.cover_url); image.alt = "";
      const copy = document.createElement("div"); const title = document.createElement("strong"); title.textContent = product.title;
      const meta = document.createElement("small"); meta.textContent = `${trainingTypeLabel(product.product_type)} · ${product.published_at ? `опубликовано ${formatDate(product.published_at)}` : `создано ${formatDate(product.created_at)}`}`;
      const facts = document.createElement("span"); facts.textContent = `${formatNumber(product.price_af_coins)} AF · просмотров ${Number(product.views_count || 0)} · покупок ${product.purchase_count} · доход ${formatNumber(product.revenue_af_coins)} AF`;
      const flags = document.createElement("em"); flags.textContent = [product.published && !product.archived ? "Опубликовано" : "Скрыто", product.pinned ? "Закреплено" : null].filter(Boolean).join(" · "); copy.append(title, meta, facts, flags);
      const actions = document.createElement("div"); actions.className = "admin-record__actions";
      const definitions = [
        ["edit", "Редактировать"], [product.published && !product.archived ? "hide" : "publish", product.published && !product.archived ? "Скрыть" : "Опубликовать"],
        [product.pinned ? "unpin" : "pin", product.pinned ? "Снять закрепление" : "Закрепить"], ["share", "Скопировать ссылку"], ["buyers", "Покупатели"], ["delete", "Удалить"],
      ];
      if (product.product_type === "automatic") definitions.push(["materials", "Материалы"]);
      definitions.forEach(([action, label]) => { const button = document.createElement("button"); button.type = "button"; button.dataset.trainingAdminAction = action; button.dataset.productId = product.id; button.textContent = label; actions.append(button); });
      card.append(image, copy, actions); return card;
    }));
  }

  function renderAdminTrainingOrders() {
    const filters = document.getElementById("adminTrainingFilters");
    if (!filters) return;
    let section = document.getElementById("adminTrainingOrdersSection");
    if (!section) {
      section = document.createElement("section"); section.id = "adminTrainingOrdersSection"; section.className = "training-orders";
      const heading = document.createElement("div"); heading.className = "training-orders-heading";
      const title = document.createElement("h3"); title.textContent = "Заказы персонального обучения";
      const note = document.createElement("span"); note.textContent = "Сохраняются в PostgreSQL";
      const list = document.createElement("div"); list.id = "adminTrainingOrders";
      const orderFilters = document.createElement("div"); orderFilters.className = "training-order-filters";
      [["new", "Ожидают"], ["in_progress", "В процессе"], ["completed", "Завершённые"]].forEach(([value, label]) => {
        const button = document.createElement("button"); button.type = "button"; button.dataset.trainingOrderFilter = value; button.textContent = label; orderFilters.append(button);
      });
      heading.append(title, note); section.append(heading, orderFilters, list); filters.before(section);
    }
    const list = document.getElementById("adminTrainingOrders");
    document.querySelectorAll("[data-training-order-filter]").forEach((button) => button.classList.toggle("is-active", button.dataset.trainingOrderFilter === state.adminTrainingOrderFilter));
    const orders = state.adminTrainingOrders.filter((purchase) => state.adminTrainingOrderFilter === "new" ? purchase.status === "awaiting_start" : purchase.status === state.adminTrainingOrderFilter);
    if (!orders.length) { const empty = document.createElement("div"); empty.className = "history-empty"; empty.textContent = "В этой категории заказов нет"; list.replaceChildren(empty); return; }
    list.replaceChildren(...orders.map((purchase) => {
      const card = createTrainingBuyerCard(purchase); card.dataset.trainingOrderId = purchase.id; return card;
    }));
  }

  async function runTrainingAdminAction(button) {
    const action = button.dataset.trainingAdminAction; const productId = button.dataset.productId;
    if (action === "edit") return openTrainingEditor(productId);
    if (action === "buyers") return openTrainingBuyers(productId);
    if (action === "materials") return openTrainingMaterials(productId);
    if (action === "share") return copyTrainingShareLink(productId, button);
    if (action === "delete") return deleteTrainingProduct(productId);
    button.disabled = true;
    try { await api.request(`/admin/training/${productId}/state/${action}`, { method: "POST" }); await loadAdminTraining(state.adminTrainingFilter); notify("Изменения сохранены"); }
    catch (error) { notify(error.message); }
    finally { button.disabled = false; }
  }

  async function copyTrainingShareLink(productId, button) {
    button.disabled = true;
    try {
      const result = await api.request(`/admin/training/${productId}/share-link`);
      if (window.navigator.clipboard?.writeText) await window.navigator.clipboard.writeText(result.url);
      else {
        const fallback = document.createElement("textarea");
        fallback.value = result.url; fallback.setAttribute("readonly", ""); fallback.style.position = "fixed"; fallback.style.opacity = "0";
        document.body.append(fallback); fallback.select();
        if (!document.execCommand("copy")) throw new Error("Не удалось скопировать ссылку");
        fallback.remove();
      }
      notify("Ссылка на обучение скопирована");
    } catch (error) { notify(error.message); }
    finally { button.disabled = false; }
  }

  async function openTrainingBuyers(productId) {
    state.selectedAdminTrainingId = productId;
    state.adminTrainingPurchases = await api.request(`/admin/training/${productId}/purchases`);
    const product = state.adminTraining.find((item) => item.id === productId);
    document.getElementById("adminTrainingDetailTitle").textContent = `Покупатели · ${product?.title || "обучение"}`;
    document.getElementById("trainingMaterialForm").hidden = true;
    elements.adminTrainingMaterials.replaceChildren(); elements.adminTrainingDetail.hidden = false;
    if (!state.adminTrainingPurchases.length) { const empty = document.createElement("div"); empty.className = "history-empty"; empty.textContent = "Покупок пока нет"; elements.adminTrainingBuyers.replaceChildren(empty); return; }
    elements.adminTrainingBuyers.replaceChildren(...state.adminTrainingPurchases.map(createTrainingBuyerCard));
  }

  function createTrainingBuyerCard(purchase) {
    const card = document.createElement("article"); card.className = "training-buyer-card";
    const avatar = document.createElement("span"); avatar.className = "conversation-avatar"; avatar.textContent = (purchase.buyer.first_name || purchase.buyer.username || "A").slice(0, 1).toUpperCase();
    if (purchase.buyer.photo_url) { const image = document.createElement("img"); image.src = purchase.buyer.photo_url; image.alt = ""; avatar.replaceChildren(image); }
    const copy = document.createElement("div"); const name = document.createElement("strong"); name.textContent = purchase.buyer_display_name || [purchase.buyer.first_name, purchase.buyer.last_name].filter(Boolean).join(" ");
    const course = document.createElement("small"); course.textContent = purchase.title_snapshot;
    const usernameValue = purchase.buyer_username || purchase.buyer.username;
    const username = document.createElement("small"); username.textContent = `${usernameValue ? `@${usernameValue} · ` : "Username не указан · "}Telegram ID ${purchase.buyer_telegram_id || purchase.buyer.telegram_id}`;
    const meta = document.createElement("span"); meta.textContent = `Заказ #${purchase.id.slice(0, 8)} · ${formatDate(purchase.created_at)} · ${formatNumber(purchase.price_af_coins)} AF Coins · Статус: ${trainingAdminOrderStatusLabel(purchase.status)}`; copy.append(name, course, username, meta); card.append(avatar, copy);
    if (purchase.buyer_username) { const chat = document.createElement("button"); chat.type = "button"; chat.className = "training-order-secondary"; chat.dataset.trainingBuyerUsername = purchase.buyer_username; chat.textContent = "💬 Написать"; card.append(chat); }
    if (purchase.product_type === "personal") {
      const notification = document.createElement("small"); notification.className = `training-notification-status is-${purchase.admin_notification_status}`;
      notification.textContent = purchase.admin_notification_status === "sent" ? "Уведомление администратору отправлено" : purchase.admin_notification_status === "failed" ? `Уведомление не доставлено: ${purchase.admin_notification_error || "Telegram API error"}` : "Уведомление ожидает отправки";
      card.append(notification);
      if (["failed", "pending", "sending"].includes(purchase.admin_notification_status)) { const retry = document.createElement("button"); retry.type = "button"; retry.className = "training-order-secondary"; retry.dataset.trainingNotify = purchase.id; retry.textContent = "Повторить уведомление"; card.append(retry); }
    }
    if (purchase.product_type === "personal" && purchase.status !== "completed") { const action = document.createElement("button"); action.type = "button"; action.dataset.trainingPurchaseAction = purchase.status === "awaiting_start" ? "in_progress" : "completed"; action.dataset.purchaseId = purchase.id; action.textContent = purchase.status === "awaiting_start" ? "Начать обучение" : "✅ Завершить"; card.append(action); }
    if (purchase.product_type === "automatic" && purchase.delivery_status === "failed") { const retry = document.createElement("button"); retry.type = "button"; retry.dataset.trainingAdminRedeliver = purchase.id; retry.textContent = "Повторить автовыдачу"; card.append(retry); }
    return card;
  }

  async function updatePersonalTrainingStatus(button) {
    const currentPurchase = [...state.adminTrainingOrders, ...state.adminTrainingPurchases].find((item) => String(item.id) === String(button.dataset.purchaseId));
    const username = currentPurchase?.buyer_username || currentPurchase?.buyer?.username;
    const buyerLabel = username ? `@${username}` : currentPurchase?.buyer_display_name || `Telegram ID ${currentPurchase?.buyer_telegram_id || "не указан"}`;
    if (button.dataset.trainingPurchaseAction === "completed" && !(await confirmAction(`Завершить обучение для ${buyerLabel}?`))) return;
    button.disabled = true;
    try {
      const purchase = await api.request(`/admin/training/purchases/${button.dataset.purchaseId}/status`, { method: "PATCH", body: JSON.stringify({ status: button.dataset.trainingPurchaseAction }) });
      state.adminTrainingPurchases = state.adminTrainingPurchases.map((item) => item.id === purchase.id ? purchase : item);
      state.adminTrainingOrders = state.adminTrainingOrders.map((item) => item.id === purchase.id ? purchase : item);
      elements.adminTrainingBuyers.replaceChildren(...state.adminTrainingPurchases.map(createTrainingBuyerCard));
      await loadAdminTraining(state.adminTrainingFilter); notify("Статус обучения обновлён");
    } catch (error) { button.disabled = false; notify(error.message); }
  }

  async function retryPersonalTrainingNotification(button) {
    button.disabled = true;
    try {
      const purchase = await api.request(`/admin/training/purchases/${button.dataset.trainingNotify}/notify`, { method: "POST" });
      state.adminTrainingOrders = state.adminTrainingOrders.map((item) => item.id === purchase.id ? purchase : item);
      renderAdminTrainingOrders(); notify("Повторная отправка поставлена в очередь");
    } catch (error) { button.disabled = false; notify(error.message); }
  }

  async function adminRedeliverTraining(button) {
    button.disabled = true;
    try {
      await api.request(`/admin/training/purchases/${button.dataset.trainingAdminRedeliver}/redeliver`, { method: "POST" });
      notify("Повторная автовыдача запущена");
    } catch (error) { button.disabled = false; notify(error.message); }
  }

  async function openTrainingMaterials(productId) {
    state.selectedAdminTrainingId = productId;
    state.adminTrainingMaterials = await api.request(`/admin/training/${productId}/materials`);
    const product = state.adminTraining.find((item) => item.id === productId);
    document.getElementById("adminTrainingDetailTitle").textContent = `Материалы · ${product?.title || "обучение"}`;
    elements.adminTrainingBuyers.replaceChildren(); elements.adminTrainingDetail.hidden = false;
    const form = document.getElementById("trainingMaterialForm"); form.hidden = false; form.reset(); form.elements.material_id.value = "";
    renderAdminTrainingMaterials();
  }

  function renderAdminTrainingMaterials() {
    if (!state.adminTrainingMaterials.length) { const empty = document.createElement("div"); empty.className = "history-empty"; empty.textContent = "Материалов пока нет"; elements.adminTrainingMaterials.replaceChildren(empty); return; }
    elements.adminTrainingMaterials.replaceChildren(...state.adminTrainingMaterials.map((material) => {
      const card = document.createElement("article"); card.className = "training-material-card";
      const copy = document.createElement("div"); const title = document.createElement("strong"); title.textContent = `${material.position + 1}. ${material.title}`;
      const meta = document.createElement("small"); meta.textContent = [trainingMaterialTypeLabel(material.material_type), material.mime_type, material.file_size ? formatFileSize(material.file_size) : null].filter(Boolean).join(" · "); copy.append(title, meta);
      const actions = document.createElement("div"); actions.className = "admin-record__actions";
      [["edit", "Заменить / изменить"], ["delete", "Удалить"]].forEach(([action, label]) => { const button = document.createElement("button"); button.type = "button"; button.dataset.trainingMaterialAction = action; button.dataset.materialId = material.id; button.textContent = label; actions.append(button); });
      card.append(copy, actions); return card;
    }));
  }

  function runTrainingMaterialAction(button) {
    const material = state.adminTrainingMaterials.find((item) => item.id === button.dataset.materialId);
    if (!material) return;
    if (button.dataset.trainingMaterialAction === "edit") {
      const form = document.getElementById("trainingMaterialForm"); form.elements.material_id.value = material.id; form.elements.title.value = material.title; form.elements.material_type.value = material.material_type; form.elements.position.value = material.position; form.elements.delivery_reference.value = material.delivery_reference; form.scrollIntoView({ behavior: "smooth", block: "start" }); return;
    }
    void deleteTrainingMaterial(material.id);
  }

  async function deleteTrainingMaterial(id) {
    if (!(await confirmAction("Удалить этот материал из выдачи? Уже купившие курс сохранят доступ к остальным материалам."))) return;
    try { await api.request(`/admin/training/materials/${id}`, { method: "DELETE" }); await openTrainingMaterials(state.selectedAdminTrainingId); notify("Материал удалён из выдачи"); }
    catch (error) { notify(error.message); }
  }

  async function saveTrainingMaterial(event) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const button = formElement.querySelector("button[type=submit]"); if (button.disabled) return; const defaultButtonText = button.textContent; button.disabled = true; button.textContent = "Сохраняем…";
    try {
      let materialType = form.get("material_type"); const file = form.get("file"); let upload = null;
      if (file?.size) {
        upload = await api.upload(file, "/admin/training/materials/upload?material_type=file", {
          kind: "training", prepareImage: false, maxBytes: 50 * 1024 * 1024, timeoutMs: 295000,
          onProgress: (percent) => { button.textContent = `Загрузка — ${percent}%`; },
        });
        materialType = upload.material_type || materialType;
        button.textContent = "Сохраняем материал…";
      }
      const reference = upload?.delivery_reference || String(form.get("delivery_reference") || "").trim();
      if (!reference) throw new Error("Добавьте текст, ссылку, file_id или выберите файл");
      const payload = { title: form.get("title"), material_type: materialType, delivery_reference: reference, mime_type: upload?.mime_type || null, file_size: upload?.file_size || null, metadata_json: upload?.metadata_json || {}, position: Number(form.get("position") || 0) };
      const id = form.get("material_id");
      await api.request(id ? `/admin/training/materials/${id}` : `/admin/training/${state.selectedAdminTrainingId}/materials`, { method: id ? "PATCH" : "POST", body: JSON.stringify(payload) });
      await openTrainingMaterials(state.selectedAdminTrainingId); notify("Материал сохранён");
    } catch (error) { notify(error.message); }
    finally { button.disabled = false; button.textContent = defaultButtonText; }
  }

  function closeAdminTrainingDetail() { elements.adminTrainingDetail.hidden = true; state.selectedAdminTrainingId = null; }

  async function openTrainingOrderDeepLink() {
    const purchaseId = new URLSearchParams(window.location.search).get("training_order");
    if (!purchaseId || state.me?.user.role !== "admin") return;
    await openAdminPanel(); switchAdminTab("training");
    [...document.querySelectorAll("[data-training-order-id]")]
      .find((card) => card.dataset.trainingOrderId === purchaseId)
      ?.scrollIntoView({ block: "center" });
  }

  async function openSupportCaseDeepLink() {
    const ticketId = new URLSearchParams(window.location.search).get("support_case");
    if (!ticketId || state.me?.user.role !== "admin") return;
    await openAdminPanel(); switchAdminTab("support");
    try {
      const ticket = await api.request(`/admin/support/tickets/${ticketId}`);
      elements.adminSupportTickets.replaceChildren(createSupportTicketCard(ticket, true));
    } catch (error) { notify(error.message); }
  }

  async function openDealSupportDeepLink() {
    const dealId = state.pendingSupportDealDeepLink;
    if (!dealId || !state.me) return;
    try {
      await api.request(`/deals/${encodeURIComponent(dealId)}/buyer-entry`);
      const conversation = await api.request(`/deals/${encodeURIComponent(dealId)}/conversation`, { method: "POST" });
      state.currentConversation = conversation;
      state.messages = [];
      openDealSupport(dealId);
      state.pendingSupportDealDeepLink = null;
    } catch (error) {
      notify(error.message);
    }
  }

  async function openDealDeepLink() {
    const dealId = state.pendingDealDeepLink;
    if (!dealId || state.openingDealDeepLink || !state.me) return;
    state.openingDealDeepLink = true;
    try {
      const endpoint = state.pendingDealBuyerEntry
        ? `/deals/${encodeURIComponent(dealId)}/buyer-entry`
        : `/deals/${encodeURIComponent(dealId)}`;
      const details = await api.request(endpoint);
      if (!details?.deal?.id) throw new Error("Сделка не найдена");
      const opened = await openDealConversation(details.deal.id);
      if (opened) {
        state.pendingDealDeepLink = null;
        state.pendingDealBuyerEntry = false;
      }
    } catch (error) {
      notify(error.message);
    } finally {
      state.openingDealDeepLink = false;
    }
  }

  async function openConversationDeepLink() {
    const conversationId = state.pendingConversationDeepLink;
    if (!conversationId || !state.me) return;
    try {
      await openConversation(encodeURIComponent(conversationId));
      state.pendingConversationDeepLink = null;
    } catch (error) {
      notify(error.message);
    }
  }

  async function openListingDeepLink() {
    const listingId = state.pendingListingDeepLink;
    if (!listingId || !state.me) return;
    await openListingDetails(encodeURIComponent(listingId));
    state.pendingListingDeepLink = null;
  }

  async function openInactiveSellerAdminDeepLink() {
    const sellerId = state.pendingAdminUnpublishSellerDeepLink || state.pendingAdminUserDeepLink;
    if (!sellerId || !state.me || state.openingAdminSellerDeepLink) return;
    state.openingAdminSellerDeepLink = true;
    try {
      if (state.me.user.role !== "admin") throw new Error("Требуется роль администратора");
      const details = await api.request(`/admin/users/${encodeURIComponent(sellerId)}`);
      await openAdminPanel();
      switchAdminTab("users");
      const telegramId = String(details.user.telegram_id);
      const searchInput = document.querySelector("#adminUserSearch input[name=q]");
      if (searchInput) searchInput.value = telegramId;
      await loadAdminUsers(telegramId);
      if (state.pendingAdminUnpublishSellerDeepLink) {
        const preview = await api.request(`/admin/users/${encodeURIComponent(sellerId)}/active-listings-count`);
        const count = Math.max(0, Number(preview.count || 0));
        if (!count) {
          notify("У пользователя нет активных объявлений");
        } else if (await confirmAction(`Снять с публикации ${count} объявлений пользователя?`)) {
          const result = await api.request(`/admin/users/${encodeURIComponent(sellerId)}/unpublish-active-listings`, { method: "POST" });
          await Promise.all([loadAdminUsers(telegramId), loadAdminListings(), refreshMarketplace()]);
          notify(`Снято с публикации: ${result.count}`);
        }
      }
      state.pendingAdminUserDeepLink = null;
      state.pendingAdminUnpublishSellerDeepLink = null;
    } catch (error) {
      notify(error.message || "Не удалось открыть пользователя");
    } finally {
      state.openingAdminSellerDeepLink = false;
    }
  }

  function switchAdminTab(tab) {
    document.querySelectorAll("[data-admin-tab]").forEach((button) => button.classList.toggle("is-active", button.dataset.adminTab === tab));
    document.querySelectorAll("[data-admin-panel]").forEach((panel) => { panel.hidden = panel.dataset.adminPanel !== tab; });
  }

 function renderAdminWithdrawals(withdrawals) {
  if (!withdrawals.length) {
    elements.adminWithdrawals.textContent = "Заявок пока нет";
    return;
  }

  elements.adminWithdrawals.replaceChildren(
    ...withdrawals.map((item) => {
      const card = document.createElement("div");
      card.className = "admin-withdrawal";

      const title = document.createElement("strong");
      title.textContent = `${formatNumber(item.amount)} AF Coins · ${withdrawalStatusLabel(item.status)}`;

      const user = document.createElement("span");
      const username = item.user_username
        ? `@${item.user_username}`
        : "username не указан";

      user.textContent =
        `${item.user_name || "Пользователь"} · ${username} · Telegram ID ${item.user_telegram_id}`;

      const details = document.createElement("small");
      details.textContent =
        `${item.payout_method} · ${item.details}`;

      const actions = document.createElement("div");
      actions.className = "admin-withdrawal__actions";

      if (item.status === "pending") {
        actions.append(
          adminActionButton(item.id, "approve", "Одобрить"),
          adminActionButton(item.id, "reject", "Отклонить")
        );
      }

      if (item.status === "approved") {
        actions.append(
          adminActionButton(item.id, "paid", "Завершено"),
          adminActionButton(item.id, "reject", "Отклонить")
        );
      }

      const history = document.createElement("button");
      history.dataset.financialHistory = item.user_id;
      history.textContent = "Финансовая история";
      actions.append(history);

      card.append(title, user, details, actions);
      return card;
    })
  );
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
    event.preventDefault();
    const formElement = event.currentTarget;
    const selected = state.adminBalanceUser;
    const data = new FormData(formElement);
    const rawAmount = Number(data.get("amount"));
    if (!selected) return setAdminBalanceLookupMessage("Сначала найдите пользователя", true);
    if (!Number.isFinite(rawAmount) || rawAmount <= 0) return void (elements.adminBalanceResult.textContent = "Введите сумму больше нуля");
    const signedAmount = state.adminBalanceDirection === "debit" ? -rawAmount : rawAmount;
    const username = selected.user.username ? `@${selected.user.username}` : `Telegram ID ${selected.user.telegram_id}`;
    const action = signedAmount > 0 ? "Начислить" : "Списать";
    if (!(await confirmAction(`${action} ${formatNumber(rawAmount)} AF Coins ${signedAmount > 0 ? "пользователю" : "у пользователя"} ${username}?`))) return;
    const button = formElement.querySelector("button[type=submit]");
    button.disabled = true;
    elements.adminBalanceResult.textContent = "Сохраняем операцию…";
    try {
      const before = selected.wallet.available_balance;
      const wallet = await api.request("/admin/balance-adjustments", {
        method: "POST",
        body: JSON.stringify({
          user_id: selected.user.id,
          amount: signedAmount,
          reason: String(data.get("reason") || "").trim() || "Корректировка баланса администратором",
        }),
      });
      selected.wallet = wallet;
      elements.adminBalanceResult.classList.remove("is-error");
      renderAdminBalanceUser(selected);
      const title = document.createElement("strong"); title.textContent = "✅ Баланс изменён";
      const values = document.createElement("span"); values.textContent = `Было: ${formatNumber(before)} AF Coins\nСтало: ${formatNumber(wallet.available_balance)} AF Coins`;
      elements.adminBalanceResult.replaceChildren(title, values);
      formElement.reset();
      setAdminBalanceDirection(state.adminBalanceDirection);
      await loadAdminFinancialHistory(selected.user.id);
    } catch (error) {
      const message = error.status === 409 ? "Недостаточно AF Coins для списания" : "Не удалось изменить баланс. Проверьте данные и попробуйте снова.";
      elements.adminBalanceResult.textContent = message;
      elements.adminBalanceResult.classList.add("is-error");
    } finally { button.disabled = false; }
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

  function bind(element, eventName, handler, label) {
    if (!element) {
      reportClientError("missing_dom_element", new Error(`Не найден элемент ${label}`));
      return;
    }
    element.addEventListener(eventName, handler);
  }

  function installGlobalErrorHandlers() {
    window.addEventListener("error", (event) => {
      const errorId = reportClientError("window_error", event.error || new Error(event.message));
      notify(`Ошибка загрузки. Код: ${errorId}`);
    });
    window.addEventListener("unhandledrejection", (event) => {
      const errorId = reportClientError("unhandled_rejection", event.reason);
      notify(`Ошибка загрузки. Код: ${errorId}`);
    });
    window.addEventListener("offline", () => {
      state.serverAvailable = false;
      elements.syncStatus.hidden = false;
      elements.syncStatusText.textContent = "Нет подключения к интернету. Данные обновятся после восстановления сети.";
    });
    window.addEventListener("online", () => {
      state.serverAvailable = true;
      void bootstrap({ automatic: true });
    });
    window.addEventListener("autoflow:api-error", (event) => {
      if (Number(event.detail?.status || 0) !== 401 || !state.me) return;
      state.serverAvailable = false;
      showStartupError("Сессия Telegram истекла. Закройте Mini App и откройте Market заново.", false);
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        state.hiddenAt = Date.now();
        return;
      }
      const inactiveFor = state.hiddenAt ? Date.now() - state.hiddenAt : 0;
      state.hiddenAt = null;
      if (inactiveFor >= 60000 && window.navigator.onLine !== false) void bootstrap({ automatic: true });
    });
    window.addEventListener("pageshow", (event) => {
      if (event.persisted && window.navigator.onLine !== false) void bootstrap({ automatic: true });
    });
  }

  function safeTelegramCall(operation, callback) {
    try { callback(); }
    catch (error) { reportClientError(`telegram_${operation}`, error); }
  }

  function reportClientError(context, error) {
    const errorId = error?.autoflowErrorId || createErrorId();
    if (error && typeof error === "object") error.autoflowErrorId = errorId;
    const expectedDegradation = context.startsWith("optional_") || context === "admin_optional" || context === "catalog_suggestions" || context === "refresh_after_checkout";
    const diagnostic = {
      error_id: errorId,
      context,
      build: document.querySelector('meta[name="autoflow-build"]')?.content || "unknown",
      endpoint: error?.endpoint || null,
      status: Number(error?.status || 0),
      error_type: error?.errorType || error?.name || typeof error,
      platform: telegram?.platform || "browser",
      telegram_version: telegram?.version || null,
      startup_stage: window.AutoFlowStartupStage || "unknown",
      user_agent: String(window.navigator?.userAgent || "unknown").slice(0, 200),
      online: window.navigator?.onLine !== false,
      related_id: state.currentConversation?.deal?.id || state.currentConversation?.listing?.id || null,
      training_id: error?.trainingId || null,
      material_count: Number.isInteger(error?.materialCount) ? error.materialCount : null,
      duration_ms: Number.isFinite(error?.duration_ms) ? error.duration_ms : null,
      upload_stage: error?.upload_stage || null,
      file_mime: error?.file_mime || null,
      file_size: Number.isFinite(error?.file_size) ? error.file_size : null,
      prepared_mime: error?.prepared_mime || null,
      prepared_size: Number.isFinite(error?.prepared_size) ? error.prepared_size : null,
      image_width: Number.isFinite(error?.image_width) ? error.image_width : null,
      image_height: Number.isFinite(error?.image_height) ? error.image_height : null,
      compression_error_type: error?.compression_error_type || null,
      photo_index: Number.isInteger(error?.photoIndex) ? error.photoIndex : null,
      client_time: new Date().toISOString(),
    };
    console[expectedDegradation ? "warn" : "error"]("[AutoFlow Client]", diagnostic);
    if (state.me && api) {
      void api.request("/diagnostics/client", {
        method: "POST",
        body: JSON.stringify(diagnostic),
        timeoutMs: 4000,
        retries: 0,
      }).catch((diagnosticError) => {
        console.warn("[AutoFlow Client] diagnostic delivery failed", {
          error_id: errorId,
          status: Number(diagnosticError?.status || 0),
          error_type: diagnosticError?.errorType || diagnosticError?.name || "Error",
        });
      });
    }
    return errorId;
  }

  function reportStartupStage(stage, metadata = {}) {
    window.AutoFlowStartupStage = stage;
    const userId = state.me?.user?.telegram_id || telegram?.initDataUnsafe?.user?.id || null;
    const entry = {
      stage,
      telegram_user_id: userId,
      platform: telegram?.platform || "browser",
      user_agent: String(window.navigator?.userAgent || "unknown").slice(0, 180),
      time: new Date().toISOString(),
      ...metadata,
    };
    console.info("[AutoFlow Startup]", entry);
    try { window.dispatchEvent(new CustomEvent("autoflow:startup-stage", { detail: entry })); }
    catch (_error) { /* Diagnostics must never block startup. */ }
  }

  function showStartupLoading(message) {
    if (!elements.startupStatus) return;
    elements.startupStatus.hidden = false;
    elements.startupSpinner.hidden = false;
    elements.startupTitle.textContent = "AutoFlow Market";
    elements.startupMessage.textContent = message;
    elements.startupRetry.hidden = true;
  }

  function showStartupError(message, canRetry) {
    if (!elements.startupStatus) return;
    elements.startupStatus.hidden = false;
    elements.startupSpinner.hidden = true;
    elements.startupTitle.textContent = "AutoFlow Market";
    elements.startupMessage.textContent = message;
    elements.startupRetry.hidden = !canRetry;
  }

  function hideStartup() {
    if (elements.startupStatus) elements.startupStatus.hidden = true;
  }

  function updateSyncStatus() {
    if (!elements.syncStatus) return;
    const count = state.failedOptional.size;
    elements.syncStatus.hidden = count === 0;
    if (count) elements.syncStatusText.textContent = "Некоторые данные временно недоступны. Основные функции продолжают работать.";
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
  function listingTitle(listing) { return [listing?.brand, listing?.model].filter(Boolean).join(" ") || "Автомобиль"; }
  function deliveryTimeLabel(value) {
    return ({
      up_to_15m: "до 15 минут",
      up_to_30m: "до 30 минут",
      up_to_1h: "до 1 часа",
      up_to_3h: "до 3 часов",
      up_to_6h: "до 6 часов",
      up_to_12h: "до 12 часов",
      up_to_24h: "до 24 часов",
    })[value] || "до 1 часа";
  }
  function formatNumber(value) { return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value)); }
  function formatDate(value) { return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(value)); }
  function formatMessageTime(value) { return value ? new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : ""; }
  function trainingTypeLabel(value) { return value === "personal" ? "Персональное обучение" : "Автоматическое обучение"; }
  function trainingAvailabilityLabel(value) { return ({ available: "Доступно", unavailable: "Недоступно", coming_soon: "Скоро" })[value] || value; }
  function trainingPurchaseStatusLabel(value) { return ({ awaiting_start: "Оплачено", in_progress: "В процессе", completed: "Завершено" })[value] || value; }
  function trainingAdminOrderStatusLabel(value) { return ({ awaiting_start: "PAID", in_progress: "IN_PROGRESS", completed: "COMPLETED" })[value] || value; }
  function trainingDeliveryStatusLabel(value) { return ({ not_applicable: "Не требуется", pending: "Ожидает отправки", sending: "Отправляется", delivered: "Доставлено", failed: "Ошибка отправки" })[value] || value; }
  function trainingMaterialTypeLabel(value) { return ({ text: "Текст", link: "Ссылка", photo: "Фото", video: "Видео", document: "Документ" })[value] || value; }
  function formatFileSize(value) { const bytes = Number(value || 0); return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} МБ` : `${Math.max(1, Math.round(bytes / 1024))} КБ`; }
  function uniqueValues(values) { return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru")); }
  function statusLabel(status) { return ({ active: "Доступно", reserved: "Деньги под защитой", sold: "Уже продано", paused: "Снято с публикации", deleted: "Удалено" })[status] || status; }
  function dealStatusLabel(status) { return ({ pending_payment: "Ожидается оплата", paid: "Ожидается передача автомобиля", seller_contacted: "Продавец готов передать автомобиль", transfer_in_progress: "Продавец сообщил о передаче", buyer_confirmed: "Получение подтверждено", completed: "Покупка завершена", disputed: "На рассмотрении поддержки", cancelled: "Отменена" })[status] || status; }
  function withdrawalStatusLabel(status) { return ({ pending: "Ожидает проверки", approved: "Одобрена", paid: "Выплачена", rejected: "Отклонена", cancelled: "Отменена" })[status] || status; }
  function supportStatusLabel(status) { return ({ new: "Новое", open: "Открыто", in_progress: "В работе", resolved: "Решено", closed: "Закрыто" })[status] || status; }
})();
