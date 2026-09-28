# Реферальная программа AutoFlow Market

Ветка: `agent/referral-program`. Изменения построены поверх main, без замены архитектуры приложения.

## Правило регистрации

Успешный реферал — **первый подтверждённый Telegram-вход нового пользователя в Mini App**.
Не первый платёж и не открытие ссылки без авторизации.

- Прямой запуск: код берётся исключительно из `start_param` внутри проверенного HMAC Telegram initData.
- Запуск через бота: доверенный Telegram webhook `/start CODE` сохраняет кандидата; награда возможна только при последующем подписанном входе.
- Первый сохранённый кандидат имеет приоритет. Повторный вход не меняет связь.
- Все существовавшие до миграции аккаунты, включая bot-only, помечаются обработанными и не могут стать новыми рефералами.
- Самоприглашение, неизвестный код, подменённая подпись, отдельный URL query из браузера не дают наград.
- Код — 8 случайных Base62-символов через `secrets`, UNIQUE. Коллизия повторяется внутри savepoint. Код создаётся при первом авторизованном обращении; неактивным старым аккаунтам массовое обновление не требуется.
- Лимит — 20 связей; блокировка пользователя-пригласителя и уникальный слот 1–20 защищают от конкурентного превышения.
- Данные сохраняются в PostgreSQL; очистка кэша или переустановка Telegram не изменяют их.

## Деньги

Награды: 3 друга → 10 AF, 10 → ещё 15 AF, 20 → ещё 50 AF. Всего 75 AF.

Использованы существующие `Wallet`, `WalletTransaction` и `wallet_transaction()`.
Бонусы зачисляются в заработанную часть `earned_balance` и `total_earned`, доступны по существующим правилам кошелька.
Нет клиентского прибавления баланса и вручную редактируемых счётчиков.

5% начисляется от реального AF-эквивалента подтверждённого оплаченного пополнения, включая точные доплаты.
Сейчас backend конвертирует Stars в AF 1:1; проценты считаются Decimal с точностью 0.01 AF.
Комиссия не вычитается из суммы пополнения друга.
После 20 приглашений она продолжает начисляться от этих друзей.

Кредит плательщику, `StarPayment`, бонус пригласителю и оба ledger-события сохраняются в одной транзакции.
Кошельки блокируются в одинаковом UUID-порядке. Повторный payment/intent не даёт второй кредит.
Строка пригласителя блокируется через PostgreSQL FOR NO KEY UPDATE: лимит по-прежнему
проверяется последовательно, но FK-проверки вставки финансового журнала не блокируются.
`ReferralReward.payment_id` и пара `user_id + milestone` дополнительно уникальны.
Ошибка до commit откатывает весь финансовый блок.

Ручное начисление админом, возвраты и сами бонусы не дают 5%.
Старый прямой платёж за обучение с purpose=`training_checkout` не является пополнением и исключён;
`training_topup` (реальное пополнение недостающей суммы) учитывается.
Покупка и settlement/refund не переписаны.

## API и Telegram

- `GET /api/referrals`: собственный код, полный URL, фактический count, limit, percent, milestones, canInvite и shareText.
- `POST /api/referrals/share-message`: только текущий авторизованный Telegram-пользователь; чужие user_id/code из body не используются.
- Оба ответа имеют `Cache-Control: no-store`.

Username и Main Mini App определяются по реальному `getMe`, без вшитого production-адреса:

1. Настроен `TELEGRAM_MINI_APP_SHORT_NAME` → `https://t.me/<bot>/<short_name>?startapp=<code>`.
2. `getMe.has_main_web_app=true` → `https://t.me/<bot>?startapp=<code>`.
3. Иначе → `https://t.me/<bot>?start=<code>`; кандидат хранится на сервере до Mini App входа.

Новые обязательные env не нужны: используются существующие BOT_TOKEN, DATABASE_URL и WebApp-конфигурация.
Опциональный `TELEGRAM_MINI_APP_SHORT_NAME` задавать только для реально настроенного short_name; для Main Mini App оставить переменную незаданной.

«Переслать» вызывает backend → `savePreparedInlineMessage`, привязанный к текущему telegram_id →
frontend `Telegram.WebApp.shareMessage(id)`. В статье настоящая inline-кнопка «Перейти в маркет»
с персональной ссылкой. Имя — first_name, без username; отсутствующее имя заменяется нейтральным текстом.
Нет parse_mode для пользовательского имени.

Prepared message кэшируется на сервере до expiration_date; повторная подготовка ограничена 25 секундами.
Хэш текста и URL инвалидирует кэш при смене имени или адреса бота.
Отмена нативного окна не вызывает вторую отправку или ложное «успешно».
Только для клиента без поддержки shareMessage/версии 8.0 используется `t.me/share/url`.

Официальные контракты: [Bot API](https://core.telegram.org/bots/api#savepreparedinlinemessage),
[Mini Apps](https://core.telegram.org/bots/webapps#initializing-mini-apps).

## UI

«Ещё» — самостоятельная основная вкладка вместо заглушки.
Сохранены существующие header, логотип, аватар, баланс, пополнение, «Информация» и все пять кнопок навигации.
Market и четыре предоставленные иконки не менялись.

Новый компонент: `webapp/js/referrals.js`; контракты для checkJs — `referrals.d.ts`.
Повторно использованы `AutoFlowApi`, `navigate`, `notify`, `renderBalance`, существующие кнопки и палитра.
Вёрстка настоящая, референс не используется как картинка.
Значения, доступность приглашения и статусы наград приходят с backend.
Активная страница обновляет данные раз в 30 секунд и после возвращения приложения на экран.
Кошелёк перечитывается через /me, без локального прибавления наград.
Полная ссылка копируется через Clipboard API с selection fallback.

## Миграция и выпуск

`backend/migrations/versions/0042_referral_program.py`, после `0041_seller_delivery_deadline`.

Добавлены:

- users: referral_code, pending_referral_code, referral_registration_processed;
- referrals: постоянная связь с уникальным приглашённым и слотом;
- referral_rewards: финансовый источник каждой награды и связь с ledger;
- referral_shares: claim/cooldown, prepared ID, expiry и hash текста/ссылки.

Нет удаления пользователей, объявлений, денег или истории.
Downgrade намеренно запрещён для сохранения финансового аудита; исправления — forward migration.
До запуска новой версии применить обычный `alembic upgrade head` через существующий Railway pre-deploy.
Production build остаётся `python scripts/build_webapp.py`; новый JS входит в общий content hash.

## Проверки

Локально выполнены:

- полный pytest: **333 passed, 1 skipped**;
- все Node unit/source tests: **85 passed**;
- checkJs/TypeScript 5.9.3 для нового компонента и его контрактов, без emit;
- Ruff 0.12.12 для новых Python-модулей, миграции и новых тестов;
- compileall, node --check, git diff --check;
- production build и проверка одинакового content hash всех четырёх JS/CSS assets;
- Alembic heads: один head; PostgreSQL SQL-preview миграции без DROP рабочих таблиц.

Browser harness: настоящий frontend с изолированными API/Telegram fixtures, Edge Chromium.
320 / 360 / 390 / 430 / 768 px: поля, заголовки, completed-карточки, no overflow,
native share/cancel, double tap, Clipboard fallback, старый клиент, лимит 20,
reload, ошибки API/retry, обновление баланса из сервера.
Отдельно перепроверены навигация, профиль и существующая передача автомобиля.

Важные backend regression-тесты: первая авторизация; повторный login;
/start без награды до login; старый аккаунт; неправильная подпись; code collision;
3/10/20 и 21-й пользователь; бонус после лимита; двойной webhook;
неправильный payer/amount/currency; откат платежа и регистрации при сбое;
нативная кнопка, user binding, cache/cooldown и изменение реального URL.
Повторная проверка выявила гонку запоздавшего ответа Telegram с более новым share claim:
исправлено повторное чтение ORM-объекта под блокировкой; добавлен regression-тест с двумя DB-сессиями.
Также проверена компиляция PostgreSQL lock modes: NO KEY UPDATE для users, UPDATE для wallets.
Матрица совместимости блокировок: [PostgreSQL](https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS).

### Что не проверено на живой инфраструктуре

Это не подтверждение пройденного production E2E:

- Нет подключённой тестовой PostgreSQL. Конкурентный тест **явно пропущен**.
  Для запуска: задать отдельную `REFERRAL_TEST_DATABASE_URL` и выполнить
  `pytest -q tests/test_referrals_postgres.py`.
  Он создаёт/удаляет только собственную временную schema, не использует DATABASE_URL приложения.
- Нет доступа к реальным iPhone/Android и production Telegram Bot API.
  Настоящее окно выбора чата и доставка inline-сообщения требуют проверки в Telegram.
- SQL-preview не заменяет применение миграции на staging PostgreSQL.

Перед production: применить миграцию на staging, проверить двумя новыми Telegram-аккаунтами:
переслать → кнопка получателя → первый вход → счётчик +1 → повторный вход без +1 →
реальное подтверждённое пополнение → один бонус 5% → перезапуск → история сохранилась.
Повторить native share на iPhone/Android и fallback на старом клиенте.
Не использовать реальные пользовательские деньги для неподготовленного теста.

## Изменённые файлы

Backend:
`app/auth.py`, `app/config.py`, `app/main.py`, `app/models.py`, `app/routes.py`,
`app/services.py`, новые `app/referrals.py` и `app/referral_routes.py`,
`.env.example`, `migrations/versions/0042_referral_program.py`, `scripts/build_webapp.py`.

Frontend:
`index.html`, `css/style.css`, `js/app.js`, новые `js/referrals.js` и `js/referrals.d.ts`.

Backend tests:
`test_referrals.py`, `test_referrals_postgres.py`, `test_bot_menu_url.py`,
`test_core_workflows.py`, `test_deal_lifecycle_control.py`, `test_listing_checkout.py`,
`test_training_star_orders.py`, `test_frontend_build.py`.

Frontend tests:
`referrals-browser.cjs`, `navigation-five-items-browser.cjs`, `profile-simple-browser.cjs`,
`ux-navigation-history.test.cjs`, `cache-busting.test.cjs`.
Документация: этот файл.
