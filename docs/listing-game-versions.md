# Car Parking 1 / Car Parking 2 — 23.09.2026

Ветка: `agent/listing-game-versions`, основана на main после merged PR #54.

## Что изменено

- Самый верх формы создания автомобиля — обязательный выбор Car Parking 1 /
  Car Parking 2. Предвыбранного варианта нет. При редактировании показывается
  сохранённый вариант. Ошибка выбора останавливает запрос до загрузки фотографий.
- Возле фото — правило об оригинальном игровом скриншоте и запрет AI-изображений.
  Автоопределение AI не добавлено, правила форматов/количества фотографий не менялись.
- Игра видна на фото в Market/уникальных машинах, в начале полной страницы,
  в своих объявлениях и в существующем контексте сделки. Логика профиля,
  сделок и чатов не изменена: добавлена только подпись игры.
- Вместо звёздочки закрепления — спокойная тонкая золотая рамка `is-pinned`.
  Размер карточки не меняется. Рамка требует действующего backend-продвижения
  и будущего `pinned_until`; она снимается по таймеру и при возвращении в Mini App.
  Таймер управляет только оформлением, не продлевает срок и не меняет оплату.
- Финансы, покупка, обучение, вывод, админские сценарии, поддержка и API
  закрепления не менялись. Иконка Market также сохранена.

## PostgreSQL и API

Миграция: `backend/migrations/versions/0040_listing_game_version.py`.
Единственный head: `0040_listing_game_version`, предшественник `0039_car_sale_zero_fee`.

1. Добавляет `listings.game_version VARCHAR(24) NOT NULL` с временным default CP1.
   Это заполняет ВСЕ старые записи, включая скрытые, проданные и soft-deleted.
2. Добавляет CHECK с двумя допустимыми значениями:
   `car_parking_1`, `car_parking_2`.
3. Удаляет default в той же миграции. Для новых записей значение обязательно
   и в API, и на уровне БД. Строки/таблицы не удаляются.

Для обновления используется штатное `python -m alembic upgrade head` из backend.
Миграция должна выполниться до запуска обновлённого backend. Downgrade, который
стёр бы информацию об игре, явно запрещён; обратное изменение требует отдельной
миграции с сохранением данных.

- `POST /api/listings`, `POST /api/admin/listings/unique`: `game_version` обязателен;
  отсутствие, null и неизвестное значение дают 422.
- Существующие PATCH объявления: пропуск поля сохраняет игру, явный null запрещён;
  при передаче разрешены только CP1/CP2. Старые проверки владельца/роли сохраняются.
- Все ответы через `ListingOut`, в том числе профиль и контекст сделки, содержат игру.

## Файлы

Production:

- `backend/app/models.py` — колонка и CHECK.
- `backend/app/schemas.py` — create/update/output validation.
- `backend/app/services.py` — сохранение выбранного значения при создании.
- `backend/migrations/versions/0040_listing_game_version.py` — безопасный backfill.
- `webapp/index.html` — выбор игры, правило фото, информация о машине.
- `webapp/js/app.js` — payload/edit, подписи и визуальное истечение закрепления.
- `webapp/css/style.css` — выбор игры, badge, рамка.

Тесты:

- Новые: `backend/tests/test_listing_game_version.py`,
  `webapp/tests/listing-game-version.test.cjs`,
  `webapp/tests/listing-game-version-browser.cjs`.
- В существующих fixtures добавлено обязательное поле игры:
  `test_chat_architecture.py`, `test_chat_lifecycle_db.py`, `test_core_workflows.py`,
  `test_deal_delivery_flow.py`, `test_listing_checkout.py`, `test_listing_engagement.py`,
  `test_message_delivery_inactivity.py`, `test_price_offer_balance.py`,
  `test_support_cases.py`. Финансовые ожидания этих тестов не изменены.

## Проверено

- Backend: 293 теста, включая 11 новых; всё прошло.
- Frontend: 85 unit tests, включая 3 новых; всё прошло.
- Новый мобильный browser-сценарий 390px: верх формы, обязательность выбора,
  отсутствие upload/POST без игры (в том числе при обходе HTML validation),
  фото + публикация CP1/CP2, reload, карточка, подробности, свои объявления,
  редактирование без потери игры/повторной загрузки фото, исчезновение рамки.
- Регрессия навигации на 320/360/390/430px и профиля для user/admin на этих ширинах.
- Реальные HTTP endpoints через ASGI и SQLite: create/edit/get, отказ 422,
  обе игры, сохранность после закрытия и повторного открытия engine/session.
- Реальные NOT NULL/CHECK в SQLite; SQL миграции скомпилирован PostgreSQL dialect;
  ADD COLUMN из миграции исполнен над legacy-таблицей с разными статусами,
  проверена сохранность всех строк и значение CP1.
- `alembic heads`: одна актуальная вершина; `git diff --check`: без ошибок.
- Перед отправкой PR повторно пройдены все указанные тесты. Дополнительно
  `alembic upgrade 0039_car_sale_zero_fee:head --sql` с тестовым URL
  без подключения к БД сгенерировал транзакционный PostgreSQL SQL:
  ADD COLUMN → CHECK → DROP DEFAULT → обновление alembic_version → COMMIT.

Ограничения: живая PostgreSQL/Railway не затрагивалась, миграция на production не
запускалась. Browser tests используют API/Telegram fixtures — это не проверки
на физических iPhone/Android. Снимки `listing-game-form-390.png` и
`listing-game-market-390.png` содержат белые тестовые изображения, а не
объявления из production. Два клиента Telegram нужно проверить после deployment.
