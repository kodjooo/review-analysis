from __future__ import annotations

from app.core.models import (
    MonitoringRunResult,
    PlatformName,
    SheetTab,
    SheetsReport,
    SkippedPointReport,
)


class ReportBuilder:
    def __init__(self, stars_threshold: int) -> None:
        self.stars_threshold = stars_threshold

    def build(self, result: MonitoringRunResult) -> SheetsReport:
        title = f"Мониторинг отзывов {result.run_finished_at.strftime('%Y-%m-%d %H:%M')}"
        return SheetsReport(
            spreadsheet_title=title,
            sheets=[
                self._build_meta_sheet(result),
                self._build_summary_sheet(result),
                self._build_low_rated_sheet(result),
                self._build_skipped_points_sheet(result),
            ],
        )

    def _build_meta_sheet(self, result: MonitoringRunResult) -> SheetTab:
        return SheetTab(
            title="run_info",
            rows=[
                ["Параметр", "Значение"],
                ["Начало запуска", result.run_started_at.strftime("%Y-%m-%d %H:%M:%S")],
                ["Завершение запуска", result.run_finished_at.strftime("%Y-%m-%d %H:%M:%S")],
                ["Порог звезд", str(self.stars_threshold)],
                ["Количество точек в отчете", str(len(result.point_reports))],
                ["Количество пропущенных точек", str(len(result.skipped_points))],
            ],
        )

    def _build_summary_sheet(self, result: MonitoringRunResult) -> SheetTab:
        rows: list[list[str]] = [[
            "Тип магазина",
            "Адрес",
            "Площадка",
            "Было отзывов",
            "Стало отзывов",
            "Новых",
            "Рейтинг был",
            "Рейтинг стал",
            "Последнее обновление",
            "Ссылка",
            "Статус",
            "Ошибка",
        ]]
        for point_report in result.point_reports:
            for platform in (PlatformName.YANDEX, PlatformName.TWOGIS):
                delta = point_report.deltas.get(platform)
                if delta is None:
                    continue
                rows.append(
                    [
                        point_report.point.type,
                        point_report.point.address,
                        self._display_platform_name(platform),
                        self._format_value(delta.previous_review_count),
                        self._format_value(delta.current_review_count),
                        str(len(delta.new_reviews)),
                        self._format_value(delta.previous_rating),
                        self._format_value(delta.current_rating),
                        self._format_value(delta.last_updated_at),
                        self._get_platform_url(point_report, platform),
                        delta.status.value,
                        delta.error_message or "",
                    ]
                )
        return SheetTab(title="summary", rows=rows)

    def _build_low_rated_sheet(self, result: MonitoringRunResult) -> SheetTab:
        rows: list[list[str]] = [[
            "Тип магазина",
            "Адрес",
            "Площадка",
            "Дата",
            "Звезды",
            "Текст",
            "Ссылка",
        ]]
        for point_report in result.point_reports:
            for platform in (PlatformName.YANDEX, PlatformName.TWOGIS):
                delta = point_report.deltas.get(platform)
                if delta is None:
                    continue
                for review in delta.low_rated_new_reviews:
                    rows.append(
                        [
                            point_report.point.type,
                            point_report.point.address,
                            self._display_platform_name(platform),
                            review.published_at,
                            str(review.stars),
                            review.text,
                            review.source_url,
                        ]
                    )
        return SheetTab(title="low_rated_new_reviews", rows=rows)

    def _build_skipped_points_sheet(self, result: MonitoringRunResult) -> SheetTab:
        rows: list[list[str]] = [[
            "ID точки",
            "Тип магазина",
            "Адрес",
            "Площадки с ошибкой",
            "Попыток",
            "Последняя попытка",
            "Последнее успешное обновление",
            "Ошибка",
            "Yandex URL",
            "2GIS URL",
        ]]
        for skipped in result.skipped_points:
            rows.append(self._build_skipped_point_row(skipped))
        return SheetTab(title="skipped_points_last_run", rows=rows)

    def _build_skipped_point_row(self, skipped: SkippedPointReport) -> list[str]:
        return [
            skipped.point.id,
            skipped.point.type,
            skipped.point.address,
            ", ".join(self._display_platform_name(platform) for platform in skipped.failed_platforms),
            str(skipped.attempts),
            skipped.last_attempted_at.strftime("%Y-%m-%d %H:%M:%S"),
            self._format_value(skipped.last_successful_update_at),
            skipped.error_message,
            skipped.point.yandex_url,
            skipped.point.twogis_url,
        ]

    def build_text(self, result: MonitoringRunResult) -> str:
        lines = ["Мониторинг отзывов", ""]
        for point_report in result.point_reports:
            lines.append(f"{point_report.point.type}, {point_report.point.address}")
            for platform in (PlatformName.YANDEX, PlatformName.TWOGIS):
                delta = point_report.deltas.get(platform)
                if delta is None:
                    continue
                lines.append(
                    f"{self._display_platform_name(platform)}: было={self._format_value(delta.previous_review_count)}, "
                    f"стало={self._format_value(delta.current_review_count)}, "
                    f"новых={len(delta.new_reviews)}, "
                    f"рейтинг был={self._format_value(delta.previous_rating)}, "
                    f"рейтинг стал={self._format_value(delta.current_rating)}, "
                    f"последнее обновление={self._format_value(delta.last_updated_at)}, "
                    f"ссылка={self._get_platform_url(point_report, platform)}, "
                    f"статус={delta.status.value}"
                )
                if delta.error_message:
                    lines.append(f"Ошибка: {delta.error_message}")
            lines.append("")
        if result.skipped_points:
            lines.append("Пропущенные точки:")
            for skipped in result.skipped_points:
                lines.append(
                    f"{skipped.point.id}: {skipped.point.address} | "
                    f"ошибка по площадкам={', '.join(self._display_platform_name(p) for p in skipped.failed_platforms)} | "
                    f"попыток={skipped.attempts} | "
                    f"последняя попытка={skipped.last_attempted_at.strftime('%Y-%m-%d %H:%M:%S')}"
                )
        return "\n".join(lines).strip()

    @staticmethod
    def _format_value(value: object) -> str:
        if isinstance(value, float):
            return f"{value:.1f}"
        return "н/д" if value is None else str(value)

    @staticmethod
    def _get_platform_url(point_report, platform: PlatformName) -> str:
        return (
            point_report.point.yandex_url
            if platform == PlatformName.YANDEX
            else point_report.point.twogis_url
        )

    @staticmethod
    def _display_platform_name(platform: PlatformName) -> str:
        return "2gis" if platform == PlatformName.TWOGIS else platform.value
