from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import Logger

from app.core.config import Settings
from app.core.models import (
    FailureKind,
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


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int
    delay_seconds: int
    dominant_failure_kind: FailureKind


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
        self._yandex_antibot_streak = 0
        self._yandex_circuit_breaker_until: datetime | None = None

    def run_once(
        self,
        points: list[MonitoringPoint] | None = None,
        merge_with_existing: bool = False,
        reset_skipped_points_sheet: bool = True,
    ) -> bool:
        started_at = datetime.now(tz=self.settings.timezone)
        run_id = self.repository.create_run(started_at)
        self.logger.info("Старт мониторинга.")

        point_reports: list[PointReport] = []
        skipped_points: list[SkippedPointReport] = []
        has_errors = False
        active_points = points if points is not None else [point for point in self.settings.points if point.is_active]

        if reset_skipped_points_sheet:
            self.sheets_service.clear_worksheet("skipped_points_last_run")

        try:
            for point_index, point in enumerate(active_points):
                point_report, skipped_point = self._collect_point_report(run_id, point)
                if point_report is not None:
                    point_reports.append(point_report)
                    if self.settings.sheets_flush_each_point:
                        self._export_partial_report(
                            started_at,
                            point_reports,
                            skipped_points,
                            merge_with_existing=merge_with_existing,
                        )
                if skipped_point is not None:
                    skipped_points.append(skipped_point)
                    has_errors = True
                    if self.settings.sheets_flush_each_point:
                        self._export_partial_report(
                            started_at,
                            point_reports,
                            skipped_points,
                            merge_with_existing=merge_with_existing,
                        )

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
            self.sheets_service.export(
                self.report_builder.build(result),
                merge_with_existing=merge_with_existing,
            )
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

        snapshots: dict[PlatformName, PlatformSnapshot] = {}
        retry_policy = RetryPolicy(
            max_attempts=self.settings.point_max_attempts,
            delay_seconds=self.settings.point_retry_delay_seconds,
            dominant_failure_kind=FailureKind.UNKNOWN,
        )

        attempt = 1
        while attempt <= retry_policy.max_attempts:
            snapshots = {}
            failed_platforms: list[PlatformName] = []

            for platform_index, platform in enumerate(platforms):
                snapshot = self._fetch_platform_snapshot(point, platform)
                snapshots[platform] = snapshot
                self._register_platform_outcome(snapshot)

                if snapshot.status == PlatformStatus.ERROR:
                    failed_platforms.append(platform)
                    # Атомарная логика по точке: как только одна площадка не прошла,
                    # остальные запросы на этой попытке не имеют смысла для итоговой таблицы.
                    break

                if platform_index < len(platforms) - 1:
                    self._sleep_with_jitter(
                        base_seconds=self.settings.delay_between_platforms_seconds,
                        reason=f"перед следующей площадкой точки {point.id}",
                    )

            validation_errors = self._validate_point_snapshots(point, snapshots)
            if validation_errors:
                for platform, message in validation_errors.items():
                    failed_platforms.append(platform)
                    snapshots[platform] = self._build_error_snapshot(
                        point=point,
                        platform=platform,
                        message=message,
                        failure_kind=FailureKind.VALIDATION,
                    )

            if not failed_platforms:
                deltas = {}
                for platform in platforms:
                    snapshot = snapshots[platform]
                    previous = self.repository.get_previous_snapshot(point.id, platform.value)
                    deltas[platform] = self.comparison_service.compare(snapshot, previous)
                    self.repository.save_snapshot(run_id, snapshot)
                return PointReport(point=point, deltas=deltas), None

            retry_policy = self._resolve_retry_policy(snapshots, failed_platforms)
            failed_platforms = list(dict.fromkeys(failed_platforms))
            self.logger.warning(
                "Точка %s не будет выгружена в таблицу на попытке %s: ошибка по площадкам %s.",
                point.id,
                attempt,
                ", ".join(platform.value for platform in failed_platforms),
            )
            if attempt < retry_policy.max_attempts:
                self.logger.info(
                    "Пауза %s сек. перед повторной попыткой точки %s. Причина retry: %s.",
                    retry_policy.delay_seconds,
                    point.id,
                    retry_policy.dominant_failure_kind.value,
                )
                time.sleep(retry_policy.delay_seconds)
                attempt += 1
                continue

            self.logger.error(
                "Точка %s пропущена после %s попыток. В таблицу она не будет записана.",
                point.id,
                retry_policy.max_attempts,
            )
            last_attempted_at = max(snapshot.collected_at for snapshot in snapshots.values())
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
                failure_kind=retry_policy.dominant_failure_kind,
                last_successful_update_at=last_successful_update_at,
            )

        return None, None

    def _fetch_platform_snapshot(
        self,
        point: MonitoringPoint,
        platform: PlatformName,
    ) -> PlatformSnapshot:
        if platform == PlatformName.YANDEX and self._is_yandex_circuit_breaker_open():
            remaining_seconds = max(
                0,
                int((self._yandex_circuit_breaker_until - datetime.now(tz=self.settings.timezone)).total_seconds()),
            )
            return self._build_error_snapshot(
                point=point,
                platform=platform,
                message=f"Yandex circuit breaker активен, до повторной попытки осталось {remaining_seconds} сек.",
                failure_kind=FailureKind.CIRCUIT_BREAKER,
            )
        return self.review_fetcher.fetch_point_reviews(point, platform)

    def _validate_point_snapshots(
        self,
        point: MonitoringPoint,
        snapshots: dict[PlatformName, PlatformSnapshot],
    ) -> dict[PlatformName, str]:
        errors: dict[PlatformName, str] = {}
        for platform in (PlatformName.YANDEX, PlatformName.TWOGIS):
            snapshot = snapshots.get(platform)
            if snapshot is None:
                errors[platform] = f"Не удалось собрать платформу {platform.value}: снимок отсутствует."
                continue
            if snapshot.status != PlatformStatus.SUCCESS:
                continue
            if not 1.0 <= snapshot.rating <= 5.0:
                errors[platform] = (
                    f"Validation gate: рейтинг {snapshot.rating} вне диапазона 1..5 для {platform.value}."
                )
                continue
            if snapshot.review_count < 0:
                errors[platform] = (
                    f"Validation gate: количество отзывов {snapshot.review_count} меньше нуля для {platform.value}."
                )
                continue
            if any(review.stars < 1 or review.stars > 5 for review in snapshot.reviews):
                errors[platform] = (
                    f"Validation gate: в {platform.value} есть отзыв с рейтингом вне диапазона 1..5."
                )
                continue
        if errors:
            self.logger.warning(
                "Точка %s не прошла validation gate: %s",
                point.id,
                " | ".join(f"{platform.value}: {message}" for platform, message in errors.items()),
            )
        return errors

    def _resolve_retry_policy(
        self,
        snapshots: dict[PlatformName, PlatformSnapshot],
        failed_platforms: list[PlatformName],
    ) -> RetryPolicy:
        kinds = [
            snapshots[platform].failure_kind or FailureKind.UNKNOWN
            for platform in failed_platforms
            if platform in snapshots
        ]
        dominant_kind = kinds[0] if kinds else FailureKind.UNKNOWN
        policy_map = {
            FailureKind.ANTIBOT: RetryPolicy(
                max_attempts=self.settings.retry_antibot_max_attempts,
                delay_seconds=self.settings.retry_antibot_delay_seconds,
                dominant_failure_kind=FailureKind.ANTIBOT,
            ),
            FailureKind.CIRCUIT_BREAKER: RetryPolicy(
                max_attempts=self.settings.retry_antibot_max_attempts,
                delay_seconds=self.settings.retry_antibot_delay_seconds,
                dominant_failure_kind=FailureKind.CIRCUIT_BREAKER,
            ),
            FailureKind.NETWORK: RetryPolicy(
                max_attempts=self.settings.retry_network_max_attempts,
                delay_seconds=self.settings.retry_network_delay_seconds,
                dominant_failure_kind=FailureKind.NETWORK,
            ),
            FailureKind.PARSE: RetryPolicy(
                max_attempts=self.settings.retry_parse_max_attempts,
                delay_seconds=self.settings.retry_parse_delay_seconds,
                dominant_failure_kind=FailureKind.PARSE,
            ),
            FailureKind.VALIDATION: RetryPolicy(
                max_attempts=self.settings.retry_parse_max_attempts,
                delay_seconds=self.settings.retry_parse_delay_seconds,
                dominant_failure_kind=FailureKind.VALIDATION,
            ),
            FailureKind.UNKNOWN: RetryPolicy(
                max_attempts=self.settings.retry_unknown_max_attempts,
                delay_seconds=self.settings.retry_unknown_delay_seconds,
                dominant_failure_kind=FailureKind.UNKNOWN,
            ),
        }
        return policy_map.get(dominant_kind, policy_map[FailureKind.UNKNOWN])

    def _register_platform_outcome(self, snapshot: PlatformSnapshot) -> None:
        if snapshot.platform != PlatformName.YANDEX:
            return
        if snapshot.status == PlatformStatus.SUCCESS:
            self._yandex_antibot_streak = 0
            if self._yandex_circuit_breaker_until and datetime.now(tz=self.settings.timezone) >= self._yandex_circuit_breaker_until:
                self._yandex_circuit_breaker_until = None
            return
        if snapshot.failure_kind == FailureKind.ANTIBOT:
            self._yandex_antibot_streak += 1
            if self._yandex_antibot_streak >= self.settings.yandex_captcha_consecutive_threshold:
                self._yandex_circuit_breaker_until = datetime.now(tz=self.settings.timezone) + timedelta(
                    seconds=self.settings.yandex_circuit_breaker_seconds
                )
                self.logger.warning(
                    "Yandex circuit breaker активирован на %s сек. после %s подряд anti-bot ошибок.",
                    self.settings.yandex_circuit_breaker_seconds,
                    self._yandex_antibot_streak,
                )
        elif snapshot.failure_kind not in {FailureKind.CIRCUIT_BREAKER}:
            self._yandex_antibot_streak = 0

    def _is_yandex_circuit_breaker_open(self) -> bool:
        if self._yandex_circuit_breaker_until is None:
            return False
        if datetime.now(tz=self.settings.timezone) >= self._yandex_circuit_breaker_until:
            self._yandex_circuit_breaker_until = None
            self._yandex_antibot_streak = 0
            return False
        return True

    def _build_error_snapshot(
        self,
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
            collected_at=datetime.now(tz=self.settings.timezone),
            review_count=0,
            rating=0.0,
            reviews=[],
            status=PlatformStatus.ERROR,
            error_message=message,
            failure_kind=failure_kind,
        )

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
        merge_with_existing: bool,
    ) -> None:
        partial_result = MonitoringRunResult(
            run_started_at=started_at,
            run_finished_at=datetime.now(tz=self.settings.timezone),
            point_reports=list(point_reports),
            skipped_points=list(skipped_points),
        )
        self.sheets_service.export(
            self.report_builder.build(partial_result),
            merge_with_existing=merge_with_existing,
        )
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
