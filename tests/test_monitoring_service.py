from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from logging import getLogger
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.core.models import (
    FailureKind,
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
    def __init__(self, scenario: dict[tuple[str, PlatformName, int], PlatformSnapshot] | None = None) -> None:
        self.scenario = scenario or {}
        self.attempts: dict[tuple[str, PlatformName], int] = {}

    def fetch_point_reviews(self, point: MonitoringPoint, platform: PlatformName) -> PlatformSnapshot:
        key = (point.id, platform)
        attempt = self.attempts.get(key, 0) + 1
        self.attempts[key] = attempt
        scenario_key = (point.id, platform, attempt)
        if scenario_key in self.scenario:
            return self.scenario[scenario_key]
        return self._success_snapshot(point, platform, stars=5, text=f"Отзыв {point.id} {platform.value}")

    @staticmethod
    def _success_snapshot(
        point: MonitoringPoint,
        platform: PlatformName,
        *,
        stars: int,
        text: str,
        review_count: int = 1,
        rating: float = 5.0,
    ) -> PlatformSnapshot:
        source_url = point.yandex_url if platform == PlatformName.YANDEX else point.twogis_url
        return PlatformSnapshot(
            point_id=point.id,
            platform=platform,
            source_url=source_url,
            collected_at=datetime.now(tz=ZoneInfo("Europe/Moscow")),
            review_count=review_count,
            rating=rating,
            reviews=[
                Review(
                    platform=platform,
                    published_at="2026-04-01T10:00:00+03:00",
                    stars=stars,
                    text=text,
                    source_url=source_url,
                    author_name="Тестовый автор",
                    external_id=f"{point.id}-{platform.value}-{stars}",
                    signature=f"{point.id}-{platform.value}-{stars}",
                )
            ],
            status=PlatformStatus.SUCCESS,
        )

    @staticmethod
    def _error_snapshot(
        point: MonitoringPoint,
        platform: PlatformName,
        message: str,
        failure_kind: FailureKind,
    ) -> PlatformSnapshot:
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
            failure_kind=failure_kind,
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
        self.export_modes: list[bool] = []
        self.cleared_titles: list[str] = []

    def export(self, report, merge_with_existing: bool = False) -> None:
        self.exports.append(report)
        self.export_modes.append(merge_with_existing)

    def clear_worksheet(self, title: str) -> None:
        self.cleared_titles.append(title)


def build_settings(flush_each_point: bool) -> SimpleNamespace:
    return SimpleNamespace(
        timezone=ZoneInfo("Europe/Moscow"),
        report_stars_threshold=4,
        delay_between_platforms_seconds=5,
        delay_between_points_seconds=10,
        delay_jitter_seconds=3,
        point_retry_delay_seconds=300,
        point_max_attempts=2,
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
    assert sheets_service.export_modes == [False, False, False]
    assert sheets_service.cleared_titles == ["skipped_points_last_run"]
    assert repository.finished_runs[-1] == (1, "completed")


def test_monitoring_service_marks_point_skipped_without_inrun_retry(monkeypatch) -> None:
    settings = build_settings(flush_each_point=False)
    point = settings.points[0]
    review_fetcher = FakeReviewFetcher(
        scenario={
            (point.id, PlatformName.YANDEX, 1): FakeReviewFetcher._error_snapshot(
                point,
                PlatformName.YANDEX,
                "DNS timeout",
                FailureKind.NETWORK,
            ),
        }
    )
    service, repository, sheets_service = build_service(settings, review_fetcher=review_fetcher)
    sleep_calls: list[int] = []
    monkeypatch.setattr("app.services.monitoring_service.time.sleep", sleep_calls.append)
    monkeypatch.setattr("app.services.monitoring_service.random.randint", lambda start, end: 0)

    success = service.run_once(points=[point])

    assert success is True
    assert repository.saved_snapshots == []
    assert sleep_calls == [5]
    skipped = sheets_service.exports[-1].skipped_points[0]
    assert skipped.failed_platforms == [PlatformName.YANDEX]
    assert skipped.failure_kind == FailureKind.NETWORK
    assert review_fetcher.attempts[(point.id, PlatformName.TWOGIS)] == 1


def test_validation_gate_skips_invalid_point_without_saving_snapshots(monkeypatch) -> None:
    settings = build_settings(flush_each_point=False)
    point = settings.points[0]
    invalid_snapshot = FakeReviewFetcher._success_snapshot(
        point,
        PlatformName.YANDEX,
        stars=5,
        text="Валидный текст",
        review_count=25,
        rating=6.0,
    )
    review_fetcher = FakeReviewFetcher(
        scenario={
            (point.id, PlatformName.YANDEX, 1): invalid_snapshot,
        }
    )
    service, repository, sheets_service = build_service(settings, review_fetcher=review_fetcher)
    monkeypatch.setattr("app.services.monitoring_service.time.sleep", lambda seconds: None)
    monkeypatch.setattr("app.services.monitoring_service.random.randint", lambda start, end: 0)

    success = service.run_once(points=[point])

    assert success is True
    assert repository.saved_snapshots == []
    assert repository.finished_runs[-1] == (1, "completed_with_errors")
    skipped = sheets_service.exports[-1].skipped_points[0]
    assert skipped.failure_kind == FailureKind.VALIDATION


def test_monitoring_service_rerun_mode_preserves_existing_summary_and_does_not_clear_skipped_sheet(monkeypatch) -> None:
    settings = build_settings(flush_each_point=True)
    service, repository, sheets_service = build_service(settings)
    monkeypatch.setattr("app.services.monitoring_service.time.sleep", lambda seconds: None)
    monkeypatch.setattr("app.services.monitoring_service.random.randint", lambda start, end: 0)

    success = service.run_once(
        points=[settings.points[0]],
        merge_with_existing=True,
        reset_skipped_points_sheet=False,
    )

    assert success is True
    assert len(repository.saved_snapshots) == 2
    assert sheets_service.cleared_titles == []
    assert sheets_service.export_modes == [True, True]
