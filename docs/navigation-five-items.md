# Нижняя навигация — исправление 16.09.2026

Ветка: `agent/navigation-five-items`, поверх текущих изменений проекта.
Область правки: только нижняя панель, четыре предоставленных PNG и окно «Ещё».
Backend, платежи, сделки, обучение и профиль не менялись. Миграций нет.

## Результат

- Фиксированный порядок: Уникальные / Обучение / Market / Профиль / Ещё.
- Пять одинаковых колонок. Центр диска Market совпадает с центром viewport.
- Исходная высота панели 68px + safe area, круг Market 64px, прежние цвета и фон.
- Видимая часть обычных иконок около 30px. PNG скопированы побайтно,
  без обрезки, перерисовки или деформации. Разные прозрачные поля компенсируются CSS.
- Счётчики «Обучение» и «Уникальные» сохранены; контейнеры не обрезают badge.
- «Ещё» открывает native dialog с затемнением и blur 8px. Текущий экран,
  активная вкладка, scroll и navigation stack не меняются.
- Закрытие: крестик, кнопка, фон вне карточки, Escape, Telegram BackButton.
  Двойной Back не проваливается на предыдущий экран.
- Канал: `https://t.me/CarParking_AF`, через `openTelegramLink`, а при отсутствии
  или ошибке Telegram API — обычная ссылка. Старый `?view=more` открывает это же окно.

## Изображения

| Раздел | Переданный файл | Файл в проекте |
|---|---|---|
| Уникальные | IMG_unique.PNG | webapp/images/nav-unique.png |
| Обучение | IMG_tuturial.PNG | webapp/images/nav-training.png |
| Профиль | profile.PNG | webapp/images/nav-profile.png |
| Ещё | more.PNG | webapp/images/nav-more.png |
| Market | Новое изображение не требуется | Сохранена существующая звезда |

По окончательному уточнению пользователя Market оставлен прежним: пятый PNG не нужен.
Совпадение SHA-256 четырёх исходников и копий проверено.

## Изменённые файлы

- `webapp/index.html`: пять пунктов и dialog.
- `webapp/css/style.css`: равные колонки, центрирование, нормализация иконок, overlay.
- `webapp/js/app.js`: открытие/закрытие «Ещё», BackButton, ссылка в канал.
- Идентификатор сборки в HTML обновлён существующим build script;
  `webapp/build-info.json` генерируется как build artifact и не хранится в Git.
- Четыре PNG из таблицы выше.
- `webapp/tests/navigation-five-items-browser.cjs`: новая браузерная проверка.
- `webapp/tests/profile-simple-browser.cjs`, `webapp/tests/training.test.cjs`:
  актуализированы ожидания числа пунктов и имён изображений.

## Проверки

- 82 frontend unit tests — прошли.
- 282 backend tests — прошли (953 предупреждения о deprecated asyncio API,
  не связанные с этой правкой).
- Новый browser test на Edge/Chromium: 320, 360, 390, 430px.
  Проверены равные ячейки, центр Market с допуском 0.1px, touch targets >=44px,
  safe area 34px, высота панели 102px, отсутствие переполнения и переноса подписей,
  загрузка PNG, пропорции, четыре основные вкладки, все способы закрытия overlay,
  повторное открытие, native Telegram link, fallback без API/с ошибкой API,
  сохранение текущего экрана и старый deep link.
- Profile browser regression: оба типа роли на тех же четырёх ширинах.
- Снимки 390px визуально проверены: `navigation-five-items-390.png`,
  `navigation-more-overlay-390.png` в этой папке.

Все browser tests используют изолированные API/Telegram fixtures. Это **не**
тесты на физических iPhone/Android в Telegram и не проверка production Railway.
Эти проверки остаются для реального устройства после deployment.

Запуск: `node --test webapp/tests/*.test.cjs`,
`node webapp/tests/navigation-five-items-browser.cjs`,
`node webapp/tests/profile-simple-browser.cjs`,
из backend — `python -m pytest -q`.
