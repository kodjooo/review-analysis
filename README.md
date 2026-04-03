# Review Analysis

Сервис собирает отзывы и рейтинги по Яндексу и 2GIS, сравнивает текущий снимок с предыдущим состоянием и выгружает результат в Google Sheets.

## Что делает сервис

- читает точки мониторинга из `config/points.json`
- собирает агрегаты и последние отзывы по `yandex` и `2gis`
- сравнивает текущий снимок с предыдущим снимком в SQLite
- определяет новые отзывы
- выделяет новые отзывы с оценкой ниже или равной порогу
- выгружает отчет в Google Sheets

## Конфигурация

Перед запуском нужно заполнить:

- `.env`
- `config/points.json`
- `secure/google-credentials.json`

Что важно в `.env`:

- `GOOGLE_SPREADSHEET_ID` — ID Google-таблицы для выгрузки
- `GOOGLE_SERVICE_ACCOUNT_FILE` — путь к JSON-ключу сервисного аккаунта
- `APP_REVIEW_FETCH_LIMIT` — сколько последних отзывов анализировать
- `APP_REPORT_STARS_THRESHOLD` — порог плохих отзывов
- `APP_REVIEW_SORT_ORDER` — порядок анализа отзывов, обычно `newest`
- `APP_PLAYWRIGHT_HEADLESS` — запускать Playwright без окна или с окном
- `APP_PROXY_URLS` — список proxy через запятую для Playwright, если нужно обходить антибот через разные IP
- `APP_PROXY_MAX_ATTEMPTS` — сколько разных proxy подряд пробовать для одной загрузки страницы

`summary` и `low_rated_new_reviews` теперь обновляются через merge/upsert даже при обычном `run`, поэтому ручной повторный запуск не должен затирать уже собранные успешные точки.

Google-таблица должна быть расшарена на сервисный аккаунт с правами редактора.

## Локальный запуск через Docker

Проект запускается через Docker.

Основные команды:

```bash
docker compose build
docker compose up -d app
docker compose exec app python -m app.main init-db
docker compose exec app python -m app.main run
docker compose exec app python -m app.main test-output
docker compose up -d scheduler
docker compose run --rm tests
```

`app` держится как постоянный служебный контейнер, чтобы ручные команды выполнялись через `docker compose exec` и не создавали временные `review-analysis-app-run-*` контейнеры.

## Visual Playwright

Для диагностического запуска можно включить видимый режим Playwright в `.env`:

```env
APP_PLAYWRIGHT_HEADLESS=false
APP_PLAYWRIGHT_SLOW_MO_MS=300
APP_PLAYWRIGHT_SAVE_SCREENSHOTS=true
```

После этого артефакты диагностики сохраняются в `debug/` и `browser-state/`.

## Хранение данных

- история снимков и отзывов хранится в SQLite
- база лежит в `data/`
- между перезапусками контейнеров данные сохраняются через Docker volume

## Разворачивание на удаленном сервере

Рабочая директория проекта на сервере:

```bash
/usr/local/automation/review-analysis/
```

Подключение к серверу:

```bash
ssh codex@<SERVER_HOST>
```

Первичное разворачивание из git-репозитория:

```bash
sudo mkdir -p /usr/local/automation
sudo chown -R codex:codex /usr/local/automation
cd /usr/local/automation
git clone https://github.com/kodjooo/review-analysis.git
cd /usr/local/automation/review-analysis
```

Подготовка сервера:

```bash
cp .env.example .env
mkdir -p secure
```

Дальше нужно:

- заполнить `.env`
- положить JSON-ключ сервисного аккаунта в `secure/google-credentials.json`
- проверить `config/points.json`

Сборка и первый запуск на сервере:

```bash
cd /usr/local/automation/review-analysis
docker compose build
docker compose up -d app
docker compose exec app python -m app.main init-db
docker compose exec app python -m app.main run
```

Запуск по расписанию:

```bash
cd /usr/local/automation/review-analysis
docker compose up -d scheduler
```

Проверка статуса:

```bash
cd /usr/local/automation/review-analysis
docker compose ps
docker compose logs -f scheduler
docker compose logs -f app
```

## Обновление проекта на сервере

Обновлять проект нужно через `git pull` по тому же рабочему процессу, который используется для репозитория [lead-generation-wine](https://github.com/kodjooo/lead-generation-wine.git).

Типовой сценарий обновления:

```bash
ssh codex@<SERVER_HOST>
cd /usr/local/automation/review-analysis
git pull origin master
docker compose build
docker compose up -d app
docker compose run --rm tests
docker compose exec app python -m app.main run
docker compose up -d scheduler
```

Если используется другая основная ветка, вместо `master` нужно подставить актуальную ветку репозитория.

## Примечания

- `.env` не нужно отправлять в git
- для `2gis` в отчете показывается имя площадки `2gis`, хотя внутренний enum в коде остается `twogis`
- плохими считаются только новые отзывы с оценкой `<= APP_REPORT_STARS_THRESHOLD`

## 2026-04-01: Повторный проход и пропущенные точки

- В `summary` добавлена колонка `Последнее обновление` с временем последнего успешного сбора по площадке.
- В отчет добавлен отдельный лист `skipped_points_last_run` с точками, которые были пропущены в последнем проходе после всех retry-попыток.
- Лист `skipped_points_last_run` очищается в начале каждого нового запуска и содержит только ошибки текущего/последнего прохода.
- Для повторного прохода только по пропущенным точкам добавлена команда:
 - Для повторного прохода только по пропущенным точкам добавлена команда:

```bash
docker compose exec app python -m app.main rerun-failed
```

- Команда читает ID точек из листа `skipped_points_last_run` и запускает повторный сбор только для этих активных точек из текущего `config/points.json`.
- В режиме `schedule` после основного планового запуска сервис автоматически запускает `rerun-failed` через 1 час и затем повторяет его каждый час, пока лист `skipped_points_last_run` не опустеет для этого прохода.

## 2026-04-02: Безопасный rerun-failed и retry Google Sheets

- Повторный проход `rerun-failed` больше не очищает основной лист `summary` и не затирает успешные результаты прошлого основного прогона.
- В режиме `rerun-failed` сервис обновляет только строки тех точек, которые действительно повторно собирались, а лист `skipped_points_last_run` пересобирает по итогам именно этого догона.
- Лист `run_info` при `rerun-failed` не переписывается, поэтому основной итог прохода остается видимым до завершения следующего полного запуска.
- Для запросов к Google Sheets API добавлены повторные попытки и пауза между ними, чтобы кратковременные сетевые таймауты не роняли выгрузку с первой ошибки.
- Планировщик `schedule` теперь оборачивает вызовы основного запуска, `rerun-failed` и чтение `skipped_points_last_run` в безопасные обработчики ошибок, чтобы единичный таймаут Google Sheets не останавливал весь `scheduler`.

## 2026-04-02: Валидация точки, upsert и защита от антибота

- Точка попадает в итоговый отчет только после полной успешной сборки обеих площадок и прохождения point-level validation gate.
- Для ошибочных или неконсистентных точек сервис не сохраняет snapshot в SQLite и не публикует строку в `summary`, а переводит точку в retry или `skipped_points_last_run`.
- Политика повторных попыток теперь зависит от типа ошибки: для антибота, сетевых сбоев, ошибок парсинга и прочих сбоев используются разные лимиты попыток и разные паузы.
- Для Playwright добавлена ротация proxy: при сбое загрузки или антибот-странице сервис повторяет попытку через следующий proxy из `APP_PROXY_URLS`.
- Лист `summary` продолжает обновляться только через merge/upsert по ключу точки и площадки, без полного clear при `rerun-failed`.

## 2026-04-02: Возврат к неблокирующему обходу точек

- В рамках одного прохода сервис больше не делает блокирующие retry по отдельной точке и не останавливает обход остальных точек.
- Для каждой точки сервис по-прежнему пытается собрать обе площадки, но при любой ошибке не коммитит точку в `summary`, а переносит ее в `skipped_points_last_run`.
- Повторный сбор проблемных точек снова выполняется только через `rerun-failed` по расписанию, с часовым или иным настроенным интервалом `APP_FAILED_RERUN_INTERVAL_SECONDS`.

## 2026-04-03: Proxy rotation and scheduler-driven reruns

- `APP_PROXY_MAX_ATTEMPTS=4` now means: up to 3 configured proxy and then one direct server IP attempt.
- Playwright rotates both proxy order and browser profile after every successful and failed page load so repeated requests do not reuse the same network/fingerprint sequence.
- After a restart `scheduler` now checks `skipped_points_last_run` immediately and schedules `rerun-failed` after `APP_FAILED_RERUN_INTERVAL_SECONDS` even if the previous main run finished earlier.
- `summary` is still updated through merge/upsert during reruns, so successful rows are preserved while skipped points are being retried.
