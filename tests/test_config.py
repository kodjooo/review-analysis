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
                "APP_REVIEW_SORT_ORDER=newest",
                "APP_REPORT_STARS_THRESHOLD=4",
                "APP_PAGE_TIMEOUT_SECONDS=10",
                "APP_PLAYWRIGHT_WAIT_NETWORKIDLE=true",
                "APP_PLAYWRIGHT_PAUSE_BEFORE_SORT_SECONDS=0",
                "APP_PLAYWRIGHT_SAVE_SORT_DEBUG_STEPS=false",
                "APP_DELAY_BETWEEN_PLATFORMS_SECONDS=5",
                "APP_DELAY_BETWEEN_POINTS_SECONDS=10",
                "APP_DELAY_JITTER_SECONDS=3",
                "APP_SHEETS_FLUSH_EACH_POINT=true",
                "APP_SCHEDULER_POLL_SECONDS=30",
                "APP_SCHEDULE_FREQUENCY=weekly",
                "APP_SCHEDULE_DAY=monday",
                "APP_SCHEDULE_HOUR=9",
                "APP_SCHEDULE_MINUTE=0",
                "APP_TIMEZONE=Europe/Moscow",
                "APP_LOG_LEVEL=INFO",
                "GOOGLE_SPREADSHEET_ID=",
                "GOOGLE_SERVICE_ACCOUNT_FILE=",
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
    assert settings.review_sort_order == "newest"
    assert settings.playwright_wait_networkidle is True
    assert settings.playwright_pause_before_sort_seconds == 0
    assert settings.playwright_save_sort_debug_steps is False
    assert settings.delay_between_platforms_seconds == 5
    assert settings.delay_between_points_seconds == 10
    assert settings.delay_jitter_seconds == 3
    assert settings.sheets_flush_each_point is True
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


def test_load_settings_rejects_unknown_review_sort_order(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    config_path = tmp_path / "points.json"
    env_path.write_text(
        "\n".join(
            [
                f"APP_CONFIG_PATH={config_path}",
                "APP_REVIEW_SORT_ORDER=random",
            ]
        ),
        encoding="utf-8",
    )
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
          }
        ]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="APP_REVIEW_SORT_ORDER"):
        load_settings(env_path=env_path)


def test_load_settings_rejects_negative_delays(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    config_path = tmp_path / "points.json"
    env_path.write_text(
        "\n".join(
            [
                f"APP_CONFIG_PATH={config_path}",
                "APP_DELAY_BETWEEN_POINTS_SECONDS=-1",
            ]
        ),
        encoding="utf-8",
    )
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
          }
        ]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="не может быть отрицательным"):
        load_settings(env_path=env_path)
