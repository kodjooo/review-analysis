from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from logging import getLogger
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.core.models import (
    MonitoringPoint,
    PlatformName,
    PlatformSnapshot,
    PlatformStatus,
    Review,
)
from app.services.monitoring_service import MonitoringService


@dataclass
class FakeDelta:
    previous_review_count: int | None
    current_review_count: int | None
    previous_rating: float | None
    current_rating: float | None
    last_updated_at: str | None
    new_reviews: list[Review]
    low_rated_new_reviews: list[Review]
    status: PlatformStatus
    error_message: str | None = None


class FakeRepository:
    def __init__(self) -> None:
        self.saved_snapshots: list[PlatformSnapshot] = []
        self.finished_runs: list[tuple[int, str]] = []

    def create_run(self, started_at: datetime) -> int:
        return 1

    def get_previous_snapshot(self, point_id: str, platform: str):
        return None

    def save_snapshot(self, run_id: int, snapshot: PlatformSnapshot) -> None:
        self.saved_snapshots.append(snapshot)

    def finish_run(self, run_id: int, finished_at: datetime, status: str) -> None:
        self.finished_runs.append((run_id, status))


class FakeReviewFetcher:
    def __init__(
        self,
        fail_once_for_point_ids: set[str] | None = None,
        always_fail_for_point_ids: set[str] | None = None,
    ) -> None:
        self.fail_once_for_point_ids = fail_once_for_point_ids or set()
        self.always_fail_for_point_ids = always_fail_for_point_ids or set()
        self.failed_once: set[tuple[str, PlatformName]] = set()

    def fetch_point_reviews(self, point: MonitoringPoint, platform: PlatformName) -> PlatformSnapshot:
        if point.id in self.always_fail_for_point_ids and platform == PlatformName.YANDEX:
            return self._error_snapshot(point, platform, "Антибот")
        if (
            point.id in self.fail_once_for_point_ids
            and platform == PlatformName.YANDEX
            and (point.id, platform) not in self.failed_once
        ):
            self.failed_once.add((point.id, platform))
            return self._error_snapshot(point, platform, "Антибот")

        source_url = point.yandex_url if platform == PlatformName.YANDEX else point.twogis_url
        return PlatformSnapshot(
            point_id=point.id,
            platform=platform,
            source_url=source_url,
            collected_at=datetime.now(tz=ZoneInfo("Europe/Moscow")),
            review_count=1,
            rating=5.0,
            reviews=[
                Review(
                    platform=platform,
                    published_at="2026-04-01T10:00:00+03:00",
                    stars=2 if platform == PlatformName.YANDEX else 5,
                    text=f"Отзыв {point.id} {platform.value}",
                    source_url=source_url,
                    author_name="Тестовый автор",
                    external_id=f"{point.id}-{platform.value}",
                    signature=f"{point.id}-{platform.value}",
                )
            ],
            status=PlatformStatus.SUCCESS,
        )

    def _error_snapshot(self, point: MonitoringPoint, platform: PlatformName, message: str) -> PlatformSnapshot:
        source_url = point.yandex_url if platform == PlatformName.YANDEX else point.twogis_url
        return PlatformSnapshot(
            point_id=point.id,
            platform=platform,
            source_url=source_url,
            collected_at=datetime.now(tz=ZoneInfo("Europe/Moscow")),
            review_count=0,
            rating=0.0,
            reviews=[],
            status=PlatformStatus.ERROR,
            error_message=message,
        )


class FakeComparisonService:
    def compare(self, snapshot: PlatformSnapshot, previous) -> FakeDelta:
        return FakeDelta(
            previous_review_count=None,
            current_review_count=snapshot.review_count,
            previous_rating=None,
            current_rating=snapshot.rating,
            last_updated_at=snapshot.collected_at.strftime("%Y-%m-%d %H:%M:%S"),
            new_reviews=snapshot.reviews,
            low_rated_new_reviews=[review for review in snapshot.reviews if review.stars <= 4],
            status=snapshot.status,
            error_message=snapshot.error_message,
        )


class FakeReportBuilder:
    def build(self, result):
        return result


class FakeSheetsService:
    def __init__(self) -> None:
        self.exports: list = []
        self.cleared_titles: list[str] = []
        self.failed_point_ids: list[str] = []

    def export(self, report) -> None:
        self.exports.append(report)

    def clear_worksheet(self, title: str) -> None:
        self.cleared_titles.append(title)

    def load_skipped_point_ids(self, title: str = "skipped_points_last_run") -> list[str]:
        return list(self.failed_point_ids)


def build_settings(flush_each_point: bool) -> SimpleNamespace:
    return SimpleNamespace(
        timezone=ZoneInfo("Europe/Moscow"),
        report_stars_threshold=4,
        delay_between_platforms_seconds=5,
        delay_between_points_seconds=10,
        delay_jitter_seconds=3,
        point_retry_delay_seconds=300,
        point_max_attempts=2,
        sheets_flush_each_point=flush_each_point,
        points=[
            MonitoringPoint(
                id="point-1",
                name="Точка 1",
                type="Винотека",
                address="Краснодар, ул. Казбекская, 1",
                yandex_url="https://example.com/yandex-1",
                twogis_url="https://example.com/2gis-1",
                is_active=True,
            ),
            MonitoringPoint(
                id="point-2",
                name="Точка 2",
                type="Винотека",
                address="Краснодар, ул. Казбекская, 2",
                yandex_url="https://example.com/yandex-2",
                twogis_url="https://example.com/2gis-2",
                is_active=True,
            ),
        ],
    )


def build_service(
    settings: SimpleNamespace,
    review_fetcher: FakeReviewFetcher | None = None,
    sheets_service: FakeSheetsService | None = None,
):
    repository = FakeRepository()
    sheets = sheets_service or FakeSheetsService()
    service = MonitoringService(
        settings=settings,
        logger=getLogger("test-monitoring-service"),
        repository=repository,
        review_fetcher=review_fetcher or FakeReviewFetcher(),
        report_builder=FakeReportBuilder(),
        sheets_service=sheets,
    )
    service.comparison_service = FakeComparisonService()
    return service, repository, sheets


def test_monitoring_service_flushes_after_each_point_when_enabled(monkeypatch) -> None:
    settings = build_settings(flush_each_point=True)
    service, repository, sheets_service = build_service(settings)
    monkeypatch.setattr("app.services.monitoring_service.time.sleep", lambda seconds: None)
    monkeypatch.setattr("app.services.monitoring_service.random.randint", lambda start, end: 0)

    success = service.run_once()

    assert success is True
    assert len(repository.saved_snapshots) == 4
    assert [len(report.point_reports) for report in sheets_service.exports] == [1, 2, 2]
    assert sheets_service.cleared_titles == ["skipped_points_last_run"]
    assert repository.finished_runs[-1] == (1, "completed")


def test_monitoring_service_waits_between_platforms_and_points(monkeypatch) -> None:
    settings = build_settings(flush_each_point=False)
    service, _, sheets_service = build_service(settings)
    sleep_calls: list[int] = []
    monkeypatch.setattr("app.services.monitoring_service.time.sleep", sleep_calls.append)
    monkeypatch.setattr("app.services.monitoring_service.random.randint", lambda start, end: 2)

    success = service.run_once()

    assert success is True
    assert sleep_calls == [7, 12, 7]
    assert len(sheets_service.exports) == 1


def test_monitoring_service_retries_failed_point_and_skips_failed_attempt_export(monkeypatch) -> None:
    settings = build_settings(flush_each_point=True)
    review_fetcher = FakeReviewFetcher(fail_once_for_point_ids={"point-1"})
    service, repository, sheets_service = build_service(settings, review_fetcher=review_fetcher)
    sleep_calls: list[int] = []
    monkeypatch.setattr("app.services.monitoring_service.time.sleep", sleep_calls.append)
    monkeypatch.setattr("app.services.monitoring_service.random.randint", lambda start, end: 0)

    success = service.run_once()

    assert success is True
    assert len(repository.saved_snapshots) == 4
    assert [len(report.point_reports) for report in sheets_service.exports] == [1, 2, 2]
    assert sheets_service.exports[-1].skipped_points == []
    assert sleep_calls == [5, 300, 5, 10, 5]
    assert repository.finished_runs[-1] == (1, "completed")


def test_monitoring_service_puts_permanently_failed_point_into_skipped_list(monkeypatch) -> None:
    settings = build_settings(flush_each_point=True)
    review_fetcher = FakeReviewFetcher(always_fail_for_point_ids={"point-1"})
    service, repository, sheets_service = build_service(settings, review_fetcher=review_fetcher)
    sleep_calls: list[int] = []
    monkeypatch.setattr("app.services.monitoring_service.time.sleep", sleep_calls.append)
    monkeypatch.setattr("app.services.monitoring_service.random.randint", lambda start, end: 0)

    success = service.run_once()

    assert success is True
    assert len(repository.saved_snapshots) == 2
    assert repository.finished_runs[-1] == (1, "completed_with_errors")
    assert len(sheets_service.exports[-1].skipped_points) == 1
    skipped = sheets_service.exports[-1].skipped_points[0]
    assert skipped.point.id == "point-1"
    assert skipped.failed_platforms == [PlatformName.YANDEX]
    assert skipped.error_message == "yandex: Антибот"
    assert sleep_calls == [5, 300, 5, 10, 5]
