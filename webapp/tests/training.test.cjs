const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");

test("user navigation replaces accounts with training and uses the supplied GG asset", () => {
  const nav = html.match(/<nav class="bottom-nav"[\s\S]*?<\/nav>/)?.[0] || "";
  assert.match(nav, /data-nav-target="training"/);
  assert.match(nav, /images\/gg-training-icon\.jpg/);
  assert.equal(fs.existsSync(path.join(root, "images", "gg-training-icon.jpg")), true);
  assert.match(nav, />Обучение</);
  assert.doesNotMatch(nav, />Аккаунты</);
});

test("training has list, details and an admin-only editor", () => {
  assert.match(html, /data-view="training"/);
  assert.match(html, /data-view="training-detail"/);
  assert.match(html, /data-open-training data-admin-only/);
  assert.match(app, /\/admin\/training/);
  assert.match(app, /\/training\/\$\{id\}/);
});

test("training purchase uses AF Coins and library uses authenticated backend workflows", () => {
  assert.match(html, /data-profile-tab="training"/);
  assert.match(html, /id="adminTrainingProducts"/);
  assert.match(html, /id="trainingMaterialForm"/);
  assert.match(app, /\/training\/\$\{flow\.product\.id\}\/purchase/);
  assert.match(app, /insufficient_af_coins/);
  assert.match(app, /\/wallet\/star-payments\/intent/);
  assert.match(app, /purpose: "training_topup", training_product_id: flow\.product\.id/);
  assert.doesNotMatch(app, /Math\.max\(10, Math\.ceil\(flow\.missing\)\)/);
  assert.match(app, /\["cancelled", "failed", "expired"\]\.includes\(payment\?\.status\)/);
  assert.match(app, /\/training\/purchases\/\$\{button\.dataset\.trainingRedeliver\}\/redeliver/);
  assert.match(app, /\/admin\/training\/management\?filter=/);
  assert.match(app, /\/admin\/training\/purchases\?product_type=personal/);
  assert.match(app, /training_order/);
  assert.doesNotMatch(app, /\/training\/\$\{product\.id\}\/purchase-intent/);
  assert.doesNotMatch(app, /Покупка обучения будет подключена на следующем этапе/);
});

test("personal training orders are managed without creating an internal conversation", () => {
  assert.match(app, /Заказ создан\. Статус: Ожидает обучения/);
  assert.match(app, /dataset\.trainingPurchaseAction = purchase\.status === "awaiting_start" \? "in_progress" : "completed"/);
  const purchaseFlow = app.slice(app.indexOf("async function buyTrainingProduct"), app.indexOf("async function redeliverTraining"));
  assert.doesNotMatch(purchaseFlow, /conversation|chat/i);
});

test("admin training orders expose durable notification state and filters", () => {
  assert.match(app, /data\.trainingOrderFilter|dataset\.trainingOrderFilter/);
  assert.match(app, /admin_notification_status/);
  assert.match(app, /\/admin\/training\/purchases\/\$\{button\.dataset\.trainingNotify\}\/notify/);
  assert.match(app, /dataTrainingBuyerUsername|dataset\.trainingBuyerUsername/);
  assert.match(app, /--chat-viewport-width/);
  assert.match(app, /Promise\.allSettled/);
  assert.match(app, /awaiting_start: "Оплачено"/);
  assert.match(app, /awaiting_start: "PAID"/);
  assert.match(app, /\["new", "Ожидают"\]/);
  assert.match(app, /"✅ Завершить"/);
  assert.match(app, /Завершить обучение для \$\{buyerLabel\}\?/);
});

test("training cards expose a real buy action and automatic editor has protected material inputs", () => {
  assert.match(app, /dataset\.buyTraining = product\.id/);
  assert.match(html, /id="automaticMaterialFields"/);
  assert.match(html, /name="automatic_material"[^>]*multiple/);
  assert.match(html, /video\/mp4,video\/quicktime,video\/webm/);
  assert.match(app, /Видео MP4, MOV или WebM — до 2 ГБ через Telegram, без ограничения длительности/);
  assert.match(app, /saveInitialAutomaticMaterials/);
});

test("automatic training restores a dedicated mobile video picker", () => {
  assert.match(app, /input\.name = "automatic_video"/);
  assert.match(app, /video\/\*,video\/mp4,video\/quicktime,video\/webm,\.mp4,\.mov,\.webm/);
  assert.match(app, /bind\(trainingVideoInput, "change", previewTrainingMaterials/);
  assert.match(app, /\.\.\.\(formElement\.elements\.automatic_video\?\.files \|\| \[\]\)/);
  assert.match(app, /Видео выбрано/);
  assert.match(app, /Загрузка видео/);
  assert.match(app, /✅ Видео загружено/);
  assert.match(app, /\/admin\/training\/uploads\/bot-link/);
  assert.match(app, /\/admin\/training\/uploads/);
  assert.match(app, /materials\/from-upload/);
  const trainingUpload = app.slice(app.indexOf("function ensureTrainingVideoInput"), app.indexOf("async function submitTrainingProduct"));
  assert.doesNotMatch(trainingUpload, /max_duration/i);
});

test("training purchase works from both the catalog card and the details screen", () => {
  assert.match(app, /trainingBuy\.dataset\.buyTraining/);
  assert.match(app, /buyTrainingProduct\(trainingBuy\.dataset\.buyTraining\)/);
  assert.match(app, /bind\(document\.getElementById\("trainingBuyButton"\), "click", \(\) => buyTrainingProduct\(\)/);
  assert.match(app, /: state\.selectedTraining/);
  assert.doesNotMatch(app, /"click", buyTrainingProduct, "trainingBuyButton"/);
});

test("admin can copy an exact production training deep link and startup opens it", () => {
  assert.match(app, /\["share", "Скопировать ссылку"\]/);
  assert.match(app, /\/admin\/training\/\$\{productId\}\/share-link/);
  assert.match(app, /navigator\.clipboard\?\.writeText/);
  assert.match(app, /pendingTrainingDeepLink/);
  assert.match(app, /openTrainingProductDeepLink/);
  assert.match(app, /training_/);
  assert.match(app, /Обучение недоступно/);
});

test("automatic materials are persisted one by one and publication waits for a saved material", () => {
  const materialFlow = app.slice(app.indexOf("async function saveInitialAutomaticMaterials"), app.indexOf("async function submitTrainingProduct"));
  assert.match(materialFlow, /await api\.request\(`\/admin\/training\/\$\{productId\}\/materials`/);
  assert.match(materialFlow, /await persist\(file\.name \|\| "Материал"/);
  assert.match(materialFlow, /onProgress/);
  assert.match(materialFlow, /savedProductId/);
  assert.match(app, /publishAfterMaterials/);
  assert.match(app, /materialResult\.savedCount/);
  assert.match(app, /Обучение оставлено скрытым: ни один материал не был сохранён/);
  assert.match(app, /formElement\.elements\.product_id\.value = saved\.id/);
  assert.match(app, /client_request_id: id \? undefined : state\.pendingTrainingRequestId/);
  assert.match(app, /Повторить загрузку/);
});

test("training covers use an uncropped 16:9 preview in every training surface", () => {
  const css = fs.readFileSync(path.join(root, "css", "style.css"), "utf8");
  assert.match(html, /id="trainingCoverPreview"/);
  assert.match(css, /\.training-card__media\{[^}]*aspect-ratio:16\/9[^}]*\}/);
  assert.match(css, /\.training-detail__cover\{[^}]*aspect-ratio:16\/9;object-fit:contain/);
  assert.match(css, /\.training-library-card>img\{[^}]*aspect-ratio:16\/9[^}]*object-fit:contain/);
  assert.match(css, /\.training-admin-card>img\{[^}]*aspect-ratio:16\/9[^}]*object-fit:contain/);
  assert.match(css, /\.training-cover-preview>div\{[^}]*aspect-ratio:16\/9/);
  assert.doesNotMatch(app, /media\.append\(badge\)/);
});

test("deleted training disappears from both public and admin state before backend refresh", () => {
  const flow = app.slice(app.indexOf("async function deleteTrainingProduct"), app.indexOf("async function submitSupportTicket"));
  assert.match(flow, /state\.training = state\.training\.filter/);
  assert.match(flow, /state\.adminTraining = state\.adminTraining\.filter/);
  assert.match(flow, /await loadAdminTraining\(state\.adminTrainingFilter\)/);
  assert.match(flow, /notify\("Обучение удалено"\)/);
});
