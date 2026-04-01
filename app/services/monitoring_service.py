from __future__ import annotations

import random
import time
from datetime import datetime
from logging import Logger

from app.core.config import Settings
from app.core.models import MonitoringRunResult, PlatformName, PlatformStatus, PointReport
from app.db.repository import MonitoringRepository
from app.services.comparison import SnapshotComparisonService
from app.services.report_builder import ReportBuilder
from app.services.review_fetcher import ReviewFetcher
from app.services.sheets_service import GoogleSheetsService


class MonitoringService:
    def __init__(
        self,
        settings: Settings,
        logger: Logger,
        repository: MonitoringRepository,
        review_fetcher: ReviewFetcher,
        report_builder: ReportBuilder,
        sheets_service: GoogleSheetsService,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.repository = repository
        self.review_fetcher = review_fetcher
        self.report_builder = report_builder
        self.sheets_service = sheets_service
        self.comparison_service = SnapshotComparisonService(settings.report_stars_threshold)

    def run_once(self) -> bool:
        started_at = datetime.now(tz=self.settings.timezone)
        run_id = self.repository.create_run(started_at)
        self.logger.info("Старт мониторинга.")

        point_reports: list[PointReport] = []
        has_errors = False
        active_points = [point for point in self.settings.points if point.is_active]

        try:
            for point_index, point in enumerate(active_points):
                self.logger.info("Обрабатывается точка %s.", point.id)
                deltas = {}
                platforms = (PlatformName.YANDEX, PlatformName.TWOGIS)
                for platform_index, platform in enumerate(platforms):
                    snapshot = self.review_fetcher.fetch_point_reviews(point, platform)
                    previous = self.repository.get_previous_snapshot(point.id, platform.value)
                    deltas[platform] = self.comparison_service.compare(snapshot, previous)
                    self.repository.save_snapshot(run_id, snapshot)
                    if snapshot.status == PlatformStatus.ERROR:
                        has_errors = True

                    if platform_index < len(platforms) - 1:
                        self._sleep_with_jitter(
                            base_seconds=self.settings.delay_between_platforms_seconds,
                            reason=f"перед следующей площадкой точки {point.id}",
                        )

                point_report = PointReport(point=point, deltas=deltas)
                point_reports.append(point_report)

                if self.settings.sheets_flush_each_point:
                    self._export_partial_report(started_at, point_reports)

                if point_index < len(active_points) - 1:
                    self._sleep_with_jitter(
                        base_seconds=self.settings.delay_between_points_seconds,
                        reason=f"перед следующей точкой после {point.id}",
                    )

            finished_at = datetime.now(tz=self.settings.timezone)
            result = MonitoringRunResult(
                run_started_at=started_at,
                run_finished_at=finished_at,
                point_reports=point_reports,
            )
            self.sheets_service.export(self.report_builder.build(result))
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

    def _export_partial_report(self, started_at: datetime, point_reports: list[PointReport]) -> None:
        partial_result = MonitoringRunResult(
            run_started_at=started_at,
            run_finished_at=datetime.now(tz=self.settings.timezone),
            point_reports=list(point_reports),
        )
        self.sheets_service.export(self.report_builder.build(partial_result))
        self.logger.info(
            "Промежуточный отчет выгружен в Google Sheets после обработки %s точек.",
            len(point_reports),
        )

    def _sleep_with_jitter(self, base_seconds: int, reason: str) -> None:
        jitter = 0
        if self.settings.delay_jitter_seconds > 0:
            jitter = random.randint(0, self.settings.delay_jitter_seconds)

        total_delay = base_seconds + jitter
        if total_delay <= 0:
            return

        self.logger.info("Пауза %s сек. %s.", total_delay, reason)
        time.sleep(total_delay)
