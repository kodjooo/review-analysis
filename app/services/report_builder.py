from __future__ import annotations

from app.core.models import MonitoringRunResult, PlatformName, SheetTab, SheetsReport


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
                    f"ссылка={self._get_platform_url(point_report, platform)}, "
                    f"статус={delta.status.value}"
                )
                if delta.error_message:
                    lines.append(f"Ошибка: {delta.error_message}")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _format_value(value: object) -> str:
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
