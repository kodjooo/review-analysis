from __future__ import annotations

import random
import time
from datetime import datetime
from logging import Logger

from app.core.config import Settings
from app.core.models import (
    MonitoringPoint,
    MonitoringRunResult,
    PlatformName,
    PlatformSnapshot,
    PlatformStatus,
    PointReport,
    SkippedPointReport,
)
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

    def run_once(self, points: list[MonitoringPoint] | None = None) -> bool:
        started_at = datetime.now(tz=self.settings.timezone)
        run_id = self.repository.create_run(started_at)
        self.logger.info("Старт мониторинга.")

        point_reports: list[PointReport] = []
        skipped_points: list[SkippedPointReport] = []
        has_errors = False
        active_points = points if points is not None else [point for point in self.settings.points if point.is_active]

        self.sheets_service.clear_worksheet("skipped_points_last_run")

        try:
            for point_index, point in enumerate(active_points):
                point_report, skipped_point = self._collect_point_report(run_id, point)
                if point_report is not None:
                    point_reports.append(point_report)
                    if self.settings.sheets_flush_each_point:
                        self._export_partial_report(started_at, point_reports, skipped_points)
                if skipped_point is not None:
                    skipped_points.append(skipped_point)
                    has_errors = True
                    if self.settings.sheets_flush_each_point:
                        self._export_partial_report(started_at, point_reports, skipped_points)

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
                skipped_points=skipped_points,
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

    def _collect_point_report(
        self,
        run_id: int,
        point: MonitoringPoint,
    ) -> tuple[PointReport | None, SkippedPointReport | None]:
        self.logger.info("Обрабатывается точка %s.", point.id)
        platforms = (PlatformName.YANDEX, PlatformName.TWOGIS)

        for attempt in range(1, self.settings.point_max_attempts + 1):
            snapshots: dict[PlatformName, PlatformSnapshot] = {}
            failed_platforms: list[PlatformName] = []

            for platform_index, platform in enumerate(platforms):
                snapshot = self.review_fetcher.fetch_point_reviews(point, platform)
                snapshots[platform] = snapshot
                if snapshot.status == PlatformStatus.ERROR:
                    failed_platforms.append(platform)

                if platform_index < len(platforms) - 1:
                    self._sleep_with_jitter(
                        base_seconds=self.settings.delay_between_platforms_seconds,
                        reason=f"перед следующей площадкой точки {point.id}",
                    )

            if not failed_platforms:
                deltas = {}
                for platform in platforms:
                    snapshot = snapshots[platform]
                    previous = self.repository.get_previous_snapshot(point.id, platform.value)
                    deltas[platform] = self.comparison_service.compare(snapshot, previous)
                    self.repository.save_snapshot(run_id, snapshot)
                return PointReport(point=point, deltas=deltas), None

            self.logger.warning(
                "Точка %s не будет выгружена в таблицу на попытке %s: ошибка по площадкам %s.",
                point.id,
                attempt,
                ", ".join(platform.value for platform in failed_platforms),
            )
            if attempt < self.settings.point_max_attempts:
                self.logger.info(
                    "Пауза %s сек. перед повторной попыткой точки %s.",
                    self.settings.point_retry_delay_seconds,
                    point.id,
                )
                time.sleep(self.settings.point_retry_delay_seconds)
                continue

            self.logger.error(
                "Точка %s пропущена после %s попыток. В таблицу она не будет записана.",
                point.id,
                self.settings.point_max_attempts,
            )
            last_attempted_at = max(
                snapshot.collected_at for snapshot in snapshots.values()
            )
            last_successful_update_at = self._last_successful_update_at(snapshots)
            return None, SkippedPointReport(
                point=point,
                failed_platforms=failed_platforms,
                attempts=attempt,
                last_attempted_at=last_attempted_at,
                error_message=" | ".join(
                    f"{platform.value}: {snapshots[platform].error_message or 'неизвестная ошибка'}"
                    for platform in failed_platforms
                ),
                last_successful_update_at=last_successful_update_at,
            )

        return None, None

    def _last_successful_update_at(self, snapshots: dict[PlatformName, PlatformSnapshot]) -> str | None:
        successful_times = [
            snapshot.collected_at.strftime("%Y-%m-%d %H:%M:%S")
            for snapshot in snapshots.values()
            if snapshot.status == PlatformStatus.SUCCESS
        ]
        return max(successful_times) if successful_times else None

    def _export_partial_report(
        self,
        started_at: datetime,
        point_reports: list[PointReport],
        skipped_points: list[SkippedPointReport],
    ) -> None:
        partial_result = MonitoringRunResult(
            run_started_at=started_at,
            run_finished_at=datetime.now(tz=self.settings.timezone),
            point_reports=list(point_reports),
            skipped_points=list(skipped_points),
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
