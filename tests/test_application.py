from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from app.services.application import ReviewMonitoringApplication


def build_app(failed_ids: list[str], run_result: bool = True):
    settings = SimpleNamespace(
        timezone=ZoneInfo("Europe/Moscow"),
        report_stars_threshold=4,
        points=[
            SimpleNamespace(id="point-1", is_active=True),
            SimpleNamespace(id="point-2", is_active=True),
            SimpleNamespace(id="point-3", is_active=False),
        ],
    )
    database = Mock()
    scheduler = Mock()
    review_fetcher = Mock()
    report_builder = Mock()
    sheets_service = Mock()
    sheets_service.load_skipped_point_ids.return_value = failed_ids
    monitoring_service = Mock()
    monitoring_service.run_once.return_value = run_result

    app = ReviewMonitoringApplication(
        settings=settings,
        logger=Mock(),
        database=database,
        review_fetcher=review_fetcher,
        report_builder=report_builder,
        sheets_service=sheets_service,
        scheduler=scheduler,
    )
    app.monitoring_service = monitoring_service
    return app, sheets_service, monitoring_service


def test_application_reruns_only_failed_active_points() -> None:
    app, sheets_service, monitoring_service = build_app(["point-1", "point-3"])

    code = app.execute("rerun-failed")

    assert code == 0
    sheets_service.load_skipped_point_ids.assert_called_once()
    passed_points = monitoring_service.run_once.call_args.kwargs["points"]
    assert [point.id for point in passed_points] == ["point-1"]


def test_application_returns_zero_when_no_failed_points() -> None:
    app, sheets_service, monitoring_service = build_app([])

    code = app.execute("rerun-failed")

    assert code == 0
    sheets_service.load_skipped_point_ids.assert_called_once()
    monitoring_service.run_once.assert_not_called()
