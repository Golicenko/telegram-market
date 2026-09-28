# Реферальная программа: backend и BONUS AF

Ветка `agent/referral-bonus-security`, от актуального main после PR #57.
Существующий интерфейс, API и финансовые сервисы переиспользованы; новой параллельной системы нет.

## Что исправлено

В PR #57 недоставало двух правил нового задания:

1. У bot-only аккаунта с `referral_registration_processed=false` можно было позднее
   записать реферального кандидата. Теперь наличие User проверяется **до INSERT**,
   а кандидат и доказательство его регистрации сохраняются только при создании User.
2. Награды зачислялись в `earned_balance`, из которого возможен вывод. Теперь все
   milestone и commission credits идут в отдельный `bonus_balance`.

## Допуск нового пользователя

`Telegram initData → HMAC/auth_date → telegram_id → SELECT User → INSERT только при отсутствии`.

- Существующий User не получает нового кандидата ни от URL, ни от последующего `/start`.
- Новый прямой Mini App login связывает проверенный `start_param` с INSERT User.
- Fallback `/start CODE`: только самый первый /start нового Telegram ID может создать
  регистрацию с кандидатом; сама связь и награда появляются после первого подписанного Mini App login.
  Здесь учитывается отсутствие User **до первого реферального /start**, а не до следующего входа.
- Обычный `/start` без кода навсегда исключает последующую атрибуцию этого аккаунта.
- `pending_referral_code` без нового серверного признака
  `referral_candidate_at_registration` недостаточно. Клиент эти поля не изменяет.
- Конкурентный INSERT проигрывает UNIQUE(telegram_id), перечитывает победившего User
  и не меняет его первоначальный кандидат.
- Self-referral, неизвестный код, заблокированный referrer, повторный login не дают наград.
- Старые связи и финансовая история не удаляются задним числом.

## Экономика и защита от повторов

Сохранена backend-конфигурация: лимит 20; 3 → 10 AF, 10 → ещё 15, 20 → ещё 50 (всего 75).
FOR NO KEY UPDATE на referrer сериализует допуск, UNIQUE(referrer,slot) и CHECK 1..20
страхуют БД. UNIQUE(referred_user_id) запрещает второго пригласителя.

Награды автоматические, в транзакции регистрации. UNIQUE(user_id,milestone), проверка
существующей награды под блокировкой кошелька и общий commit предотвращают двойное начисление.

5% считаются Decimal/Numeric от реально зачисленного оплаченного AF-пополнения.
100 → 5, 50 → 2.50, 25 → 1.25. Лимит 20 не отключает комиссию от существующих друзей.
Whitelist платёжных purpose: topup, cart_checkout, listing_checkout, training_topup,
listing_promotion_topup. Старый прямой training_checkout не считается пополнением.
Админские начисления, бонусы, возвраты по сделке, failed/cancelled/test не дают комиссии.

Применяются существующие StarPayment/StarPaymentIntent, UNIQUE charge_id,
UNIQUE(ReferralReward.payment_id) и один commit кредитования обоих кошельков.
`ReferralReward.payment_id → StarPayment.user_id/af_coin_amount` сохраняет источник.
В ledger также записаны источник REAL_PAID_TOPUP, topup_id, сумма, процент и комиссия;
чужие Telegram ID в пользовательскую историю не попадают.
Кошельки в пополнениях и расчётах между участниками блокируются в одном UUID-порядке.

## BONUS AF и покупки

- Wallet: purchased, earned и **bonus**, отдельные доступные и замороженные остатки.
- Общий доступный баланс = сумма трёх доступных частей. Frontend использует ответ backend.
- Вывод и резерв подарочной заявки по-прежнему допускают **только earned_balance**;
  bonus не участвует даже при прямом HTTP-запросе или старой, ранее корректной quote.
- При покупке расходуется bonus, затем purchased, затем earned.
- В Deal/TrainingPurchase хранится bonus_frozen_amount; в WalletTransaction —
  balance_breakdown со снимком всех частей и funding для списания/покупки.
- При отмене/споре/таймауте покупателю возвращается тот же тип средств.
- При settlement часть выручки, оплаченная бонусами, остаётся бонусной у продавца.
  Иначе два связанных аккаунта могли бы превратить бонус в выводимые AF через фиктивную продажу.
  Пропорция считается Decimal, округление бонусной части вверх до копейки не создаёт выводимый остаток.
- Обычная оплаченная выручка остаётся earned, существующие цены, комиссии и суммы выплат не изменены.
- То же правило применяется к personal/automatic training, иначе обучение стало бы обходом.

### Refund/chargeback исходного пополнения

В текущем репозитории **нет** обработчика refundStarPayment/refunded_payment/chargeback
и операции сторнирования самого оплаченного top-up. Есть возвраты защищённых средств
по сделкам — это не отмена исходного пополнения и не источник новой комиссии.
В рамках этой задачи новая система возврата Stars не добавлялась. При её внедрении
сторно комиссии должно войти в ту же финансовую транзакцию с сохранением истории.

## API и пересылка

- GET `/api/referrals` сохранён для существующего frontend.
- GET `/api/referrals/me` — совместимый alias с той же Telegram-авторизацией.
- POST `/api/referrals/share-message` сохранён: current user → лимит → Telegram
  savePreparedInlineMessage → user-bound preparedMessageId → WebApp.shareMessage.
- InlineKeyboardMarkup содержит персональную кнопку «Перейти в маркет»;
  legacy fallback сохранён. Bot token никогда не возвращается клиенту.
- Wallet API дополнительно возвращает bonus_balance и bonus_frozen_balance.
- Состояния и деньги хранятся в PostgreSQL; очистка клиентских данных ничего не меняет.

Существующие [официальные контракты Telegram](https://core.telegram.org/bots/api#savepreparedinlinemessage)
и [валидация Mini App initData](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app) сохранены.

## Миграция 0043_referral_bonus_safety

Новых таблиц нет. Добавлены:

- users.referral_candidate_at_registration;
- wallets.bonus_balance, wallets.bonus_frozen_balance + CHECK;
- deals.bonus_frozen_amount, training_purchases.bonus_frozen_amount + CHECK;
- wallet_transactions.balance_breakdown JSONB.

Старая миграция 0042 не переписана. Все существующие User помечаются обработанными;
старые pending-кандидаты очищаются, потому что их происхождение не подтверждено новым правилом.
Существующие Referral/ReferralReward не удаляются.

### Нельзя слепо выкатывать поверх уже потраченных старых наград

PR #57 мог начислить награды в earned. Владелец не знает, были ли начисления.
Поэтому новая миграция сначала проверяет ledger под блокировкой таблиц:

- Если наград не было — обычное добавление новых полей.
- Если награды есть, но после них не было расходов/резервов и суммы полностью сохранены,
  переносится точная сумма earned → bonus. Общий баланс неизменен, старые записи не редактируются;
  добавляется `referral_bonus_reclassified` audit transaction.
- Если после наград были расходы, резервы, вывод или сумма не сходится,
  **REFERRAL_LEGACY_REVIEW_REQUIRED** прерывает всю миграцию. Никакого угадывания происхождения,
  частичного списания, отрицательного баланса или уничтожения истории.

Порядок выпуска:

1. На staging/копии БД запустить `python scripts/audit_referral_legacy.py` (read-only, без Telegram ID/секретов).
2. При неоднозначной истории сначала сверить затронутые ledger/сделки/заявки и подготовить
   отдельное адресное решение. Не обходить guard через stamp, удаление наград или ручное уменьшение баланса.
3. Для переключения financial semantics остановить старые backend/worker-процессы и запись платежных операций.
   Нельзя одновременно оставлять старую версию, кредитующую earned, и новую бонусную модель.
4. `alembic upgrade head`, затем запуск новой версии. Production из этой задачи не менялся.
5. При старте фоновая recovery-задача назначает отсутствующие коды порциями по 100,
   с отдельными commit, SKIP LOCKED, retry коллизий и восстановлением после restart.
   Она не блокирует HTTP startup и никогда не создаёт Referral.
   Ручной повтор: `python scripts/backfill_referral_codes.py`.

Новые обязательные env отсутствуют. TELEGRAM_MINI_APP_SHORT_NAME остаётся опциональным
только для реального short_name. Main Mini App и username определяются существующим getMe.
Для тестов — отдельный REFERRAL_TEST_DATABASE_URL, никогда production DATABASE_URL.

## Реально выполненные проверки

- Изолированная локальная PostgreSQL 17.6 на loopback, без рабочих данных.
- Полная цепочка Alembic от пустой БД до 0043 применена успешно.
- Тесты migration: перенос 10 AF с неизменным total и append-only ledger;
  отказ при уже потраченных средствах или несогласованных earned/total_earned с полным rollback.
  Read-only preflight проверен на тех же сценариях и выдаёт совпадающий needs_review.
- Одновременные 25 регистраций: максимум 20; отдельно гонка двух пользователей на 20-й слот.
- Конкурентные повторные milestone, дублированные вебхуки, первый login одного ID по двум ссылкам.
- Существующий bot-only аккаунт, обычный /start до ссылки, повторный /start, повторный signed login.
- Одновременные top-up и settlement с общим referrer/seller.
- Backfill 204 старых аккаунтов двумя работниками, принудительная collision, повторный прогон без изменений.
- HTTP-запрет вывода бонусов, mixed-wallet reserve/refund/settlement, admin complete/refund,
  personal/automatic training без превращения bonus в earned.
- Полный backend pytest: **360 passed**, включая PostgreSQL, без skipped.
- Frontend Node unit/source: **85 passed**; referral browser harness 320/360/390/430/768 px.
- TypeScript/checkJs существующего referral component; Ruff изменённых backend-модулей и новых файлов;
  compileall; production build; git diff --check.

Дополнительный `alembic check` нашёл уже существовавшие различия имён индексов
training_inbox_uploads, wallet_transactions и формы UNIQUE/index users.telegram_id.
Новые поля 0043 расхождений не дали. Эти исторические эквивалентные индексы не переименовывались.

Это **не live Telegram E2E**: нет доступа к реальным iPhone/Android, двум пользовательским аккаунтам
и production Bot API. Настоящую пересылку/оплату на устройствах нужно проверить на staging перед выпуском.
Mocks/fixtures используются только в тестах внешнего Telegram transport, не в рабочей программе.

## Изменённые файлы

- app/auth.py, app/routes.py — INSERT-only candidate, повторный /start не меняет его.
- app/referrals.py — бонусное начисление, идемпотентность, audit logs, batched backfill.
- app/referral_routes.py — совместимый /me alias.
- app/main.py — фоновый backfill при старте.
- app/models.py, app/schemas.py — bonus buckets, provenance, API response.
- app/services.py — три источника средств, reserve/refund/settlement, общий порядок wallet locks.
- migrations/versions/0043_referral_bonus_safety.py — безопасная схема и guard старых наград.
- scripts/audit_referral_legacy.py, scripts/backfill_referral_codes.py — операционные инструменты.
- tests/test_referral_bonus_security.py, tests/test_referral_bonus_postgres.py — новые проверки.
- tests/test_core_workflows.py, tests/test_referrals.py — адаптация контрактов/registration fixture.
- docs/referral-program.md и этот отчёт.

Frontend layout, нижняя навигация и native share UI не переделывались.
