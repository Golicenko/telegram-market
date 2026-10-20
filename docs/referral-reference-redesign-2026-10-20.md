# Реферальная программа — 20.10.2026

## Что изменено

Переработан существующий раздел «Ещё», а не создано новое приложение. Первые два изображения владельца — референсы всей страницы и состояния полученной награды. Третье изображение используется только как верхний баннер: ночная улица, автомобиль и логотип AUTOFLOW MARKET. Фиолетово-чёрная палитра, золотой блок процента, реальный счётчик, три карточки-билета и кнопки реализованы HTML/CSS, не вставлены скриншотом.

Из баннера удалены нарисованные аватар, пример баланса, «Информация» и «+». Поверх чистого фона работают настоящие элементы:

- Имя, фото/инициалы и баланс — существующий `/me`, сумма `wallet.available_balance`. Полное имя сохраняется в DOM/title, длинное имя переносится и не перекрывает кошелёк.
- Баланс открывает существующий кошелёк; отдельная настоящая кнопка «+» — существующее пополнение. Нет вложенных кнопок.
- «Информация» открывает существующую справку и раскрывает статью о рефералах. На остальных страницах её прежнее действие сохранено.
- Нижняя навигация и исходные иконки переиспользованы; активна «Ещё». Верхняя нативная панель Telegram не имитируется.

Изменение общей шапки ограничено `body.more-open`; профиль, Market, обучение, уникальные и админка не получают новую тему. На 320/360 px проверяются реальные границы шапки и кнопок, а не только отсутствие document overflow: `width:100%` предотвращает увеличение ширины из-за сочетания aspect-ratio/min-height.

## Награды и данные

Весь пользовательский статус — из существующего `GET /api/referrals`: `referralUrl`, `referralCount`, `commissionPercent`, `canInvite`, `milestones`. Нет демонстрационных значений в рабочем UI, localStorage-наград или новых claim-запросов.

- Основной счётчик показывает только фактическое число. Он не превращается в «X / 20» и не обрезается до 20.
- Карточки 3/10/20 и суммы берутся из backend-конфигурации ответа; существующие накопительные награды 10/15/50 AF не менялись.
- «Получено» и зелёная галочка появляются **только при `milestone.completed === true`**, который backend получает из сохранённого `ReferralReward`. Достижение числа без подтверждённой записи показывается как ожидание начисления.
- У полученной карточки размывается только внутреннее содержимое, поверх — затемнение и зелёная галочка. Карточка остаётся доступной для просмотра подробностей.
- При новом подтверждении сервера — короткая анимация; при первом открытии/перезагрузке уже полученные награды не проигрываются заново. `prefers-reduced-motion` учитывается.
- Баланс обновляется запросом `/me`, а не локальным прибавлением награды. Обновление происходит и когда пришла комиссия без изменения количества друзей.

Нажатие любой карточки/её стрелки открывает информационный dialog. Остаток — `max(0, threshold-count)`, прогресс — `min(count, threshold)/threshold`; правильные формы «друг/друга/друзей». Например, 8 из 10 означает ещё 2 друзей и 80%, 17 из 20 — ещё 3 друзей и 85%. Это не кнопка ручного получения денег.

## Окно, копирование, пересылка

Dialog: затемнение/blur, focus trap, inert background, запрет фоновой прокрутки, сохранение позиции и фокуса. Закрытие крестиком, «Понятно», backdrop, Escape и Telegram Back. При уходе со страницы/скрытии приложения снимаются scroll lock/inert и таймеры. Wheel/single-touch backdrop не оставляют отложенную прокрутку после закрытия; масштабирование двумя пальцами не запрещено.

«Скопировать» и иконка копируют **полный персональный URL**, Clipboard API + прежний selection fallback. Toast «Ссылка скопирована» и краткая индикация появляются только после успеха. Ошибка не выдаётся за успешное копирование.

«Переслать» сохраняет действующий flow фото-приглашения: защищённый `POST /api/referrals/share-message` → `preparedMessageId` → `Telegram.WebApp.shareMessage(id)`. Кнопка блокируется на время запроса, автоматических повторов POST нет, отмена выбора чата не запускает вторую отправку. Backend-подготовка сообщения, персональная inline-кнопка и настоящее фото не изменены. Сохранено действующее поведение старого клиента: предложение обновить Telegram, **без подмены фото-приглашения обычной текстовой share-ссылкой**.

Лимит приглашений управляется `canInvite`: копирование/пересылка отключаются после лимита, но существующие связи и 5% с подтверждённых платных пополнений не отключаются.

## Производительность и существующие компоненты

Переиспользованы маршрутизация `navigate/openSecondary`, шапка, `renderUser/renderBalance`, toast, справка `help-referrals`, кошелёк/пополнение, Telegram Back и контроллер `AutoFlowReferrals`.

Новые UI-части: карточка milestone с информационным dialog, фон баннера, локальная display-типографика и маленькая настоящая кнопка пополнения в шапке. Контроллер сохраняет DOM карточек между обновлениями; кэш 15 секунд, один запрос одновременно, polling 30 секунд только на активном видимом экране. На 390 px 80 переключений вкладок дали **0 дополнительных referral-запросов, слушателей, native Back handlers и ResizeObservers** в изолированном браузерном сценарии.

Баннер загружается только при первом открытии «Ещё», повторно не назначается при навигации. При ошибке остаётся обычный логотип. Фото пользователя с неизменившимся URL не переназначается при каждом обновлении. Локальные шрифты не создают внешних runtime-запросов.

## Файлы / API / конфигурация

- `webapp/index.html`, `webapp/css/style.css`: настоящая разметка/тема, dialog, шапка, mobile/reduced-motion, build fingerprint.
- `webapp/js/referrals.js`, `referrals.d.ts`: представление наград, модальное окно, копирование, существующая пересылка, кэш и cleanup.
- `webapp/js/app.js`: More-only шапка, текущие имя/баланс, отдельное пополнение, существующая информация, Back и toast.
- `webapp/images/referral-hero-20261020.jpg`: очищенный баннер 2061×763, 403088 bytes.
- `webapp/fonts/*`: локальный Oswald 700 Latin/Cyrillic (19424 bytes суммарно), `OFL-Oswald.txt` содержит лицензию. Источник — Google Fonts / google/fonts, SIL OFL 1.1.
- `webapp/tests/referral-presentation.test.cjs`, `referral-header.test.cjs`, `referral-reference-browser.cjs`: новые runtime/браузерные регрессии.
- `backend/tests/test_referral_summary_state.py`: 11 тестов реального response/сохранённого reward state, без изменения backend-реализации.
- Адаптированы существующие `referrals-browser`, `navigation-loading` и `profile-presentation` tests; в `profile-reference-browser` добавлена диагностика ошибок сети, без ослабления проверок. CI запускает новый браузерный набор.
- Этот отчёт и три скриншота на изолированных тестовых данных.

**Новых API, env/config, библиотек runtime, миграций и изменений финансовой модели нет.** Сохранены авторизация, новые-пользователи-only атрибуция, лимит 20, накопительные milestones, бонусный баланс и действующая фото-пересылка. Production не использовался и не деплоился.

## Проверки и границы

Локально: **183/183 Node tests**, **71 referral backend tests**, 9 PostgreSQL-тестов пропущены без отдельной локальной БД; Ruff нового backend-теста, `node --check`, production asset build и `git diff --check` прошли. Самостоятельные TypeScript/ESLint-команды в репозитории не настроены: не объявляются выполненными.

Новый браузерный набор прошёл **320/360/375/390/414/430 px**, плюс отдельный slow/error/retry сценарий на 390. Проверены 0/1/2/3/8/10/17/20/25, достигнутые, но ещё не подтверждённые награды, подтверждение backend, reload, blur/check, остаток/склонения/progress, все способы закрытия, backdrop-scroll, размер tap targets, полные URL, Clipboard/fallback/failure, native share callback/cancel/error/double tap, реальная шапка, пополнение/кошелёк/информация и повторная навигация. 25 — только граничный test fixture, не обход действующего backend-лимита. Старый referral browser suite прошёл 320/360/390/430/768.

Соседний профиль прошёл все 12 сочетаний user/admin × 320/360/375/390/414/430 и отдельный slow-сценарий; дополнительно четыре повторных user-414. Первоначальный локальный timeout открытия поддержки на 414 не воспроизвёлся; причина не подтверждена, для следующего сбоя добавлена сетевая диагностика, а не обход проверок.

Полный CI с PostgreSQL и регрессиями соседних разделов проверяется отдельно перед передачей PR на review; его фактический результат указан в PR. Тестовые картинки/аккаунт/ответы API существуют только в тестах, не подменяют production-данные.

**Не проверено:** физические iPhone/Android Telegram WebView, реальная доставка подготовленного сообщения в выбранный чат, production-платёж/вывод. Браузер использует настоящий frontend с mobile/touch viewport и изолированным Telegram/API transport. Настоящих списаний, возвратов, выплат и начислений на production не было.

Скриншоты `referral-reference-count-1-390.png`, `referral-reference-received-3-390.png`, `referral-reference-modal-390.png` — рендер этого приложения на явно тестовых данных. Полная матрица/JSON — CI artifact `publication-browser-evidence`, подпапка `referral-reference`.

Rollback — возврат frontend-коммита/предыдущей статической сборки; откат БД не нужен. После review владелец может проверить экран в своём Telegram; автоматического слияния/деплоя нет.

## Подготовка баннера

Использован skill `imagegen`, builtin edit по предоставленному владельцем изображению. Исходник владельца не изменялся. После генерации фон осмотрен; сохранён JPEG quality 90. Назначение — убрать нарисованные данные и вернуть за ними фон, чтобы настоящие элементы не дублировались с картинкой. Логотип, автомобиль и сцена сохранены; вся остальная страница сверстана кодом.

Фактический prompt редактирования:

> Use case: precise-object-edit. Edit target: the attached wide AutoFlow Market banner, to become a real Mini App background asset. Keep the exact wide composition and aspect ratio, night Japanese street, wet road, orange lanterns, purple sky, and silver sports car in precisely the same position. Preserve the large upper-left AUTOFLOW MARKET logo text and its white/gold styling verbatim. REMOVE ONLY these baked-in interface elements completely and seamlessly reconstruct the scene behind them: the entire upper-right purple Information button (including all text, border, info icon, chevron); the entire lower-right balance panel (including the sample 1324.74 digits, AF coin, divider and plus button); and the entire lower-left circular avatar portrait and gold ring. The result must contain absolutely NO avatar/person inset, no balance/numbers, no coins, no buttons/panels, no other interface symbols. Leave just the existing branded scene and AUTOFLOW MARKET logo, with a naturally reconstructed car/road/buildings where overlays were. Do not add objects, change logo wording, zoom/crop car, change lighting style, or redesign the original banner. This is a background asset, not a new interface screenshot.
