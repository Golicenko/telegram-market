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
TRAINING_DELIVERY_COOLDOWN_SECONDS=300
SELLER_RESPONSE_TIMEOUT_SECONDS=86400
DEAL_NOTIFICATION_CLAIM_TIMEOUT_SECONDS=120
DEAL_NOTIFICATION_RETRY_BASE_SECONDS=30
DEAL_NOTIFICATION_MAX_ATTEMPTS=5
```

Если имя PostgreSQL-сервиса отличается от `Postgres`, исправьте ссылку `${{<имя сервиса>.DATABASE_URL}}`. Railway предоставляет `RAILWAY_PUBLIC_DOMAIN`; приложение регистрирует `https://<domain>/api/telegram/webhook` автоматически. Можно явно задать `PUBLIC_BASE_URL`.

Для постоянного хранения фотографий подключите Railway Volume к `/data` и задайте `UPLOAD_DIR=/data/uploads`. Без Volume файлы внутри контейнера исчезнут при новом деплое. Healthcheck: `GET /api/health`.

После первого успешного деплоя укажите публичный HTTPS URL в BotFather как Menu Button / Mini App URL. Секреты не добавляйте в GitHub.

### Кнопки запуска Mini App в Telegram

Приложение при каждом запуске Railway обновляет стандартную кнопку меню бота через Bot API и отдельно обновляет кнопку для `ADMIN_ID`. URL получает параметр версии `af_build`, поэтому Telegram открывает актуальную frontend-сборку. Команда `/start` также повторно обновляет кнопку конкретного пользователя.

Кнопка **«Открыть приложение» в профиле бота** относится к Main Mini App и хранится отдельно у Telegram. Bot API не позволяет менять её URL программно. Один раз укажите для Main Mini App в `@BotFather` стабильный адрес текущего Railway-сервиса — тот же адрес, который находится в `RAILWAY_PUBLIC_DOMAIN` или `PUBLIC_BASE_URL`. Не указывайте временный deployment URL: стабильный домен остаётся прежним, а актуальность файлов обеспечивают `no-store` для `index.html` и версии frontend-ресурсов.

Корневой адрес автоматически отвечает `307`-переходом на текущий `?af_build=...`. Поэтому в BotFather остаётся постоянный URL, а Telegram WebView при каждом новом frontend build получает новый конечный адрес.

## Устойчивый запуск Mini App

- HTML сразу показывает рабочую оболочку Market. Полноэкранной заставки нет; состояние авторизации и холодного запуска отображается компактной строкой над интерфейсом.
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
| `listings`, `listing_images`, `uploaded_images` | объявления строго типа `regular` или `unique`, до 10 фотографий с постоянным хранением в PostgreSQL, просмотры, срок закрепления |
| `account_listings` | прежние карточки аккаунтов; таблица сохранена для безопасной миграции, но скрыта из пользовательского UI |
| `training_products` | отдельные продукты раздела «Обучение», публикация, закрепление и soft delete |
| `training_materials` | закрытые ссылки/file_id материалов автовыдачи, порядок и метаданные; публичный API не отдаёт секрет выдачи |
| `training_purchases` | бессрочная серверная история покупок, снимок продукта, статусы персонального обучения и автовыдачи |
| `favorites`, `cart_items` | избранное и серверная корзина |
| `conversations`, `conversation_messages`, `price_offers` | постоянный диалог и торг до/после покупки |
| `deals`, `deal_messages` | защищённые средства и жизненный цикл сделки |
| `wallets` | `available_balance`, `frozen_balance`, `total_earned` |
| `wallet_transactions` | неизменяемая история с балансами до/после |
| `star_payment_intents`, `star_payments` | XTR invoice, привязка точного пополнения к объявлению, статус автоматического продолжения покупки и уникальный Telegram charge ID |
| `withdrawal_requests` | ручной вывод и статусы заявки |
| `notifications` | уведомления внутри приложения и постановка Bot API уведомлений |
| `support_tickets`, `support_messages` | обращения пользователя и переписка с администратором |
| `advertisements` | единственный управляемый из БД баннер Market |
| `admin_balance_adjustments`, `admin_actions` | аудит администраторских действий |

Все траты, защищённые суммы сделок, расчёты, возвраты, выводы и корректировки выполняются в транзакциях PostgreSQL с блокировкой нужных строк. Цена, продавец, комиссия и итоговый баланс берутся из БД, а не из запроса браузера. История кошелька защищена от `UPDATE` и `DELETE` триггером миграции.

### Миграция финансовой модели

Миграция `0006_split_wallet_balances` не удаляет и не обнуляет существующие деньги. Старый `available_balance`, происхождение которого исторически не фиксировалось, переименовывается в `purchased_balance`: средства остаются полностью доступными для покупок, но не становятся ошибочно выводимыми. Из старого замороженного баланса суммы действующих заявок на вывод переносятся в `earned_frozen_balance`; остальное сохраняется как защищённые средства покупок. Новые пополнения Stars идут только в `purchased_balance`, доход с продаж — только в `earned_balance`. Вывести можно исключительно `earned_balance`.

## Основные API-маршруты

Персональные и изменяющие данные маршруты требуют проверенный заголовок `X-Telegram-Init-Data`. Роль администратора проверяется сервером.

- `GET /api/health`, `GET /api/me`, `GET /api/profile`
- `POST /api/uploads`
- `GET /api/advertisement`
- `GET /api/listings?type=regular|unique`, `GET /api/listings/{id}`, `POST /api/listings`
- `POST /api/listings/{id}/purchase`, `POST /api/listings/{id}/purchase-topup-intent`
- `GET /api/wallet/star-payments/intents/{id}`, `POST /api/wallet/star-payments/intents/{id}/resume-checkout`
- `PATCH|DELETE /api/listings/{id}`, `POST /api/listings/{id}/promote`
- `POST /api/admin/listings/unique`, `PATCH|DELETE /api/admin/listings/{id}`
- `GET /api/training`, `GET /api/training/{id}`, `GET /api/training/mine`
- `POST /api/training/{id}/purchase`, `POST /api/training/purchases/{purchase_id}/redeliver`
- `GET|POST /api/admin/training`, `PATCH|DELETE /api/admin/training/{id}`
- `GET /api/admin/training/management`, `GET /api/admin/training/stats`
- `POST /api/admin/training/{id}/state/{publish|hide|pin|unpin}`
- `GET|POST /api/admin/training/{id}/materials`, `PATCH|DELETE /api/admin/training/materials/{material_id}`
- `POST /api/admin/training/materials/upload`
- `GET /api/admin/training/{id}/purchases`, `PATCH /api/admin/training/purchases/{purchase_id}/status`
- Устаревшие маршруты `/api/accounts` временно сохранены для совместимости и анализа старых данных, но пользовательский интерфейс их не вызывает.
- `GET /api/cart`, `POST|DELETE /api/cart/items/{listing_id}`, `POST /api/cart/checkout`
- `GET|POST|DELETE /api/favorites...`
- `POST /api/conversations/listing/{listing_id}`, `GET /api/conversations`
- `POST /api/conversations/listing/{listing_id}/messages`, `POST /api/conversations/{id}/hide`
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
- `GET /api/admin/users/{id}/active-listings-count`, `POST /api/admin/users/{id}/unpublish-active-listings`
- `GET /api/admin/listings`, `POST /api/admin/listings/{id}/{promote|publish|unpublish}`
- `GET /api/admin/deals`, `POST /api/admin/deals/{id}/resolve`
- `GET /api/admin/withdrawals`, `POST /api/admin/withdrawals/{id}/{approve|paid|reject}`
- `GET /api/admin/users/{id}/financial-history`, `POST /api/admin/balance-adjustments`
- `GET /api/admin/support/tickets`, `POST|PATCH /api/admin/support/tickets/{id}...`
- `POST /api/telegram/webhook`

### Администраторская рассылка

Администратор запускает текстовую рассылку командой `/рассылка Текст` или `#рассылка Текст`. Для фотографии команда указывается в подписи. Webhook только атомарно регистрирует команду по Telegram `update_id` и сразу отвечает Telegram; отправка выполняется отдельной фоновой задачей. Повторная доставка того же update и повторный запуск уже работающей задачи не отправляют сообщения заново. Пока одна рассылка имеет статус `pending` или `running`, вторая рассылка того же администратора не запускается. Итоговые количества успешных и неуспешных доставок сохраняются в PostgreSQL и отправляются администратору один раз после завершения. Telegram webhook защищён секретным заголовком; если `TELEGRAM_WEBHOOK_SECRET` не задан, сервер стабильно и безопасно выводит его из `BOT_TOKEN`, не сохраняя производное значение во frontend или логах.

## Обучение — библиотека и управление

Пользовательская вкладка «Аккаунты» заменена вкладкой «Обучение». Старые записи и таблица `account_listings` не удаляются: они временно скрыты из интерфейса и сохранены для аудита и безопасного отката.

Продукты обучения хранятся отдельно в `training_products` и поддерживают типы `personal` и `automatic`. Публичный API возвращает только опубликованные и не удалённые продукты; закреплённые продукты сортируются первыми. Создание, редактирование, публикация, снятие с публикации, бесплатное закрепление и soft delete доступны только администратору и повторно проверяются backend.

Миграция `0009_training_library` добавляет `training_materials`, `training_purchases` и связь с неизменяемой историей кошелька. Она не удаляет старые аккаунты, пользователей, покупки, сделки или балансы. Продукт с покупками архивируется через `published/deleted_at`, а покупка и её финансовый снимок сохраняются.

Покупка выполняется только backend: продукт и кошельки блокируются, повторный запрос возвращает существующую покупку, а уникальное ограничение `(product_id, buyer_id)` не позволяет списать деньги дважды. Для `personal` деньги остаются под защитой до статуса «Завершено»; для `automatic` расчёт фиксируется сразу и бот отправляет текущий упорядоченный набор материалов. Публичные ответы содержат только название, тип, размер и порядок материала — Telegram `file_id`, закрытый текст или ссылка остаются на сервере.

В профиле есть «Мои обучения» с отдельными списками персональных и автоматических покупок. Повторная выдача проверяет покупателя и покупку на сервере, использует блокировку отправки и настраиваемый cooldown. Администратор видит статистику из реальных `training_purchases`, фильтры каталога, покупателей, статусы персонального обучения и CRUD материалов. Новые материалы становятся доступны всем прежним законным покупателям при следующей выдаче. В навигации используется предоставленная эмблема `webapp/images/gg-training-icon.jpg`.

### Мобильный запуск и диагностика

Критический bootstrap загружает только Telegram `initData` и `/api/me`, после чего сразу показывает shell. Каталог, профиль, корзина, реклама, уведомления и обучение загружаются независимо: ошибка или timeout одного вторичного endpoint не блокирует Market. Для Railway cold start предусмотрены ограниченные повторные попытки без бесконечного цикла.

Диагностика фиксирует endpoint, HTTP-статус, длительность, тип ошибки, Telegram ID, платформу и startup stage (`telegram_ready`, `auth_started`, `auth_success`, `me_loaded`, `shell_rendered`, `market_loading`, `market_loaded`). Полный `initData`, токены и платёжные секреты не логируются.

## Публикация и продвижение объявлений

Публикация обычных объявлений полностью бесплатна и не ограничена оплатой. Создание, повторное создание, редактирование, изменение цены/описания, удаление и загрузка фотографий не списывают AF Coins.

Поля обычного объявления: от одной до десяти фотографий, произвольное название автомобиля, положительные мощность и максимальная скорость без искусственного верхнего лимита, описание и цена. Подсказки названий необязательны и не ограничивают ввод. Минимальная цена — 1 AF Coin; быстрые значения: 10, 25, 30, 50, 70 и 100. Пополнение через Telegram Stars работает по курсу 1 XTR = 1 AF Coin.

Единственная платная операция — закрепление обычного объявления на 24 часа за 5 AF Coins. При создании пользователь явно выбирает: «Закрепить за 5 AF» или «Опубликовать бесплатно». Backend в одной транзакции публикует объявление, блокирует кошелёк, списывает ровно 5 AF Coins, пишет финансовую операцию и устанавливает `pinned_until`. Повторный запрос с тем же `client_request_id` не списывает деньги повторно. При нехватке доступно точное пополнение через Telegram Stars с возвратом к незавершённой публикации. После истечения срока объявление остаётся активным и возвращается в обычную сортировку. Администратор бесплатно закрепляет только собственные уникальные автомобили и аккаунты; его обычные объявления подчиняются общей цене.

Проверить бесплатное создание нескольких объявлений и отдельное платное закрепление одного объявления за 5 AF Coins.

## Что работает реально

- Market (`regular`) и «Уникальные» (`unique`) разделены на сервере; уникальные объявления создаёт только администратор.
- Каталог не содержит выдуманных машин; фильтры и подсказки используют отдельный небольшой тестовый JSON.
- Создание нескольких обычных объявлений бесплатно; редактирование, удаление и продвижение проверяются сервером.
- Корзина хранится в PostgreSQL, а доступность и баланс повторно проверяются непосредственно перед покупкой.
- Покупка переводит AF Coins под защиту, блокирует объявление, создаёт сделку и постоянный внутренний диалог.
- На обычных и уникальных карточках доступна одинаковая серверная покупка. При недостатке баланса интерфейс показывает точную недостающую сумму и выставляет привязанный к объявлению XTR invoice; после `successful_payment` backend автоматически пытается завершить ту же покупку. Если объявление уже занял другой покупатель, начисленные AF Coins остаются на балансе.
- Сделка поддерживает статусы, торг, сообщения, отмену, спор, подтверждение через пять минут и расчёт продавцу 70% / платформе 30%.
- Сразу после успешного серверного сохранения данных передачи backend сохраняет 24-часовой deadline независимо от Telegram. Уведомление продавца доставляется отдельной очередью с PostgreSQL-состоянием, ограниченными retry и восстановлением прерванного `sending`. Если продавец не написал по конкретной сделке и не совершил действие по ней, worker атомарно отменяет сделку и один раз возвращает покупателю 100% защищённых AF Coins. Администратор получает решение о ручном снятии активных объявлений продавца; записи и финансовая история не удаляются.
- Профиль показывает объявления, покупки, активные сделки, диалоги и неизменяемую историю кошелька.
- Заявка на ручной вывод принимает только заработанные AF Coins и защищает их от повторной траты; администратор может approve/paid/reject с обязательной причиной отказа.
- Telegram `initData` проверяется по HMAC на сервере; роли нельзя подменить через CSS или JavaScript.
- Обычное пополнение от 10 Stars создаёт настоящий XTR invoice через Bot API. Для конкретной покупки разрешён счёт ровно на недостающую сумму от 1 XTR. `pre_checkout_query` проверяется сервером; AF Coins начисляются только после `successful_payment`. Уникальный `telegram_payment_charge_id` предотвращает двойное начисление.
- Команда `/start` показывает приветственное меню с кнопкой открытия Mini App и переключаемым разделом «Как это работает»; `/start <payload>` не перехватывается и остаётся доступным для deep-link сценариев.
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

## Мобильный чат

Для каждой неупорядоченной пары пользователей существует один постоянный `Conversation`. Простое открытие формы не создаёт запись и не отправляет уведомление: новый диалог появляется только с первым сообщением либо при создании сделки. Скрытие хранится на сервере отдельно для каждого участника; следующее входящее сообщение возвращает тот же диалог в список. Сообщения используют клиентский UUID и уникальное ограничение PostgreSQL для защиты от повторной отправки. Статусы `is_read/read_at` устанавливаются сервером при фактическом открытии диалога.

Экран чата использует `visualViewport`, событие Telegram `viewportChanged`, safe-area и отдельный фиксированный composer. Это сохраняет историю, набираемый текст и кнопку отправки над клавиатурой в мобильном WebView.

## Мобильный результат

Скриншот пустого Market на ширине 390 px: [docs/screenshots/market-390.png](docs/screenshots/market-390.png).

По сравнению с референсом сохранены компактный фирменный логотип, тёмный фон, оранжевые акценты, аватар, баланс, фильтры и закреплённая нижняя навигация. Демонстрационные машины удалены; баннер выводится только когда администратор активировал запись в БД; внутренняя кнопка «Закрыть» удалена, потому что Mini App закрывается нативной кнопкой Telegram.
