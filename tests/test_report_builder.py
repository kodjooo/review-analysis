from datetime import datetime

from app.core.models import (
    MonitoringPoint,
    MonitoringRunResult,
    PlatformDelta,
    PlatformName,
    PlatformStatus,
    PointReport,
    Review,
)
from app.services.report_builder import ReportBuilder


def test_report_builder_includes_low_rated_reviews() -> None:
    point = MonitoringPoint(
        id="point-1",
        name="Точка",
        type="Винотека",
        address="Краснодар",
        yandex_url="https://example.com/yandex",
        twogis_url="https://example.com/2gis",
        is_active=True,
    )
    review = Review(
        platform=PlatformName.YANDEX,
        published_at="2026-03-30",
        stars=4,
        text="Нужно улучшить сервис",
        source_url="https://example.com/review/1",
        author_name="Анна",
    )
    delta = PlatformDelta(
        point_id=point.id,
        platform=PlatformName.YANDEX,
        previous_review_count=10,
        current_review_count=11,
        previous_rating=4.5,
        current_rating=4.4,
        new_reviews=[review],
        low_rated_new_reviews=[review],
        status=PlatformStatus.SUCCESS,
    )
    point_report = PointReport(point=point, deltas={PlatformName.YANDEX: delta})
    result = MonitoringRunResult(
        run_started_at=datetime(2026, 3, 30, 9, 0, 0),
        run_finished_at=datetime(2026, 3, 30, 9, 5, 0),
        point_reports=[point_report],
    )

    message = ReportBuilder(stars_threshold=4).build(result)

    assert "Нужно улучшить сервис" in message.html
    assert "https://example.com/yandex" in message.html
    assert "новых=1" in message.plain_text
