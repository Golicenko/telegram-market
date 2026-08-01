# AUTOFLOW MARKET

Telegram Mini App автомобильного маркетплейса с мобильным чёрно-оранжевым интерфейсом, FastAPI API и PostgreSQL. Внутри приложения цены и баланс выражены только в **AF Coins**. Telegram Stars (`XTR`) предусмотрены исключительно как внешний способ пополнения 1:1 и пока не выставляются реальным invoice.

## Структура

```text
telegram-market/
├─ Dockerfile             # production image: backend + Mini App
├─ start.sh               # migrations, then Uvicorn on Railway PORT
├─ railway.json           # Docker build, pre-deploy migration, healthcheck
├─ compose.yaml
├─ backend/
│  ├─ .env.example
│  ├─ requirements.txt
│  ├─ alembic.ini
│  ├─ app/
│  │  ├─ main.py          # FastAPI, CORS, раздача загруженных фото
│  │  ├─ auth.py          # серверная проверка Telegram initData и ролей
│  │  ├─ models.py        # SQLAlchemy-модели PostgreSQL
│  │  ├─ schemas.py       # входные и выходные схемы API
│  │  ├─ services.py      # транзакции кошелька, объявления, диалоги, сделки, вывод
│  │  ├─ routes.py        # HTTP API и Telegram webhook
│  │  └─ bot.py           # уведомления продавцу и покупателю через Bot API
│  ├─ migrations/
│  │  └─ versions/
│  │     ├─ 0001_initial.py
│  │     └─ 0002_market_features.py
│  └─ uploads/
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
pip install -r requirements.txt
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Откройте `http://127.0.0.1:8000`: FastAPI раздаёт и API, и Mini App из одного origin. В `.env.example` включён локальный debug-пользователь.

## Деплой в Railway

Railway автоматически обнаруживает корневой `Dockerfile`. Перед деплоем `railway.json` запускает `python /app/backend/scripts/migrate.py`: runner проверяет `DATABASE_URL`, ожидает готовности PostgreSQL и применяет Alembic-миграции. После успешной миграции `/app/start.sh` запускает Uvicorn на выданном Railway порту `0.0.0.0:$PORT`. Healthcheck: `/api/health`.

В Variables сервиса приложения нужны:

```text
BOT_TOKEN=<токен от BotFather>
ADMIN_ID=<ваш числовой Telegram ID>
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

`DATABASE_URL` формата `postgres://` или `postgresql://` автоматически преобразуется для драйвера `asyncpg`. Если у сервиса создан публичный Railway domain, приложение использует `RAILWAY_PUBLIC_DOMAIN` и само регистрирует `https://<domain>/api/telegram/webhook` в Telegram. Опционально задайте случайный `TELEGRAM_WEBHOOK_SECRET`.

Если PostgreSQL запускается одновременно с приложением, runner повторяет подключение до 12 раз с интервалом 5 секунд. Эти значения можно изменить переменными `MIGRATION_MAX_ATTEMPTS` и `MIGRATION_RETRY_SECONDS`. В Start Command не нужно повторно запускать Alembic: миграция выполняется только в Pre-deploy.

Загруженные фотографии по умолчанию лежат в файловой системе контейнера. Для сохранения между деплоями подключите Railway Volume к `/data` и задайте `UPLOAD_DIR=/data/uploads`; позже это можно заменить объектным хранилищем.

После первого успешного деплоя укажите публичный HTTPS URL приложения в BotFather как Menu Button / Mini App URL. Секреты не добавляйте в GitHub.

## Схема данных

| Таблица | Назначение |
|---|---|
| `users` | Telegram-профиль, роль `user/admin`, активность Mini App |
| `listings`, `listing_images` | объявления строго типа `regular` или `unique`, фотографии и закрепление на 24 часа |
| `account_listings` | разрешённые администратором карточки аккаунтов без логинов и паролей |
| `favorites`, `cart_items` | избранное и серверная корзина |
| `conversations`, `conversation_messages`, `price_offers` | постоянные диалоги до и после покупки, сообщения и торг |
| `deals`, `deal_messages` | резервирование и статусы сделки; `deal_messages` сохранена для обратной совместимости |
| `wallets` | `available_balance`, `frozen_balance`, `total_earned` |
| `wallet_transactions` | append-only история с балансами до/после |
| `star_payments` | уникальный Telegram charge ID и конвертация XTR → AF Coins |
| `withdrawal_requests` | ручной вывод и его статусы |
| `notifications` | уведомления внутри приложения |
| `admin_balance_adjustments`, `admin_actions` | аудит администраторских операций |

Все траты, резервы, расчёты, возвраты, выводы и корректировки выполняются в транзакциях PostgreSQL с `SELECT ... FOR UPDATE`. Цена, продавец, комиссия и итоговый баланс берутся только из базы. История кошелька защищена от `UPDATE` и `DELETE` триггером миграции.

## API

Все персональные и изменяющие данные маршруты используют проверенный `X-Telegram-Init-Data`; чтение активного каталога доступно без авторизации. Режим разработки доступен только при `DEBUG=true`.

- `GET /api/health`, `GET /api/me`, `GET /api/profile`
- `POST /api/uploads`
- `GET /api/listings?type=regular|unique`, `POST /api/listings`
- `PATCH|DELETE /api/listings/{id}`, `POST /api/listings/{id}/promote`
- `POST /api/admin/listings/unique`, `PATCH|DELETE /api/admin/listings/{id}`
- `GET /api/accounts`, `POST /api/admin/accounts`, `PATCH|DELETE /api/admin/accounts/{id}`
- `GET /api/cart`, `POST|DELETE /api/cart/items/{listing_id}`, `POST /api/cart/checkout`
- `GET|POST|DELETE /api/favorites...`
- `POST /api/conversations/listing/{listing_id}`, `GET /api/conversations`
- `GET /api/conversations/{id}`, `GET|POST /api/conversations/{id}/messages`
- `POST /api/conversations/{id}/offers`, `POST /api/conversations/{id}/offers/counter`
- `POST /api/offers/{id}/{accept|reject}`
- `GET /api/deals`, `GET /api/deals/{id}`
- `GET|POST /api/deals/{id}/messages`
- `POST /api/deals/{id}/seller-contacted|transfer|confirm|dispute|cancel`
- `GET /api/wallet`, `POST /api/wallet/star-payments/intent`
- `GET|POST /api/withdrawals`, `POST /api/withdrawals/{id}/cancel`
- `GET /api/admin/withdrawals`, `POST /api/admin/withdrawals/{id}/{approve|paid|reject}`
- `GET /api/admin/users`, `GET /api/admin/users/{id}`, `POST /api/admin/users/{id}/{block|unblock}`
- `GET /api/admin/listings`, `POST /api/admin/listings/{id}/{promote|publish|unpublish}`
- `GET /api/admin/deals`, `POST /api/admin/deals/{id}/resolve`, `GET /api/admin/conversations/{id}`
- `GET /api/admin/users/{id}/financial-history`, `POST /api/admin/balance-adjustments`
- `GET /api/notifications`, `POST /api/notifications/{id}/read`
- `POST /api/telegram/webhook`

## Что работает сейчас

- серверное разделение Market (`regular`) и «Уникальные» (`unique`);
- роль администратора по `ADMIN_ID` (также поддерживается список `ADMIN_TELEGRAM_IDS`); уникальные машины и аккаунты создаются только через защищённые сервером admin API;
- пустой каталог без выдуманных объявлений, фильтры, подсказки марки/модели из отдельного тестового JSON;
- редактирование, удаление и платное закрепление своего объявления на 24 часа за 15 AF Coins; для администратора закрепление бесплатно;
- серверная корзина, повторная проверка доступности и баланса перед покупкой;
- постоянный диалог начинается до покупки, хранится в PostgreSQL и поддерживает предложение, отклонение, принятие и встречную цену;
- резерв AF Coins, блокировка объявления, перевод диалога в сделку, спор, отмена, подтверждение через пять минут, расчёт 70/30;
- профиль, управление объявлениями, покупки, активные сделки, диалоги, история кошелька и пояснение замороженных средств;
- админ-панель с пользователями, блокировками, объявлениями, сделками/спорами, выводами и аудируемой корректировкой баланса;
- заявки на ручной вывод, заморозка средств, admin approve/paid/reject и обязательная причина отказа;
- Mini App initData HMAC-проверка, роли только на сервере, уведомления через Bot API;
- idempotent обработчик `successful_payment` с уникальным `telegram_payment_charge_id` и конвертацией 1:1.

## Намеренно отложено

- реальное создание invoice XTR и `pre_checkout_query`: `/wallet/star-payments/intent` отвечает `501`, баланс не меняется;
- автоматическая внешняя выплата: администратор только фиксирует ручную выплату;
- покупка и автоматическая передача аккаунтов; сейчас публикуются только описательные карточки, логины и пароли не хранятся;
- полный каталог марок/моделей — в JSON только небольшой явно помеченный тестовый набор;
- правила оплаты второго и последующих обычных объявлений отключены настройкой.

Никакие настоящие балансы, покупки или сделки не сохраняются в `localStorage`.
