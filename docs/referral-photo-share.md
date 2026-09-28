# Приглашение: фото + подпись + кнопка

Узкая доработка существующей пересылки, отдельная от финансового PR #58.
Реферальные связи, лимиты, награды, начисления, модели БД и layout страницы не менялись.

## Отправка

`Переслать → POST /api/referrals/share-message → savePreparedInlineMessage → Telegram.WebApp.shareMessage(id)`.

В существующий `result` теперь передаётся `InlineQueryResultPhoto`: `type=photo`,
`photo_url`, `thumbnail_url`, `caption` и `reply_markup.inline_keyboard`.
`input_message_content` намеренно отсутствует: иначе Telegram заменяет фото текстом.
Prepared message остаётся привязанным к Telegram ID авторизованного отправителя.
Чат выбирает сам пользователь; backend не отправляет приглашения его контактам.

Caption — настоящее first_name + «приглашает тебя в AutoFlow Market 🚗», затем:

> Зарабатывай вместе со мной в AutoFlow Market.
>
> Покупай и продавай машины из Car Parking 1 и Car Parking 2, приглашай друзей и получай бонусы.

Без имени: «Тебя приглашают в AutoFlow Market 🚗». Caption — plain text, без HTML/Markdown
интерпретации имени. Аномально длинные импортированные имена ограничены, чтобы не превысить
лимит подписи. В inline keyboard ровно одна настоящая URL-кнопка «Перейти в маркет».
Ссылка вычисляется существующим backend из referralCode текущего пользователя и реального
bot launch configuration, не из JSON клиента.

## Присланное изображение

- Источник: `photo_2026-09-28_23-50-55.jpg` владельца.
- В репозитории: `webapp/images/referral-share.ffadf191b10c.jpg`.
- JPEG, 960×1280, 129764 байта. Никаких crop/resize/перерисовки или перекодирования.
- SHA-256: `ffadf191b10cd7e3bb87a26a89c07e5ff07ccac843e5230021f342af7d17eb4c`.
- Фото включается существующим Docker `COPY webapp`, раздаётся существующим StaticFiles.
  Это не временный upload, frontend state или Railway volume; файл остаётся в deployment image.
- Публичный HTTPS URL строится из существующего `PUBLIC_BASE_URL`, либо `RAILWAY_PUBLIC_DOMAIN`.
  Новый env не нужен. Домен должен действительно раздавать этот файл без авторизации.
  При отсутствии конфигурации/файла возвращается понятная 503, а не ложное успешное сообщение без фото.

Выбран прямой публичный JPEG URL, официально поддерживаемый Telegram. Он не требует
предварительной отправки фото владельцу/пользователю ради file_id. Повторный клик получает
сохранённый в `ReferralShare` prepared ID, пока он действителен, а не повторно загружает файл.
Telegram получает фото по URL при подготовке нового сообщения; приложение не посылает
multipart-файл при каждом клике.

При ручной замене: добавить новый JPEG с новым hash в имени, обновить `REFERRAL_PHOTO_PATH`
и контрольный hash/размер в тесте. Адрес фото и тип сообщения входят в content_hash кэша:
старое текстовое или старое фото-приглашение не переиспользуется. Уже пересланные сообщения
не редактируются и не удаляются. Существующие cooldown, лимит приглашений и защита double tap сохранены.

## Ограничения Telegram

[InlineQueryResultPhoto](https://core.telegram.org/bots/api#inlinequeryresultphoto)
поддерживает JPEG до 5 MB и подпись до 1024 символов; приложенный файл проходит эти ограничения.
[savePreparedInlineMessage](https://core.telegram.org/bots/api#savepreparedinlinemessage)
принимает этот InlineQueryResult и возвращает user-bound prepared ID.

В старом клиенте без `shareMessage` нельзя передать фото и inline keyboard через `t.me/share/url`.
Чтобы не подменять запрошенное сообщение обычной ссылкой, теперь показывается:
«Обновите Telegram, чтобы переслать приглашение с фото». Сам экран, кнопка копирования
реферальной ссылки и оформление не изменены. Для современного клиента используется прежний native flow.

## Проверки

- 352 backend tests passed, включая имеющийся PostgreSQL concurrency test на локальной изолированной БД.
- 18 новых проверок: точные байты JPEG/формат/размер; реальный HTTP GET публичного изображения
  без Telegram auth и ETag; подпись с именем/без имени/длинным именем; допустимый HTTPS config;
  отсутствие файла; разные кнопки двух отправителей; смена фото/старого article-кэша;
  повторное открытие DB сохраняет prepared ID.
- Обновлён существующий HTTP-тест: spoof user_id/referralCode не влияет на отправителя/кнопку,
  payload содержит фото + caption, без замены через input_message_content.
- 85 frontend unit/source tests passed. Browser harness: 320/360/390/430/768 px,
  native success/cancel, double tap, ошибка API, copy, старый SDK, лимит, reload, retry.
- TypeScript/checkJs, Ruff затронутых модулей/тестов, compileall, production build — успешно.
- Новый frontend build `af-493ebce08c06`; в index.html обновлены только build/version-ссылки.

Это не live Telegram E2E. Telegram transport и SDK изолированы тестовыми fixtures;
в рабочем коде подмен нет. Реальная доставка картинки двум Telegram-аккаунтам и выбор чата
на iPhone/Android не проверены без доступа к устройствам/аккаунтам.

Перед выпуском на staging: открыть полный публичный URL фото без входа; A нажимает «Переслать»,
выбирает B; B получает именно фото, новый caption и одну кнопку; по кнопке открывается
персональная referral URL A. Повторить с другим отправителем и проверить отмену share dialog.

## Изменённые файлы

- `backend/app/referral_routes.py` — photo payload, публичный asset URL, версия кэша.
- `backend/app/referrals.py` — только invitation_text, экономика не менялась.
- `backend/tests/test_referrals.py` — существующие тесты photo payload.
- `backend/tests/test_referral_photo_share.py` — новые проверки.
- `webapp/images/referral-share.ffadf191b10c.jpg` — исходное фото.
- `webapp/js/referrals.js` — честное сообщение старому клиенту вместо пересылки без фото.
- `webapp/tests/referrals-browser.cjs` — native success/unsupported client.
- `webapp/index.html` — сгенерированные ссылки новой сборки, без layout изменений.
- Этот отчёт. Миграции не нужны.
