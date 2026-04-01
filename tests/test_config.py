from pathlib import Path

import pytest

from app.core.config import load_settings


@pytest.fixture(autouse=True)
def clear_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "APP_CONFIG_PATH",
        "APP_DATABASE_PATH",
        "APP_REVIEW_FETCH_LIMIT",
        "APP_REVIEW_SORT_ORDER",
        "APP_REPORT_STARS_THRESHOLD",
        "APP_PAGE_TIMEOUT_SECONDS",
        "APP_PLAYWRIGHT_HEADLESS",
        "APP_PLAYWRIGHT_SLOW_MO_MS",
        "APP_PLAYWRIGHT_SAVE_SCREENSHOTS",
        "APP_PLAYWRIGHT_WAIT_NETWORKIDLE",
        "APP_PLAYWRIGHT_PAUSE_BEFORE_SORT_SECONDS",
        "APP_PLAYWRIGHT_SAVE_SORT_DEBUG_STEPS",
        "APP_DELAY_BETWEEN_PLATFORMS_SECONDS",
        "APP_DELAY_BETWEEN_POINTS_SECONDS",
        "APP_DELAY_JITTER_SECONDS",
        "APP_POINT_RETRY_DELAY_SECONDS",
        "APP_POINT_MAX_ATTEMPTS",
        "APP_SHEETS_FLUSH_EACH_POINT",
        "APP_SCHEDULER_POLL_SECONDS",
        "APP_SCHEDULE_FREQUENCY",
        "APP_SCHEDULE_DAY",
        "APP_SCHEDULE_HOUR",
        "APP_SCHEDULE_MINUTE",
        "APP_TIMEZONE",
        "APP_LOG_LEVEL",
        "GOOGLE_SPREADSHEET_ID",
        "GOOGLE_SERVICE_ACCOUNT_FILE",
    ):
        monkeypatch.delenv(key, raising=False)


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
                "APP_POINT_RETRY_DELAY_SECONDS=300",
                "APP_POINT_MAX_ATTEMPTS=2",
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
    assert settings.point_retry_delay_seconds == 300
    assert settings.point_max_attempts == 2
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


def test_load_settings_rejects_non_positive_point_attempts(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    config_path = tmp_path / "points.json"
    env_path.write_text(
        "\n".join(
            [
                f"APP_CONFIG_PATH={config_path}",
                "APP_POINT_MAX_ATTEMPTS=0",
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

    with pytest.raises(ValueError, match="APP_POINT_MAX_ATTEMPTS"):
        load_settings(env_path=env_path)


def test_runtime_environment_overrides_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    default_config_path = tmp_path / "points-default.json"
    override_config_path = tmp_path / "points-override.json"
    env_path.write_text(
        "\n".join(
            [
                f"APP_CONFIG_PATH={default_config_path}",
                "APP_REVIEW_FETCH_LIMIT=10",
            ]
        ),
        encoding="utf-8",
    )
    default_config_path.write_text(
        """
        [
          {
            "id": "point-default",
            "type": "Винотека",
            "address": "Москва",
            "yandex_url": "https://example.com/yandex-default",
            "twogis_url": "https://example.com/2gis-default",
            "is_active": true
          }
        ]
        """,
        encoding="utf-8",
    )
    override_config_path.write_text(
        """
        [
          {
            "id": "point-override",
            "type": "Винотека",
            "address": "Казань",
            "yandex_url": "https://example.com/yandex-override",
            "twogis_url": "https://example.com/2gis-override",
            "is_active": true
          }
        ]
        """,
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_CONFIG_PATH", str(override_config_path))

    settings = load_settings(env_path=env_path)

    assert settings.config_path == override_config_path
    assert [point.id for point in settings.points] == ["point-override"]
