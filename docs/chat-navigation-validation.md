# Сделки, чаты и навигация

## Изменения и причины

Раньше создание ветки торга и создание предложения выполнялись в двух
транзакциях: отказ по балансу мог оставить пустой чат. Теперь ветка,
PriceOffer, системное сообщение и уведомление сохраняются атомарно.
Обычный диалог остаётся отдельной сущностью и не становится чатом сделки.

Единая серверная политика `app/chat_access.py` проверяет участника,
архивирование и наличие конкретного активного предложения либо оплаченной
сделки. Она применяется к деталям, сообщениям, прочтению и списку веток
профиля. Открытие чата завершённой сделки больше не восстанавливает его.
Отклонение закрывает ветку и отменяет оставшиеся активные предложения в ней.
Повторный торг создаёт новую ветку, не уничтожая историю предыдущей.

Запись сообщения блокирует основание ветки (объявление или сделку), затем
разговор. Ответ на предложение блокирует объявление, разговор и предложение.
После блокировки загруженные ранее объекты перечитываются. Финансовые
операции покупки, settlement/refund и Telegram-авторизация не заменялись.

## Состояния

- Торг доступен для `pending` / `accepted` при активном объявлении.
- `rejected`, `expired`, `cancelled`, legacy `countered` сами по себе не дают доступ.
- Принятие предложения сохраняет цену и активную ветку, но **не создаёт
  фиктивную оплаченную сделку** и не резервирует деньги до покупки.
- Сохранены финансовые статусы `paid`, `seller_contacted`,
  `transfer_in_progress`, `buyer_confirmed`, `disputed`: они допускают чат.
- `pending_payment`, `completed`, `cancelled` не допускают пользовательский чат.
- Архив обозначается существующим `archived_at`; сообщения не удаляются.
  Административный доступ для аудита сохранён.

## API (существующие маршруты, без новых публичных endpoints)

- `POST /api/conversations/listing/{listing_id}/offers`: атомарное начало торга.
- `POST /api/conversations/{id}/offers` и `/offers/counter`: только активная ветка.
- `POST /api/offers/{offer_id}/accept` и `/reject`: проверка основания и закрытие при отказе.
- `POST /api/deals/{deal_id}/conversation`: участник и активная оплаченная сделка.
- `GET /api/conversations/{id}`, `GET/POST .../{id}/messages`,
  `POST .../{id}/read`: единая проверка доступа.
- Legacy `GET/POST /api/deals/{deal_id}/messages`: закрытые/неоплаченные сделки запрещены.
- `GET /api/profile`: только действительно активные ветки.
- Неучастник получает 404; закрытый или необоснованный чат — 409;
  недостаточный баланс при предложении — 402.

## Навигация

Общий обработчик `goBack`, стек внутренних страниц и блокировка двойного
нажатия 450 мс. HTML-кнопки и Telegram BackButton используют один обработчик.
Зона нажатия 44×44, заголовок в потоке рядом с кнопкой, учитываются Telegram
safeAreaInset/contentSafeAreaInset и системные CSS safe areas.
На главных вкладках кнопки нет; существующая вкладка «Обучение» сохранена.

## Миграция

`0034_chat_lifecycle` после `0033_dialog_deal_threads`: расширяет CHECK
статусов PriceOffer и архивирует старые пустые/завершённые ветки. Не удаляет
пользователей, объявления, сообщения, сделки или кошельки. При downgrade
`expired`/`cancelled` переводятся в `rejected`; архивирование не отменяется.

Запуск после резервной копии на staging: `cd backend && python -m alembic upgrade head`.
Проверены единый Alembic head и генерация PostgreSQL SQL для диапазона
`0033_dialog_deal_threads:head`. Применение на живом PostgreSQL здесь не проверено.

## Проверки

- `cd backend && python -m pytest -q`: 228 passed.
- `node --test webapp/tests/*.test.cjs`: 76 passed.
- `node webapp/tests/navigation-browser.cjs` с установленным Playwright и Edge:
  320/360/390/430 px, safe areas, отсутствие overlap/overflow, обычный диалог,
  возврат chat → listing → Market, двойное нажатие, composer при высоте 420 px.
  В тесте API/Telegram SDK подменены, реальные платежи не выполняются.
- Новые DB service tests: открытие карточки без ветки; обычное сообщение;
  оффер → отказ → новая ветка; rollback при недостаточном балансе;
  принятие → покупка по согласованной цене → завершение; независимая вторая
  машина; запрет пустой ветки и доступа постороннего; terminal offer statuses.
- Прямые HTTP-тесты запрещают reopen/read/send для pending_payment/completed/cancelled.

DB service tests используют SQLite с SQLAlchemy: это проверка сохранения,
rollback и сервисов, **не доказательство поведения конкурентных PostgreSQL locks**.
Проверки на реальных iPhone/Android в Telegram, доставка уведомлений двум
аккаунтам и конкурентные запросы PostgreSQL остаются обязательной staging
проверкой перед production merge. Отсутствие устройств/тестовой БД не
заменено утверждением «всё проверено».

## Изменённые файлы

- backend/app/chat_access.py (новый)
- backend/app/models.py
- backend/app/routes.py
- backend/app/services.py
- backend/migrations/versions/0034_chat_lifecycle.py (новый)
- backend/tests/test_chat_lifecycle_db.py (новый)
- backend/tests/test_deal_delivery_flow.py
- backend/tests/test_price_offer_balance.py
- webapp/index.html
- webapp/css/style.css
- webapp/js/app.js
- webapp/tests/navigation-browser.cjs (новый)
- docs/chat-navigation-validation.md (этот отчёт)
