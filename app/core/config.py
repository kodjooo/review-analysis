from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.models import MonitoringPoint


@dataclass(slots=True)
class Settings:
    config_path: Path
    database_path: Path
    review_fetch_limit: int
    review_sort_order: str
    report_stars_threshold: int
    page_timeout_seconds: int
    playwright_headless: bool
    playwright_slow_mo_ms: int
    playwright_save_screenshots: bool
    playwright_wait_networkidle: bool
    playwright_pause_before_sort_seconds: int
    playwright_save_sort_debug_steps: bool
    delay_between_platforms_seconds: int
    delay_between_points_seconds: int
    delay_jitter_seconds: int
    point_retry_delay_seconds: int
    point_max_attempts: int
    failed_rerun_interval_seconds: int
    sheets_flush_each_point: bool
    scheduler_poll_seconds: int
    schedule_frequency: str
    schedule_day: str
    schedule_hour: int
    schedule_minute: int
    timezone: ZoneInfo
    log_level: str
    google_spreadsheet_id: str
    google_service_account_file: Path | None
    points: list[MonitoringPoint]


def parse_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _read_env(name: str, default: str, env_values: dict[str, str]) -> str:
    runtime_value = os.getenv(name)
    if runtime_value is not None:
        return runtime_value
    if name in env_values:
        return env_values[name]
    return default


def _read_bool(name: str, default: bool, env_values: dict[str, str]) -> bool:
    value = _read_env(name, "true" if default else "false", env_values)
    return value.lower() in {"1", "true", "yes", "on"}


def _load_points(config_path: Path) -> list[MonitoringPoint]:
    if not config_path.exists():
        raise ValueError(f"Файл конфигурации точек не найден: {config_path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Конфигурация точек должна быть массивом объектов.")

    points: list[MonitoringPoint] = []
    for item in data:
        missing = [
            key
            for key in ("id", "type", "address", "yandex_url", "twogis_url", "is_active")
            if key not in item
        ]
        if missing:
            raise ValueError(
                f"В точке мониторинга отсутствуют обязательные поля: {', '.join(missing)}"
            )
        points.append(
            MonitoringPoint(
                id=str(item["id"]),
                name=item.get("name"),
                type=str(item["type"]),
                address=str(item["address"]),
                yandex_url=str(item["yandex_url"]),
                twogis_url=str(item["twogis_url"]),
                is_active=bool(item["is_active"]),
            )
        )
    return points


def load_settings(env_path: Path, config_path: Path | None = None) -> Settings:
    env_values = parse_env_file(env_path)
    resolved_config = Path(
        _read_env("APP_CONFIG_PATH", str(config_path or "config/points.json"), env_values)
    )
    points = _load_points(resolved_config)

    settings = Settings(
        config_path=resolved_config,
        database_path=Path(_read_env("APP_DATABASE_PATH", "data/review_analysis.sqlite3", env_values)),
        review_fetch_limit=int(_read_env("APP_REVIEW_FETCH_LIMIT", "20", env_values)),
        review_sort_order=_read_env("APP_REVIEW_SORT_ORDER", "newest", env_values).lower(),
        report_stars_threshold=int(_read_env("APP_REPORT_STARS_THRESHOLD", "4", env_values)),
        page_timeout_seconds=int(_read_env("APP_PAGE_TIMEOUT_SECONDS", "45", env_values)),
        playwright_headless=_read_bool("APP_PLAYWRIGHT_HEADLESS", True, env_values),
        playwright_slow_mo_ms=int(_read_env("APP_PLAYWRIGHT_SLOW_MO_MS", "0", env_values)),
        playwright_save_screenshots=_read_bool(
            "APP_PLAYWRIGHT_SAVE_SCREENSHOTS", False, env_values
        ),
        playwright_wait_networkidle=_read_bool(
            "APP_PLAYWRIGHT_WAIT_NETWORKIDLE", True, env_values
        ),
        playwright_pause_before_sort_seconds=int(
            _read_env("APP_PLAYWRIGHT_PAUSE_BEFORE_SORT_SECONDS", "0", env_values)
        ),
        playwright_save_sort_debug_steps=_read_bool(
            "APP_PLAYWRIGHT_SAVE_SORT_DEBUG_STEPS", False, env_values
        ),
        delay_between_platforms_seconds=int(
            _read_env("APP_DELAY_BETWEEN_PLATFORMS_SECONDS", "0", env_values)
        ),
        delay_between_points_seconds=int(
            _read_env("APP_DELAY_BETWEEN_POINTS_SECONDS", "0", env_values)
        ),
        delay_jitter_seconds=int(_read_env("APP_DELAY_JITTER_SECONDS", "0", env_values)),
        point_retry_delay_seconds=int(
            _read_env("APP_POINT_RETRY_DELAY_SECONDS", "300", env_values)
        ),
        point_max_attempts=int(_read_env("APP_POINT_MAX_ATTEMPTS", "2", env_values)),
        failed_rerun_interval_seconds=int(
            _read_env("APP_FAILED_RERUN_INTERVAL_SECONDS", "3600", env_values)
        ),
        sheets_flush_each_point=_read_bool("APP_SHEETS_FLUSH_EACH_POINT", False, env_values),
        scheduler_poll_seconds=int(_read_env("APP_SCHEDULER_POLL_SECONDS", "60", env_values)),
        schedule_frequency=_read_env("APP_SCHEDULE_FREQUENCY", "weekly", env_values),
        schedule_day=_read_env("APP_SCHEDULE_DAY", "monday", env_values),
        schedule_hour=int(_read_env("APP_SCHEDULE_HOUR", "9", env_values)),
        schedule_minute=int(_read_env("APP_SCHEDULE_MINUTE", "0", env_values)),
        timezone=ZoneInfo(_read_env("APP_TIMEZONE", "Europe/Moscow", env_values)),
        log_level=_read_env("APP_LOG_LEVEL", "INFO", env_values).upper(),
        google_spreadsheet_id=_read_env("GOOGLE_SPREADSHEET_ID", "", env_values),
        google_service_account_file=_path_or_none(
            _read_env("GOOGLE_SERVICE_ACCOUNT_FILE", "", env_values)
        ),
        points=points,
    )
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    if settings.review_fetch_limit <= 0:
        raise ValueError("APP_REVIEW_FETCH_LIMIT должен быть больше нуля.")
    if settings.review_sort_order not in {"newest", "oldest"}:
        raise ValueError("APP_REVIEW_SORT_ORDER должен быть newest или oldest.")
    if settings.report_stars_threshold < 1 or settings.report_stars_threshold > 5:
        raise ValueError("APP_REPORT_STARS_THRESHOLD должен быть в диапазоне от 1 до 5.")
    if settings.page_timeout_seconds <= 0:
        raise ValueError("APP_PAGE_TIMEOUT_SECONDS должен быть больше нуля.")
    if settings.playwright_slow_mo_ms < 0:
        raise ValueError("APP_PLAYWRIGHT_SLOW_MO_MS не может быть отрицательным.")
    if settings.playwright_pause_before_sort_seconds < 0:
        raise ValueError("APP_PLAYWRIGHT_PAUSE_BEFORE_SORT_SECONDS не может быть отрицательным.")
    if settings.delay_between_platforms_seconds < 0:
        raise ValueError("APP_DELAY_BETWEEN_PLATFORMS_SECONDS не может быть отрицательным.")
    if settings.delay_between_points_seconds < 0:
        raise ValueError("APP_DELAY_BETWEEN_POINTS_SECONDS не может быть отрицательным.")
    if settings.delay_jitter_seconds < 0:
        raise ValueError("APP_DELAY_JITTER_SECONDS не может быть отрицательным.")
    if settings.point_retry_delay_seconds < 0:
        raise ValueError("APP_POINT_RETRY_DELAY_SECONDS не может быть отрицательным.")
    if settings.point_max_attempts <= 0:
        raise ValueError("APP_POINT_MAX_ATTEMPTS должен быть больше нуля.")
    if settings.failed_rerun_interval_seconds <= 0:
        raise ValueError("APP_FAILED_RERUN_INTERVAL_SECONDS должен быть больше нуля.")
    if settings.scheduler_poll_seconds <= 0:
        raise ValueError("APP_SCHEDULER_POLL_SECONDS должен быть больше нуля.")
    if settings.schedule_frequency not in {"weekly", "daily"}:
        raise ValueError("APP_SCHEDULE_FREQUENCY должен быть weekly или daily.")
    if settings.schedule_day.lower() not in {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }:
        raise ValueError("APP_SCHEDULE_DAY указан неверно.")
    if settings.schedule_hour < 0 or settings.schedule_hour > 23:
        raise ValueError("APP_SCHEDULE_HOUR должен быть в диапазоне от 0 до 23.")
    if settings.schedule_minute < 0 or settings.schedule_minute > 59:
        raise ValueError("APP_SCHEDULE_MINUTE должен быть в диапазоне от 0 до 59.")
    if settings.google_spreadsheet_id and settings.google_service_account_file is None:
        raise ValueError(
            "Если GOOGLE_SPREADSHEET_ID указан, необходимо заполнить GOOGLE_SERVICE_ACCOUNT_FILE."
        )
    if settings.google_service_account_file and not settings.google_service_account_file.exists():
        raise ValueError("Файл сервисного аккаунта Google не найден.")

    seen_ids: set[str] = set()
    for point in settings.points:
        if point.id in seen_ids:
            raise ValueError(f"Обнаружен дублирующийся id точки: {point.id}")
        seen_ids.add(point.id)
        if not point.yandex_url and not point.twogis_url:
            raise ValueError(
                f"Точка {point.id} должна содержать хотя бы одну ссылку на площадку."
            )


def _path_or_none(value: str) -> Path | None:
    normalized = value.strip()
    return Path(normalized) if normalized else None
