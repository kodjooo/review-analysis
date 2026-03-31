from datetime import datetime

from app.core.models import (
    MonitoringPoint,
    MonitoringRunResult,
    PlatformDelta,
    PlatformName,
    PlatformSnapshot,
    PlatformStatus,
    PointReport,
    Review,
)
from app.core.utils import make_review_signature
from app.db.repository import PreviousSnapshot
from app.services.comparison import SnapshotComparisonService
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

    report = ReportBuilder(stars_threshold=4).build(result)

    summary_rows = report.sheets[1].rows
    low_rated_rows = report.sheets[2].rows

    assert summary_rows[1][8] == "https://example.com/yandex"
    assert low_rated_rows[1][5] == "Нужно улучшить сервис"
    assert low_rated_rows[1][4] == "4"


def test_report_builder_displays_2gis_platform_name() -> None:
    point = MonitoringPoint(
        id="point-1",
        name="Точка",
        type="Винотека",
        address="Краснодар",
        yandex_url="https://example.com/yandex",
        twogis_url="https://example.com/2gis",
        is_active=True,
    )
    delta = PlatformDelta(
        point_id=point.id,
        platform=PlatformName.TWOGIS,
        previous_review_count=17,
        current_review_count=18,
        previous_rating=5.0,
        current_rating=5.0,
        new_reviews=[],
        low_rated_new_reviews=[],
        status=PlatformStatus.SUCCESS,
    )
    point_report = PointReport(point=point, deltas={PlatformName.TWOGIS: delta})
    result = MonitoringRunResult(
        run_started_at=datetime(2026, 3, 30, 9, 0, 0),
        run_finished_at=datetime(2026, 3, 30, 9, 5, 0),
        point_reports=[point_report],
    )

    report = ReportBuilder(stars_threshold=4).build(result)

    assert report.sheets[1].rows[1][2] == "2gis"


def test_report_builder_low_rated_sheet_contains_only_new_low_rated_reviews_for_each_platform() -> None:
    point = MonitoringPoint(
        id="point-1",
        name="Точка",
        type="Винотека",
        address="Краснодар",
        yandex_url="https://example.com/yandex",
        twogis_url="https://example.com/2gis",
        is_active=True,
    )
    yandex_review = Review(
        platform=PlatformName.YANDEX,
        published_at="2026-03-31T10:00:00Z",
        stars=2,
        text="Яндекс: новый низкий отзыв",
        source_url="https://example.com/yandex/review-1",
        author_name="Анна",
    )
    twogis_review = Review(
        platform=PlatformName.TWOGIS,
        published_at="2026-03-31T11:00:00+03:00",
        stars=3,
        text="2GIS: новый низкий отзыв",
        source_url="https://example.com/2gis/review-1",
        author_name="Олег",
    )
    yandex_delta = PlatformDelta(
        point_id=point.id,
        platform=PlatformName.YANDEX,
        previous_review_count=41,
        current_review_count=42,
        previous_rating=5.0,
        current_rating=4.9,
        new_reviews=[yandex_review],
        low_rated_new_reviews=[yandex_review],
        status=PlatformStatus.SUCCESS,
    )
    twogis_delta = PlatformDelta(
        point_id=point.id,
        platform=PlatformName.TWOGIS,
        previous_review_count=17,
        current_review_count=18,
        previous_rating=5.0,
        current_rating=4.8,
        new_reviews=[twogis_review],
        low_rated_new_reviews=[twogis_review],
        status=PlatformStatus.SUCCESS,
    )
    point_report = PointReport(
        point=point,
        deltas={
            PlatformName.YANDEX: yandex_delta,
            PlatformName.TWOGIS: twogis_delta,
        },
    )
    result = MonitoringRunResult(
        run_started_at=datetime(2026, 3, 31, 12, 0, 0),
        run_finished_at=datetime(2026, 3, 31, 12, 5, 0),
        point_reports=[point_report],
    )

    report = ReportBuilder(stars_threshold=4).build(result)
    rows = report.sheets[2].rows

    assert len(rows) == 3
    assert rows[1][2] == "yandex"
    assert rows[1][5] == "Яндекс: новый низкий отзыв"
    assert rows[2][2] == "2gis"
    assert rows[2][5] == "2GIS: новый низкий отзыв"


def test_end_to_end_new_low_rated_review_appears_in_low_rated_sheet() -> None:
    point = MonitoringPoint(
        id="point-1",
        name="Точка",
        type="Винотека",
        address="Краснодар",
        yandex_url="https://example.com/yandex",
        twogis_url="https://example.com/2gis",
        is_active=True,
    )
    old_review = Review(
        platform=PlatformName.YANDEX,
        published_at="2026-03-30T10:00:00Z",
        stars=5,
        text="Старый отзыв",
        source_url="https://example.com/yandex/review-old",
        author_name="Иван",
    )
    old_review.signature = make_review_signature(old_review)
    new_bad_review = Review(
        platform=PlatformName.YANDEX,
        published_at="2026-03-31T10:00:00Z",
        stars=2,
        text="Новый плохой отзыв",
        source_url="https://example.com/yandex/review-bad",
        author_name="Анна",
    )
    new_bad_review.signature = make_review_signature(new_bad_review)

    snapshot = PlatformSnapshot(
        point_id=point.id,
        platform=PlatformName.YANDEX,
        source_url=point.yandex_url,
        collected_at=datetime(2026, 3, 31, 12, 0, 0),
        review_count=42,
        rating=4.8,
        reviews=[old_review, new_bad_review],
    )
    previous = PreviousSnapshot(
        review_count=41,
        rating=5.0,
        signatures={old_review.signature},
    )

    delta = SnapshotComparisonService(stars_threshold=4).compare(snapshot, previous)
    report = ReportBuilder(stars_threshold=4).build(
        MonitoringRunResult(
            run_started_at=datetime(2026, 3, 31, 12, 0, 0),
            run_finished_at=datetime(2026, 3, 31, 12, 5, 0),
            point_reports=[PointReport(point=point, deltas={PlatformName.YANDEX: delta})],
        )
    )

    rows = report.sheets[2].rows

    assert len(delta.new_reviews) == 1
    assert len(delta.low_rated_new_reviews) == 1
    assert rows[1][2] == "yandex"
    assert rows[1][4] == "2"
    assert rows[1][5] == "Новый плохой отзыв"
