# AUTOFLOW MARKET

Telegram Mini App для автомобильного маркетплейса: мобильный чёрно-оранжевый интерфейс, FastAPI API и PostgreSQL. Внутри сервиса цены, покупки и баланс выражены только в **AF Coins**. Telegram Stars (`XTR`) используются только для пополнения: после подтверждённого сервером платежа 1 XTR начисляет 1 AF Coin.

## Структура проекта

```text
telegram-market/
├─ Dockerfile
├─ railway.json                 # Railway build, migration и healthcheck
├─ start.sh                     # запуск Uvicorn на Railway PORT
├─ compose.yaml                 # локальный PostgreSQL
├─ backend/
│  ├─ .env.example
│  ├─ requirements.txt
│  ├─ requirements-dev.txt
│  ├─ alembic.ini
│  ├─ scripts/migrate.py        # проверка DATABASE_URL и Alembic с retry
│  ├─ migrations/versions/
│  │  ├─ 0001_initial.py
│  │  ├─ 0002_market_features.py
│  │  └─ 0003_payments_support_and_listing_details.py
│  ├─ tests/test_core_workflows.py
│  └─ app/
│     ├─ main.py                # FastAPI и раздача Mini App/uploads
│     ├─ auth.py                # проверка Telegram initData и роли
│     ├─ models.py              # SQLAlchemy-модели
│     ├─ schemas.py             # входные/выходные схемы API
│     ├─ services.py            # транзакции, сделки, кошельки, Stars
│     ├─ routes.py              # HTTP API и Telegram webhook
│     └─ bot.py                 # Telegram Bot API
├─ docs/screenshots/market-390.png
└─ webapp/
   ├─ index.html
   ├─ css/style.css
   ├─ js/api.js
   ├─ js/app.js
   ├─ data/vehicle_catalog.json
   └─ images/af-coin.jpg
```

## Запуск локально

Нужны Docker Desktop и Python 3.12+.

```powershell
docker compose up -d db
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Приложение доступно на `http://127.0.0.1:8000`: FastAPI раздаёт API и Mini App с одного origin. Локальная авторизация разрешена только при `DEBUG=true`.

Проверки:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall app migrations
.\.venv\Scripts\python.exe -m alembic upgrade head --sql
node --test ..\webapp\tests\*.test.cjs
```

## Railway

Railway использует корневой `Dockerfile` и конфигурацию `railway.json`.

Точные команды:

```text
Pre-deploy command: python /app/backend/scripts/migrate.py
Start Command:      /app/start.sh
```

Migration runner проверяет `DATABASE_URL`, преобразует Railway URL для `asyncpg`, ждёт PostgreSQL и применяет все Alembic-миграции. Не добавляйте второй `alembic upgrade` в Start Command.

Обязательные Variables сервиса приложения:

```text
BOT_TOKEN=<токен BotFather>
ADMIN_ID=<числовой Telegram ID администратора>
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

Полезные дополнительные Variables:

```text
TELEGRAM_WEBHOOK_SECRET=<случайная строка>
UPLOAD_DIR=/data/uploads
LISTING_PROMOTION_COST_AF_COINS=15
LISTING_PROMOTION_HOURS=24
SELLER_PAYOUT_PERCENT=70
STAR_TOPUP_MIN=100
STAR_TOPUP_MAX=1000
```

Если имя PostgreSQL-сервиса отличается от `Postgres`, исправьте ссылку `${{<имя сервиса>.DATABASE_URL}}`. Railway предоставляет `RAILWAY_PUBLIC_DOMAIN`; приложение регистрирует `https://<domain>/api/telegram/webhook` автоматически. Можно явно задать `PUBLIC_BASE_URL`.

Для постоянного хранения фотографий подключите Railway Volume к `/data` и задайте `UPLOAD_DIR=/data/uploads`. Без Volume файлы внутри контейнера исчезнут при новом деплое. Healthcheck: `GET /api/health`.

После первого успешного деплоя укажите публичный HTTPS URL в BotFather как Menu Button / Mini App URL. Секреты не добавляйте в GitHub.

## Устойчивый запуск Mini App

- HTML сразу показывает фирменный экран `AutoFlow Market — Загрузка…`; загрузка Telegram SDK не блокирует отображение страницы.
- Для входа критичны только настоящий `Telegram.WebApp.initData` и `GET /api/me`. В production нет автоматического входа под debug/admin-пользователем.
- Каталог, аккаунты, корзина, профиль, реклама и уведомления загружаются независимо через `Promise.allSettled`. Ошибка одного раздела не скрывает интерфейс и не ломает навигацию.
- GET-запросы имеют timeout 12 секунд и один ограниченный retry; `/me` использует timeout 10 секунд на попытку. Зависшие запросы отменяются через `AbortController`.
- После временной ошибки выполняется одно автоматическое восстановление, а событие `online` повторяет только недоступные данные. Бесконечных циклов retry нет.
- При открытии обычным браузером без Telegram initData показывается «Откройте AutoFlow Market через Telegram» без бесконечного loader.
- API по умолчанию всегда same-origin: `<публичный HTTPS-домен>/api`. `localhost` и `127.0.0.1` отсутствуют во frontend production-коде.
- Railway-логи API содержат endpoint, HTTP status, длительность, тип ошибки, проверенный Telegram ID, платформу и время. Токен бота, полный initData и тела запросов не логируются.

## Схема данных

| Таблица | Назначение |
|---|---|
| `users` | Telegram-профиль, роль `user/admin`, блокировка и активность Mini App |
| `listings`, `listing_images` | объявления строго типа `regular` или `unique`, одна фотография, просмотры, срок закрепления |
| `account_listings` | управляемые администратором карточки аккаунтов без логинов и паролей |
| `favorites`, `cart_items` | избранное и серверная корзина |
| `conversations`, `conversation_messages`, `price_offers` | постоянный диалог и торг до/после покупки |
| `deals`, `deal_messages` | резерв средств и жизненный цикл сделки |
| `wallets` | `available_balance`, `frozen_balance`, `total_earned` |
| `wallet_transactions` | неизменяемая история с балансами до/после |
| `star_payment_intents`, `star_payments` | XTR invoice, статус и уникальный Telegram charge ID |
| `withdrawal_requests` | ручной вывод и статусы заявки |
| `notifications` | уведомления внутри приложения и постановка Bot API уведомлений |
| `support_tickets`, `support_messages` | обращения пользователя и переписка с администратором |
| `advertisements` | единственный управляемый из БД баннер Market |
| `admin_balance_adjustments`, `admin_actions` | аудит администраторских действий |

Все траты, резервы, расчёты, возвраты, выводы и корректировки выполняются в транзакциях PostgreSQL с блокировкой нужных строк. Цена, продавец, комиссия и итоговый баланс берутся из БД, а не из запроса браузера. История кошелька защищена от `UPDATE` и `DELETE` триггером миграции.

## Основные API-маршруты

Персональные и изменяющие данные маршруты требуют проверенный заголовок `X-Telegram-Init-Data`. Роль администратора проверяется сервером.

- `GET /api/health`, `GET /api/me`, `GET /api/profile`
- `POST /api/uploads`
- `GET /api/advertisement`
- `GET /api/listings?type=regular|unique`, `GET /api/listings/{id}`, `POST /api/listings`
- `PATCH|DELETE /api/listings/{id}`, `POST /api/listings/{id}/promote`
- `POST /api/admin/listings/unique`, `PATCH|DELETE /api/admin/listings/{id}`
- `GET /api/accounts`, `POST /api/admin/accounts`, `PATCH|DELETE /api/admin/accounts/{id}`
- `GET /api/cart`, `POST|DELETE /api/cart/items/{listing_id}`, `POST /api/cart/checkout`
- `GET|POST|DELETE /api/favorites...`
- `POST /api/conversations/listing/{listing_id}`, `GET /api/conversations`
- `GET /api/conversations/{id}`, `GET|POST /api/conversations/{id}/messages`
- `POST /api/conversations/{id}/offers`, `POST /api/conversations/{id}/offers/counter`
- `POST /api/offers/{id}/{accept|reject}`
- `GET /api/deals`, `GET /api/deals/{id}`, `GET|POST /api/deals/{id}/messages`
- `POST /api/deals/{id}/{seller-contacted|transfer|confirm|dispute|cancel}`
- `GET /api/wallet`, `POST /api/wallet/star-payments/intent`
- `GET /api/wallet/star-payments/intents/{intent_id}`
- `GET|POST /api/withdrawals`, `POST /api/withdrawals/{id}/cancel`
- `GET|POST /api/support/tickets`, `POST /api/support/tickets/{id}/messages`
- `GET /api/notifications`, `POST /api/notifications/{id}/read`
- `GET|PUT|DELETE /api/admin/advertisement`, `POST /api/admin/advertisement/upload`
- `GET /api/admin/users`, `GET /api/admin/users/{id}`, `POST /api/admin/users/{id}/{block|unblock}`
- `GET /api/admin/listings`, `POST /api/admin/listings/{id}/{promote|publish|unpublish}`
- `GET /api/admin/deals`, `POST /api/admin/deals/{id}/resolve`
- `GET /api/admin/withdrawals`, `POST /api/admin/withdrawals/{id}/{approve|paid|reject}`
- `GET /api/admin/users/{id}/financial-history`, `POST /api/admin/balance-adjustments`
- `GET /api/admin/support/tickets`, `POST|PATCH /api/admin/support/tickets/{id}...`
- `POST /api/telegram/webhook`

## Публикация и продвижение объявлений

Публикация обычных объявлений полностью бесплатна и не ограничена оплатой. Создание, повторное создание, редактирование, изменение цены/описания, удаление и загрузка одной фотографии не списывают AF Coins.

Поля обычного объявления: одна фотография, марка, модель, мощность, максимальная скорость, описание и цена. Марка и модель поддерживают поиск с подсказками. Минимальная цена — 100 AF Coins; быстрые значения: 100, 150, 200, 300, 400 и 500.

Единственная платная операция — закрепление обычного объявления на 24 часа за 15 AF Coins. До запроса интерфейс спрашивает: «Закрепить объявление за 15 AF Coins?». Backend проверяет владельца и статус объявления, блокирует кошелёк, списывает ровно 15 AF Coins один раз, пишет транзакцию и возвращает `pinned_until`. Повторный запрос во время активного закрепления не списывает деньги повторно. После истечения срока объявление остаётся активным и возвращается в обычную сортировку. Администратор бесплатно закрепляет только собственные уникальные автомобили и аккаунты; его обычные объявления подчиняются общей цене.

Проверить бесплатное создание нескольких объявлений и отдельное платное закрепление одного объявления за 15 AF Coins.

## Что работает реально

- Market (`regular`) и «Уникальные» (`unique`) разделены на сервере; уникальные объявления создаёт только администратор.
- Каталог не содержит выдуманных машин; фильтры и подсказки используют отдельный небольшой тестовый JSON.
- Создание нескольких обычных объявлений бесплатно; редактирование, удаление и продвижение проверяются сервером.
- Корзина хранится в PostgreSQL, а доступность и баланс повторно проверяются непосредственно перед покупкой.
- Покупка резервирует AF Coins, блокирует объявление, создаёт сделку и постоянный внутренний диалог.
- Сделка поддерживает статусы, торг, сообщения, отмену, спор, подтверждение через пять минут и расчёт продавцу 70% / платформе 30%.
- Профиль показывает объявления, покупки, активные сделки, диалоги и неизменяемую историю кошелька.
- Заявка на ручной вывод замораживает средства; администратор может approve/paid/reject с обязательной причиной отказа.
- Telegram `initData` проверяется по HMAC на сервере; роли нельзя подменить через CSS или JavaScript.
- Пополнение создаёт настоящий XTR invoice через Bot API. `pre_checkout_query` проверяется сервером; AF Coins начисляются только после `successful_payment`. Уникальный `telegram_payment_charge_id` предотвращает двойное начисление.
- Обращения в поддержку, ответы администратора и один рекламный баннер хранятся в PostgreSQL.
- Верхний блок Market адаптирован под 320, 360, 390 и 430 px без горизонтальной прокрутки всей страницы.

## Что остаётся ручным или отложено

- Реальный XTR-платёж нужно принять двумя Telegram-аккаунтами после деплоя: автоматические тесты проверяют подпись, pre-checkout/успешное начисление и идемпотентность, но не заменяют платёж в клиенте Telegram.
- Внешняя выплата продавцу не автоматизирована: администратор вручную выплачивает средства и фиксирует статус `paid`.
- Автоматическая продажа и выдача логинов/паролей аккаунтов не реализована; приложение хранит только описательные карточки, пока не подтверждены правила игры/платформы.
- Полный справочник марок и моделей будет добавлен после выбора подтверждённого источника; сейчас JSON содержит небольшой тестовый набор.
- Для фотографий в Railway требуется подключённый Volume или последующая интеграция объектного хранилища.
- Обновление чата выполняется при открытии/перезагрузке экрана; WebSocket/push-синхронизация сообщений в открытом Mini App пока не добавлена.

Настоящие балансы, покупки, сделки, обращения и объявления не сохраняются в `localStorage`.

## Мобильный результат

Скриншот пустого Market на ширине 390 px: [docs/screenshots/market-390.png](docs/screenshots/market-390.png).

По сравнению с референсом сохранены компактный фирменный логотип, тёмный фон, оранжевые акценты, аватар, баланс, фильтры и закреплённая нижняя навигация. Демонстрационные машины удалены; баннер выводится только когда администратор активировал запись в БД; внутренняя кнопка «Закрыть» удалена, потому что Mini App закрывается нативной кнопкой Telegram.
