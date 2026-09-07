# Часть 2: уведомления, непрочитанные и неактивность

Изменения продолжают часть 1 (PR #49, уже merged в main).
Этот набор подготовлен отдельно от части 1. Пока предназначен для staging,
не является подтверждением проверки живого Railway/Telegram.

## Причины и решение

- Обычные сообщения использовали разовую BackgroundTasks-отправку без кнопки
  конкретного чата и без восстановления после рестарта.
- Счётчик учитывал только обычные диалоги; локальное обнуление мог расходиться
  с backend, а список использовал устаревший unread_count.
- Групповой sender автоотмены повторял всех адресатов при частичной ошибке.
- Предыдущая автоотмена возвращала объявление в active и требовала ручного
  снятия остальных объявлений. Теперь конкретный обработанный случай хранится
  в БД, объявления переводятся в paused в транзакции возврата.

## Таблицы и миграции

`0035_message_delivery` (после `0034_chat_lifecycle`):

- users: viewing_conversation_id, chat_presence_at. Присутствие в конкретном
  чате имеет срок 45 секунд и не определяется по любому запросу Mini App.
- notifications: delivery_status, delivery_claimed_at, delivery_sent_at,
  delivery_error, delivery_attempts, delivery_next_attempt_at, индекс статуса.
  Старые уведомления получают not_required и массово не переотправляются.
- conversation_messages: используются существующие is_read/read_at и
  client_message_id. Новых копий обычных сообщений не создаётся.

`0036_inactivity_state`:

- conversations: response_required_at, inactivity_deadline, inactivity_status,
  inactivity_processed_at. Статусы: not_required, waiting, answered, processed.
- deals: cancellation_reason = seller_inactive; сохранены существующие
  seller_response_deadline, seller_responded_at, seller_timeout_processed_at.
- Старые неоднозначные групповые отправки отключаются, чтобы не повторять
  частично доставленные сообщения. Их старые данные остаются для диагностики.
- Уже существующие deadlines оплаченных сделок сохраняются. Старые обычные
  диалоги не наказываются задним числом.

Таблицы не удаляются. Новые уведомления и payload с причиной, временем и
списком снятых объявлений являются сохраняемым журналом обработки.

## API

- Новый POST /api/conversations/{id}/presence?visible=true|false: сервер
  проверяет участника/доступ к чату, сохраняет либо освобождает присутствие.
- POST /api/conversations/{id}/read?through_message_id=...: отмечает прочитанным
  только полученную клиентом историю до указанного сообщения. Чужой ID запрещён.
- GET /api/conversations/unread-summary: включает активные сделки и обычные
  диалоги с явным conversation_type, не смешивая их сущности.
- Существующие endpoints отправки сообщений сохраняют сообщение и outbox
  атомарно. Legacy DealMessage также отражается в конкретной conversation,
  чтобы сообщение было видно в текущем Mini App.
- DealOut включает cancellation_reason. Существующий GET conversation
  проверяет права при переходе по deep link.

## Telegram и UI

Worker объединяет ожидающие сообщения адресата в одно короткое уведомление
с русским склонением. Единственная кнопка «Открыть» использует существующий
production web_app URL с conversation_id и build version. Telegram ID/токен
не помещаются в ссылку. Backend повторно проверяет доступ к диалогу.

При открытии: загрузка истории → прокрутка вниз → read receipt → новый
серверный unread-summary. Непрочитанные обозначены красным badge (1…9+)
в разделе диалогов/сделок, конкретном списке и существующей кнопке сообщений.
При нуле badge исчезает. Обычные диалоги и сделки остаются раздельными.
Скрытая страница не отмечает сообщения прочитанными. Presence освобождается
при уходе и истекает самостоятельно при закрытии/потере сети.

## Доставка и отсутствие дублей

- pending → sending фиксируется в PostgreSQL до Telegram HTTP.
- Блокировка строки получателя исключает параллельные sender для него.
- sent/suppressed повторно не отправляются.
- Явный отказ повторяется не более трёх попыток, через две минуты.
- Timeout/неизвестный результат или прерванная sending после рестарта → unknown.
  Такая отправка автоматически не повторяется: Telegram sendMessage не даёт
  идемпотентного ключа. Это избегает дублей, но не гарантирует доставку при
  неопределённом сетевом результате. Read/unread в Mini App остаются доступными.
- Если получатель не запускал/заблокировал бота, уведомление не может быть
  гарантированно доставлено. Ошибка сохраняется без токена и raw ответа.

## Неактивность и деньги

Последнее новое сообщение/предложение/изменение данных передачи покупателя
обновляет deadline. Ответ или предусмотренное действие продавца снимает
ожидание; последующее новое требующее ответа действие может начать новый срок.
Простое открытие приложения не является ответом. Повтор сохранённого сообщения
с тем же client_message_id не сдвигает срок и не создаёт новое уведомление.

В обычном диалоге/торге без покупки worker снимает активные автомобильные
объявления, отмечает processed; возврата и ложного текста о возврате нет.
Повторные сообщения покупателя не запускают обработанный случай заново, пока
продавец не ответит. Если снимать уже нечего, повторное Telegram-уведомление
о снятии не отправляется, событие остаётся в журнале.

В оплаченной сделке worker использует существующий auto_cancel_unanswered_deal
и _apply_deal_refund: блокировка Deal, повторная проверка статуса/срока,
полный возврат защищённых компонентов кошелька, уникальный reference транзакции,
cancelled + seller_inactive, закрытие ветки, paused объявления. Всё в одной
DB transaction. Продавцу ничего не начисляется. Финансовая история сохраняется.
Администратору не запускается повторяющаяся групповая Telegram-рассылка.

**Требует решения владельца:** автоматический возврат пока разрешён только
для paid/seller_contacted (до передачи), как в существующей финансовой модели.
transfer_in_progress/disputed/completed не возвращаются автоматически.
Срок начинается после сообщения/данных покупателя, а не по одной неоплаченной
форме. Расширять возврат на уже отмеченную передачу без согласования нельзя.

## Worker / Railway

- run_message_notification_worker запускается из FastAPI lifespan и проверяет
  очередь каждые 5 секунд. Не зависит от открытия приложения пользователем.
- Существующий run_seller_response_timeout_worker дополнен обычными диалогами.
  Интервал DEAL_NOTIFICATION_POLL_SECONDS (по умолчанию 5), срок
  SELLER_RESPONSE_TIMEOUT_SECONDS (по умолчанию 86400; сокращать только в тестах).
- После рестарта оба worker стартуют из lifespan, состояние берут из PostgreSQL.
- railway.json уже использует scripts/migrate.py на pre-deploy и /app/start.sh
  для uvicorn. Эти команды не менялись. Логи старта worker добавлены.
- Нужно включённое постоянно работающее Railway web service: фактический
  sleep/scale-to-zero и логи deployment из этой среды не проверены.

## Выполненные проверки

- Backend: полный pytest, 236 passed.
- Frontend: 76 тестов Node.
- Браузер Edge/Playwright 320/360/390/430 px: навигация, resized composer,
  точный deep link, read-through receipt, исчезновение badge, прокрутка к последнему.
- SQLite service/HTTP tests: unread 1→2→0, duplicate client request,
  присутствие/истечение lease, запрет чужого чата, read cursor, точная кнопка
  Telegram (MockTransport), восстановление outbox, ограничение retry,
  отсутствие replay unknown, ответ на 23-м часу, новый deadline,
  hide без покупки, refund один раз, сохранение истории и закрытие ветки.
- Alembic: один head и генерация PostgreSQL SQL 0034_chat_lifecycle:head.

Не выполнены: реальные два Telegram-аккаунта/iPhone/Android, применение
миграций и конкурентные транзакции на PostgreSQL, фактический Railway restart.
SQLite и подменённый Telegram API не заменяют эти staging-проверки.

## Файлы

backend/app/{models,schemas,services,routes,main}.py;
backend/app/inactivity.py; backend/app/message_notifications.py;
backend/migrations/versions/{0035_message_delivery,0036_inactivity_state}.py;
backend/tests/{test_deal_delivery_flow,test_message_delivery_inactivity}.py;
webapp/js/app.js; webapp/css/style.css; webapp/tests/navigation-browser.cjs;
docs/message-notifications-inactivity.md.
