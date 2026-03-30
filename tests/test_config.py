from pathlib import Path

import pytest

from app.core.config import load_settings


def test_load_settings_reads_points(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    config_path = tmp_path / "points.json"
    env_path.write_text(
        "\n".join(
            [
                f"APP_CONFIG_PATH={config_path}",
                "APP_DATABASE_PATH=data/test.sqlite3",
                "APP_REVIEW_FETCH_LIMIT=10",
                "APP_REPORT_STARS_THRESHOLD=4",
                "APP_PAGE_TIMEOUT_SECONDS=10",
                "APP_SCHEDULER_POLL_SECONDS=30",
                "APP_SCHEDULE_FREQUENCY=weekly",
                "APP_SCHEDULE_DAY=monday",
                "APP_SCHEDULE_HOUR=9",
                "APP_SCHEDULE_MINUTE=0",
                "APP_TIMEZONE=Europe/Moscow",
                "APP_LOG_LEVEL=INFO",
            ],
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        """
        [
          {
            "id": "point-1",
            "name": "Точка 1",
            "type": "Винотека",
            "address": "Краснодар",
            "yandex_url": "https://example.com/yandex",
            "twogis_url": "https://example.com/2gis",
            "is_active": true
          }
        ]
        """,
        encoding="utf-8",
    )

    settings = load_settings(env_path=env_path)

    assert settings.review_fetch_limit == 10
    assert len(settings.points) == 1
    assert settings.points[0].id == "point-1"


def test_load_settings_rejects_duplicate_ids(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    config_path = tmp_path / "points.json"
    env_path.write_text(f"APP_CONFIG_PATH={config_path}", encoding="utf-8")
    config_path.write_text(
        """
        [
          {
            "id": "point-1",
            "type": "Винотека",
            "address": "Краснодар",
            "yandex_url": "https://example.com/yandex",
            "twogis_url": "https://example.com/2gis",
            "is_active": true
          },
          {
            "id": "point-1",
            "type": "Магазин",
            "address": "Москва",
            "yandex_url": "https://example.com/yandex2",
            "twogis_url": "https://example.com/2gis2",
            "is_active": false
          }
        ]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="дублирующийся id"):
        load_settings(env_path=env_path)
