# Review Analysis

Сервис собирает отзывы и рейтинги по Яндекс и 2ГИС, сравнивает текущий замер с предыдущим состоянием, а затем отправляет e-mail-отчет.

## Запуск только через Docker Desktop

Подготовка:
- заполнить `.env`;
- отредактировать `config/points.json`;
- убедиться, что Docker Desktop запущен.

Основные команды:

```bash
docker compose build
docker compose run --rm app python -m app.main init-db
docker compose run --rm app python -m app.main run
docker compose run --rm app python -m app.main test-email
docker compose up scheduler
docker compose run --rm tests
docker compose logs -f app
```

## Конфигурация

- `.env`:
  - инфраструктурные настройки;
  - SMTP;
  - расписание;
  - лимиты и таймауты.
- `config/points.json`:
  - список точек мониторинга;
  - ссылки на Яндекс и 2ГИС;
  - флаг активности.

## Хранение данных

Снимки мониторинга и отзывы сохраняются в SQLite-файл внутри `data/`. Для сохранения данных между перезапусками используется Docker volume.

## Развертывание на удаленном сервере

Обновление проекта на сервере выполнять через `git pull` по аналогии с рабочим процессом из репозитория [lead-generation-wine](https://github.com/kodjooo/lead-generation-wine.git). Рабочая директория проекта на сервере: `/usr/local/automation/review-analysis/`.
