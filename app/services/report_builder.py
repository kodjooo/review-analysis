from __future__ import annotations

from html import escape

from app.core.models import EmailMessage, MonitoringRunResult, PlatformName, PlatformStatus


class ReportBuilder:
    def __init__(self, stars_threshold: int) -> None:
        self.stars_threshold = stars_threshold

    def build(self, result: MonitoringRunResult) -> EmailMessage:
        subject = (
            f"Мониторинг отзывов за период — "
            f"{result.run_finished_at.strftime('%Y-%m-%d %H:%M')}"
        )
        return EmailMessage(
            subject=subject,
            html=self._build_html(result),
            plain_text=self._build_text(result),
        )

    def _build_html(self, result: MonitoringRunResult) -> str:
        summary_rows: list[str] = []
        low_rated_rows: list[str] = []

        for point_report in result.point_reports:
            for platform in (PlatformName.YANDEX, PlatformName.TWOGIS):
                delta = point_report.deltas.get(platform)
                if delta is None:
                    continue
                summary_rows.append(
                    "<tr>"
                    f"<td>{escape(point_report.point.type)}</td>"
                    f"<td>{escape(point_report.point.address)}</td>"
                    f"<td>{escape(platform.value)}</td>"
                    f"<td>{self._format_value(delta.previous_review_count)}</td>"
                    f"<td>{self._format_value(delta.current_review_count)}</td>"
                    f"<td>{len(delta.new_reviews)}</td>"
                    f"<td>{self._format_value(delta.previous_rating)}</td>"
                    f"<td>{self._format_value(delta.current_rating)}</td>"
                    f"<td><a href=\"{escape(self._get_platform_url(point_report, platform))}\">ссылка</a></td>"
                    f"<td>{escape(delta.error_message or delta.status.value)}</td>"
                    "</tr>"
                )
                for review in delta.low_rated_new_reviews:
                    low_rated_rows.append(
                        "<tr>"
                        f"<td>{escape(point_report.point.type)}</td>"
                        f"<td>{escape(point_report.point.address)}</td>"
                        f"<td>{escape(platform.value)}</td>"
                        f"<td>{escape(review.published_at)}</td>"
                        f"<td>{review.stars}</td>"
                        f"<td>{escape(review.text)}</td>"
                        f"<td><a href=\"{escape(review.source_url)}\">ссылка</a></td>"
                        "</tr>"
                    )

        return (
            "<html><body>"
            "<h1>Мониторинг отзывов</h1>"
            f"<p>Дата завершения: {result.run_finished_at.strftime('%Y-%m-%d %H:%M:%S')}</p>"
            "<h2>Сводка</h2>"
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<thead><tr><th>Тип магазина</th><th>Адрес</th><th>Площадка</th>"
            "<th>Было отзывов</th><th>Стало отзывов</th><th>Новых</th>"
            "<th>Рейтинг был</th><th>Рейтинг стал</th><th>Ссылка</th><th>Статус</th></tr></thead>"
            f"<tbody>{''.join(summary_rows) or '<tr><td colspan=\"10\">Нет данных</td></tr>'}</tbody>"
            "</table>"
            f"<h2>Новые отзывы со звездами не выше {self.stars_threshold}</h2>"
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<thead><tr><th>Тип магазина</th><th>Адрес</th><th>Площадка</th>"
            "<th>Дата</th><th>Звезды</th><th>Текст</th><th>Ссылка</th></tr></thead>"
            f"<tbody>{''.join(low_rated_rows) or '<tr><td colspan=\"7\">Нет новых отзывов ниже порога</td></tr>'}</tbody>"
            "</table>"
            "</body></html>"
        )

    def _build_text(self, result: MonitoringRunResult) -> str:
        lines = ["Мониторинг отзывов", ""]
        for point_report in result.point_reports:
            lines.append(f"{point_report.point.type}, {point_report.point.address}")
            for platform in (PlatformName.YANDEX, PlatformName.TWOGIS):
                delta = point_report.deltas.get(platform)
                if delta is None:
                    continue
                lines.append(
                    f"{platform.value}: было={self._format_value(delta.previous_review_count)}, "
                    f"стало={self._format_value(delta.current_review_count)}, "
                    f"новых={len(delta.new_reviews)}, "
                    f"рейтинг был={self._format_value(delta.previous_rating)}, "
                    f"рейтинг стал={self._format_value(delta.current_rating)}, "
                    f"ссылка={self._get_platform_url(point_report, platform)}, "
                    f"статус={delta.status.value}"
                )
                if delta.error_message:
                    lines.append(f"Ошибка: {delta.error_message}")
                for review in delta.low_rated_new_reviews:
                    lines.append(
                        f"Новый отзыв: {review.published_at} | {review.stars} | {review.text}"
                    )
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
