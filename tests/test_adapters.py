from pathlib import Path
from zoneinfo import ZoneInfo

from app.adapters.twogis import TwoGisAdapter
from app.adapters.yandex import YandexAdapter
from app.core.config import Settings


def build_settings() -> Settings:
    return Settings(
        config_path=Path("config/points.json"),
        database_path=Path("data/test.sqlite3"),
        review_fetch_limit=20,
        report_stars_threshold=4,
        page_timeout_seconds=10,
        scheduler_poll_seconds=60,
        schedule_frequency="weekly",
        schedule_day="monday",
        schedule_hour=9,
        schedule_minute=0,
        timezone=ZoneInfo("Europe/Moscow"),
        log_level="INFO",
        smtp_sender="",
        smtp_recipients=[],
        smtp_host="",
        smtp_port=587,
        smtp_use_tls=True,
        smtp_username="",
        smtp_password="",
        points=[],
    )


def test_yandex_adapter_parses_fixture(fixtures_dir: Path) -> None:
    adapter = YandexAdapter(build_settings())
    review_count, rating, reviews = adapter.parse_html(
        (fixtures_dir / "yandex_reviews.html").read_text(encoding="utf-8")
    )

    assert review_count == 100
    assert rating == 4.6
    assert len(reviews) == 2
    assert reviews[1]["stars"] == 3


def test_twogis_adapter_parses_fixture(fixtures_dir: Path) -> None:
    adapter = TwoGisAdapter(build_settings())
    review_count, rating, reviews = adapter.parse_html(
        (fixtures_dir / "twogis_reviews.html").read_text(encoding="utf-8")
    )

    assert review_count == 42
    assert rating == 4.3
    assert len(reviews) == 2
    assert reviews[1]["author_name"] == "Анна"
