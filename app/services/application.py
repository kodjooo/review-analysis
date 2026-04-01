from __future__ import annotations

from datetime import datetime
from logging import Logger

from app.core.config import Settings
from app.core.models import MonitoringRunResult
from app.db.database import Database
from app.db.repository import MonitoringRepository
from app.services.monitoring_service import MonitoringService
from app.services.report_builder import ReportBuilder
from app.services.review_fetcher import ReviewFetcher
from app.services.scheduler import SchedulerService
from app.services.sheets_service import GoogleSheetsService


class ReviewMonitoringApplication:
    def __init__(
        self,
        settings: Settings,
        logger: Logger,
        database: Database,
        review_fetcher: ReviewFetcher,
        report_builder: ReportBuilder,
        sheets_service: GoogleSheetsService,
        scheduler: SchedulerService,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.database = database
        self.repository = MonitoringRepository(database)
        self.report_builder = report_builder
        self.sheets_service = sheets_service
        self.monitoring_service = MonitoringService(
            settings=settings,
            logger=logger,
            repository=self.repository,
            review_fetcher=review_fetcher,
            report_builder=report_builder,
            sheets_service=sheets_service,
        )
        self.scheduler = scheduler

    def execute(self, command: str) -> int:
        self.database.initialize()

        if command == "init-db":
            self.logger.info("База данных инициализирована.")
            return 0

        if command == "test-output":
            return self._test_output()

        if command == "rerun-failed":
            return self._rerun_failed_points()

        if command == "schedule":
            self.scheduler.run_forever(
                main_callback=self.monitoring_service.run_once,
                rerun_failed_callback=lambda: self._rerun_failed_points() == 0,
                has_failed_points_callback=self._has_failed_points,
            )
            return 0

        result = self.monitoring_service.run_once()
        return 0 if result else 1

    def _rerun_failed_points(self) -> int:
        failed_ids = set(self.sheets_service.load_skipped_point_ids())
        if not failed_ids:
            self.logger.info("Пропущенных точек для повторного прохода нет.")
            return 0

        points = [point for point in self.settings.points if point.is_active and point.id in failed_ids]
        if not points:
            self.logger.warning(
                "В листе пропущенных точек есть ID, которых нет в текущем конфиге: %s",
                ", ".join(sorted(failed_ids)),
            )
            return 1

        self.logger.info(
            "Запускается повторный проход по %s пропущенным точкам: %s",
            len(points),
            ", ".join(point.id for point in points),
        )
        result = self.monitoring_service.run_once(points=points)
        return 0 if result else 1

    def _has_failed_points(self) -> bool:
        return bool(self.sheets_service.load_skipped_point_ids())

    def _test_output(self) -> int:
        started = datetime.now(tz=self.settings.timezone)
        result = MonitoringRunResult(
            run_started_at=started,
            run_finished_at=started,
            point_reports=[],
            skipped_points=[],
        )
        report = self.report_builder.build(result)
        self.sheets_service.export(report)
        self.logger.info("Тестовая выгрузка в Google Sheets выполнена.")
        return 0
