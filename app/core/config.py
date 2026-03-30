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
    report_stars_threshold: int
    page_timeout_seconds: int
    scheduler_poll_seconds: int
    schedule_frequency: str
    schedule_day: str
    schedule_hour: int
    schedule_minute: int
    timezone: ZoneInfo
    log_level: str
    smtp_sender: str
    smtp_recipients: list[str]
    smtp_host: str
    smtp_port: int
    smtp_use_tls: bool
    smtp_username: str
    smtp_password: str
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
    if name in env_values:
        return env_values[name]
    return os.getenv(name, default)


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
        report_stars_threshold=int(_read_env("APP_REPORT_STARS_THRESHOLD", "4", env_values)),
        page_timeout_seconds=int(_read_env("APP_PAGE_TIMEOUT_SECONDS", "45", env_values)),
        scheduler_poll_seconds=int(_read_env("APP_SCHEDULER_POLL_SECONDS", "60", env_values)),
        schedule_frequency=_read_env("APP_SCHEDULE_FREQUENCY", "weekly", env_values),
        schedule_day=_read_env("APP_SCHEDULE_DAY", "monday", env_values),
        schedule_hour=int(_read_env("APP_SCHEDULE_HOUR", "9", env_values)),
        schedule_minute=int(_read_env("APP_SCHEDULE_MINUTE", "0", env_values)),
        timezone=ZoneInfo(_read_env("APP_TIMEZONE", "Europe/Moscow", env_values)),
        log_level=_read_env("APP_LOG_LEVEL", "INFO", env_values).upper(),
        smtp_sender=_read_env("SMTP_SENDER", "", env_values),
        smtp_recipients=[
            item.strip()
            for item in _read_env("SMTP_RECIPIENTS", "", env_values).split(",")
            if item.strip()
        ],
        smtp_host=_read_env("SMTP_HOST", "", env_values),
        smtp_port=int(_read_env("SMTP_PORT", "587", env_values)),
        smtp_use_tls=_read_bool("SMTP_USE_TLS", True, env_values),
        smtp_username=_read_env("SMTP_USERNAME", "", env_values),
        smtp_password=_read_env("SMTP_PASSWORD", "", env_values),
        points=points,
    )
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    if settings.review_fetch_limit <= 0:
        raise ValueError("APP_REVIEW_FETCH_LIMIT должен быть больше нуля.")
    if settings.report_stars_threshold < 1 or settings.report_stars_threshold > 5:
        raise ValueError("APP_REPORT_STARS_THRESHOLD должен быть в диапазоне от 1 до 5.")
    if settings.page_timeout_seconds <= 0:
        raise ValueError("APP_PAGE_TIMEOUT_SECONDS должен быть больше нуля.")
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
    if settings.smtp_host and not settings.smtp_recipients:
        raise ValueError("Если SMTP_HOST указан, необходимо заполнить SMTP_RECIPIENTS.")
    if settings.smtp_host and not (settings.smtp_sender or settings.smtp_username):
        raise ValueError("Если SMTP_HOST указан, необходимо заполнить SMTP_SENDER или SMTP_USERNAME.")
    seen_ids: set[str] = set()
    for point in settings.points:
        if point.id in seen_ids:
            raise ValueError(f"Обнаружен дублирующийся id точки: {point.id}")
        seen_ids.add(point.id)
        if not point.yandex_url and not point.twogis_url:
            raise ValueError(
                f"Точка {point.id} должна содержать хотя бы одну ссылку на площадку."
            )
