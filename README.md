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
