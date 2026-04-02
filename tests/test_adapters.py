from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.adapters.twogis import TwoGisAdapter
from app.adapters.yandex import YandexAdapter
from app.core.config import Settings
from app.core.models import MonitoringPoint


def build_settings() -> Settings:
    return Settings(
        config_path=Path("config/points.json"),
        database_path=Path("data/test.sqlite3"),
        review_fetch_limit=20,
        review_sort_order="newest",
        report_stars_threshold=4,
        page_timeout_seconds=10,
        playwright_headless=True,
        playwright_slow_mo_ms=0,
        playwright_save_screenshots=False,
        playwright_wait_networkidle=True,
        playwright_pause_before_sort_seconds=0,
        playwright_save_sort_debug_steps=False,
        delay_between_platforms_seconds=5,
        delay_between_points_seconds=10,
        delay_jitter_seconds=3,
        point_retry_delay_seconds=300,
        point_max_attempts=2,
        failed_rerun_interval_seconds=3600,
        retry_antibot_delay_seconds=300,
        retry_network_delay_seconds=120,
        retry_parse_delay_seconds=0,
        retry_unknown_delay_seconds=180,
        retry_antibot_max_attempts=2,
        retry_network_max_attempts=3,
        retry_parse_max_attempts=1,
        retry_unknown_max_attempts=2,
        proxy_urls=[],
        proxy_max_attempts=3,
        sheets_api_retry_delay_seconds=10,
        sheets_api_max_attempts=3,
        sheets_flush_each_point=False,
        scheduler_poll_seconds=60,
        schedule_frequency="weekly",
        schedule_day="monday",
        schedule_hour=9,
        schedule_minute=0,
        timezone=ZoneInfo("Europe/Moscow"),
        log_level="INFO",
        google_spreadsheet_id="",
        google_service_account_file=None,
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


def test_yandex_adapter_uses_embedded_state_fallback() -> None:
    adapter = YandexAdapter(build_settings())
    html = """
    <html>
      <body>
        <script>
          window.__STATE__ = {
            "ratingData":{"ratingCount":54,"ratingValue":5,"reviewCount":42},
            "reviews":[
              {
                "reviewId":"rev-1",
                "author":{"name":"Мария"},
                "text":"Очень понравилось",
                "rating":5,
                "updatedTime":"2026-03-31T09:00:00.000Z"
              }
            ],
            "params":{"count":42}
          };
        </script>
      </body>
    </html>
    """

    review_count, rating, reviews = adapter.parse_html(html)

    assert review_count == 42
    assert rating == 5.0
    assert len(reviews) == 1
    assert reviews[0]["author_name"] == "Мария"


def test_yandex_adapter_sorts_embedded_reviews_by_newest() -> None:
    adapter = YandexAdapter(build_settings())
    html = """
    <html>
      <body>
        <script>
          window.__STATE__ = {
            "ratingData":{"ratingCount":54,"ratingValue":5,"reviewCount":42},
            "reviews":[
              {
                "reviewId":"rev-old",
                "author":{"name":"Старый"},
                "text":"Старый отзыв",
                "rating":5,
                "updatedTime":"2026-03-01T09:00:00.000Z"
              },
              {
                "reviewId":"rev-new",
                "author":{"name":"Новый"},
                "text":"Новый отзыв",
                "rating":5,
                "updatedTime":"2026-03-31T09:00:00.000Z"
              }
            ],
            "params":{"count":42}
          };
        </script>
      </body>
    </html>
    """

    review_count, rating, reviews = adapter.parse_html(html)

    assert review_count == 42
    assert rating == 5.0
    assert reviews[0]["external_id"] == "rev-new"
    assert reviews[1]["external_id"] == "rev-old"


def test_yandex_extract_float_ignores_review_count_suffix() -> None:
    node = BeautifulSoup("<div>5,0 54 оценки</div>", "html.parser").div

    assert node is not None
    assert YandexAdapter._extract_float(node) == 5.0


def test_yandex_prefers_review_count_over_rating_count() -> None:
    adapter = YandexAdapter(build_settings())
    html = """
    <html>
      <body>
        <div class="business-summary-rating-badge-view__rating-count">54 оценки</div>
        <div class="business-reviews-card-view__header">
          <h2 class="card-section-header__title_wide">42 отзыва</h2>
        </div>
        <div class="business-rating-badge-view__rating-text">5,0 54 оценки</div>
        <script>
          window.__STATE__ = {
            "ratingData":{"ratingCount":54,"ratingValue":5,"reviewCount":42},
            "reviews":[
              {
                "reviewId":"rev-1",
                "author":{"name":"Мария"},
                "text":"Очень понравилось",
                "rating":5,
                "updatedTime":"2026-03-31T09:00:00.000Z"
              }
            ],
            "params":{"count":42}
          };
        </script>
      </body>
    </html>
    """

    review_count, rating, reviews = adapter.parse_html(html)

    assert review_count == 42
    assert rating == 5.0
    assert len(reviews) == 1


def test_yandex_prefers_embedded_review_count_over_photo_tab_count() -> None:
    adapter = YandexAdapter(build_settings())
    html = """
    <html>
      <body>
        <div class="business-tab_type_photo"><span class="business-tab__count">34</span></div>
        <div class="business-reviews-card-view__header">
          <h2 class="card-section-header__title_wide">34</h2>
        </div>
        <script>
          window.__STATE__ = {
            "ratingData":{"ratingCount":54,"ratingValue":5,"reviewCount":42},
            "reviews":[
              {
                "reviewId":"rev-1",
                "author":{"name":"Мария"},
                "text":"Очень понравилось",
                "rating":5,
                "updatedTime":"2026-03-31T09:00:00.000Z"
              }
            ],
            "params":{"offset":0,"limit":50,"count":42,"loadedReviewsCount":42}
          };
        </script>
      </body>
    </html>
    """

    review_count, rating, reviews = adapter.parse_html(html)

    assert review_count == 42
    assert rating == 5.0
    assert len(reviews) == 1


def test_twogis_adapter_parses_fixture(fixtures_dir: Path) -> None:
    adapter = TwoGisAdapter(build_settings())
    review_count, rating, reviews = adapter.parse_html(
        (fixtures_dir / "twogis_reviews.html").read_text(encoding="utf-8")
    )

    assert review_count == 42
    assert rating == 4.3
    assert len(reviews) == 2
    assert reviews[1]["author_name"] == "Анна"


def test_twogis_adapter_uses_api_reviews_by_default() -> None:
    adapter = TwoGisAdapter(build_settings())
    adapter._fetch_reviews_from_api = lambda html, source_url: [  # type: ignore[method-assign]
        {
            "external_id": "218320611",
            "author_name": "Ирина",
            "published_at": "2026-02-10T21:01:46.732943+07:00",
            "text": "Отличный выбор",
            "source_url": "https://2gis.ru/review/218320611",
            "stars": 5,
        }
    ]

    html = """
    <html>
      <head>
        <meta
          name="description"
          content="18 отзывов о Культура крепкого, винотека. Рейтинг 5 на основе 19 оценок."
        />
      </head>
      <body>
        <div data-review-id="dom-1">
          <div class="Name">DOM Автор</div>
          <time>2025-01-01</time>
          <div class="Comment">DOM отзыв</div>
        </div>
        <a href="/krasnodar/firm/70000001104623156/tab/reviews">
          <span>Отзывы</span>
          <span>18</span>
        </a>
        <div class="_1tam240">5</div>
      </body>
    </html>
    """

    review_count, rating, reviews = adapter.parse_html(
        html,
        source_url="https://2gis.ru/krasnodar/firm/70000001104623156/tab/reviews",
    )

    assert review_count == 18
    assert rating == 5.0
    assert len(reviews) == 1
    assert reviews[0]["external_id"] == "218320611"
    assert reviews[0]["author_name"] == "Ирина"


def test_twogis_adapter_sets_unknown_author_placeholder_when_name_missing() -> None:
    review = TwoGisAdapter._normalize_api_review(
        {
            "id": "218320611",
            "user": {},
            "date_created": "2026-02-10T21:01:46.732943+07:00",
            "text": "Понравилась работа кавистов.",
            "rating": 5,
        }
    )

    assert review["author_name"] == "Имя не определено"

def test_adapter_fetch_skips_invalid_zero_star_reviews() -> None:
    adapter = YandexAdapter(build_settings())
    adapter._load_html = lambda _: "<html></html>"  # type: ignore[method-assign]
    adapter.parse_html = lambda html, source_url=None: (  # type: ignore[method-assign]
        42,
        5.0,
        [
            {
                "external_id": "bad-review",
                "author_name": "Тест",
                "published_at": "",
                "text": "",
                "source_url": None,
                "stars": 0,
            },
            {
                "external_id": "good-review",
                "author_name": "Тест",
                "published_at": "2026-04-01T10:00:00+03:00",
                "text": "Нормальный отзыв",
                "source_url": None,
                "stars": 5,
            }
        ],
    )

    snapshot = adapter.fetch(
        MonitoringPoint(
            id="point-1",
            name="Точка 1",
            type="Винотека",
            address="Краснодар",
            yandex_url="https://example.com/yandex",
            twogis_url="https://example.com/2gis",
            is_active=True,
        )
    )

    assert snapshot.review_count == 42
    assert snapshot.rating == 5.0
    assert len(snapshot.reviews) == 1
    assert snapshot.reviews[0].external_id == "good-review"


def test_adapter_fetch_rounds_snapshot_rating() -> None:
    adapter = TwoGisAdapter(build_settings())
    adapter._load_html = lambda _: "<html></html>"  # type: ignore[method-assign]
    adapter.parse_html = lambda html, source_url=None: (  # type: ignore[method-assign]
        15,
        4.900000095367432,
        [
            {
                "external_id": "review-1",
                "author_name": "Тест",
                "published_at": "2026-04-01T10:00:00+03:00",
                "text": "Хороший отзыв",
                "source_url": None,
                "stars": 5,
            }
        ],
    )

    snapshot = adapter.fetch(
        MonitoringPoint(
            id="point-1",
            name="Точка 1",
            type="Винотека",
            address="Краснодар",
            yandex_url="https://example.com/yandex",
            twogis_url="https://example.com/2gis",
            is_active=True,
        )
    )

    assert snapshot.rating == 4.9


def test_adapter_builds_proxy_targets_from_settings() -> None:
    settings = build_settings()
    settings.proxy_urls = [
        "http://user:pass@proxy1.example.com:8080",
        "http://proxy2.example.com:3128",
    ]
    settings.proxy_max_attempts = 2
    adapter = YandexAdapter(settings)

    targets = adapter._build_proxy_targets()

    assert len(targets) == 2
    assert targets[0].server == "http://proxy1.example.com:8080"
    assert targets[0].username == "user"
    assert targets[0].password == "pass"
    assert targets[0].state_label == "proxy-1"
    assert targets[1].server == "http://proxy2.example.com:3128"
