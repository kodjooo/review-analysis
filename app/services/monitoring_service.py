from __future__ import annotations

from datetime import datetime
from logging import Logger

from app.core.config import Settings
from app.core.models import MonitoringRunResult, PlatformName, PlatformStatus, PointReport
from app.db.repository import MonitoringRepository
from app.services.comparison import SnapshotComparisonService
from app.services.email_service import EmailService
from app.services.report_builder import ReportBuilder
from app.services.review_fetcher import ReviewFetcher


class MonitoringService:
    def __init__(
        self,
        settings: Settings,
        logger: Logger,
        repository: MonitoringRepository,
        review_fetcher: ReviewFetcher,
        report_builder: ReportBuilder,
        email_service: EmailService,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.repository = repository
        self.review_fetcher = review_fetcher
        self.report_builder = report_builder
        self.email_service = email_service
        self.comparison_service = SnapshotComparisonService(settings.report_stars_threshold)

    def run_once(self) -> bool:
        started_at = datetime.now(tz=self.settings.timezone)
        run_id = self.repository.create_run(started_at)
        self.logger.info("Старт мониторинга.")

        point_reports: list[PointReport] = []
        has_errors = False

        try:
            for point in self.settings.points:
                if not point.is_active:
                    self.logger.info("Точка %s пропущена: мониторинг выключен.", point.id)
                    continue

                self.logger.info("Обрабатывается точка %s.", point.id)
                deltas = {}
                for platform in (PlatformName.YANDEX, PlatformName.TWOGIS):
                    snapshot = self.review_fetcher.fetch_point_reviews(point, platform)
                    previous = self.repository.get_previous_snapshot(point.id, platform.value)
                    deltas[platform] = self.comparison_service.compare(snapshot, previous)
                    self.repository.save_snapshot(run_id, snapshot)
                    if snapshot.status == PlatformStatus.ERROR:
                        has_errors = True
                point_reports.append(PointReport(point=point, deltas=deltas))

            finished_at = datetime.now(tz=self.settings.timezone)
            result = MonitoringRunResult(
                run_started_at=started_at,
                run_finished_at=finished_at,
                point_reports=point_reports,
            )
            self.email_service.send(self.report_builder.build(result))
            self.repository.finish_run(
                run_id=run_id,
                finished_at=finished_at,
                status="completed_with_errors" if has_errors else "completed",
            )
            self.logger.info("Мониторинг завершен.")
            return True
        except Exception as error:
            finished_at = datetime.now(tz=self.settings.timezone)
            self.repository.finish_run(run_id=run_id, finished_at=finished_at, status="failed")
            self.logger.exception("Мониторинг завершился с ошибкой: %s", error)
            return False
