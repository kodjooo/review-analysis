from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from logging import Logger

from app.core.config import Settings


class SchedulerService:
    WEEKDAYS = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    def __init__(self, settings: Settings, logger: Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.last_trigger_key: str | None = None
        self.next_failed_rerun_at: datetime | None = None

    def run_forever(
        self,
        main_callback: Callable[[], bool],
        rerun_failed_callback: Callable[[], bool],
        has_failed_points_callback: Callable[[], bool],
    ) -> None:
        self.logger.info("Запущен планировщик.")
        while True:
            now = datetime.now(tz=self.settings.timezone)

            if self._is_due(now):
                self.logger.info("Наступило время планового запуска.")
                self._safe_invoke("Плановый запуск завершился ошибкой", main_callback)
                self.next_failed_rerun_at = now + timedelta(
                    seconds=self.settings.failed_rerun_interval_seconds
                )
                time.sleep(self.settings.scheduler_poll_seconds)
                continue

            if self.next_failed_rerun_at is not None and now >= self.next_failed_rerun_at:
                has_failed_points = self._safe_check_failed_points(
                    "Не удалось проверить список пропущенных точек перед rerun-failed",
                    has_failed_points_callback,
                )
                if has_failed_points is None:
                    self.next_failed_rerun_at = now + timedelta(
                        seconds=self.settings.failed_rerun_interval_seconds
                    )
                    time.sleep(self.settings.scheduler_poll_seconds)
                    continue

                if has_failed_points:
                    self.logger.info("Наступило время повторного прохода пропущенных точек.")
                    if not self._safe_invoke(
                        "Повторный проход пропущенных точек завершился ошибкой",
                        rerun_failed_callback,
                    ):
                        self.next_failed_rerun_at = now + timedelta(
                            seconds=self.settings.failed_rerun_interval_seconds
                        )
                        time.sleep(self.settings.scheduler_poll_seconds)
                        continue

                    has_failed_points = self._safe_check_failed_points(
                        "Не удалось повторно проверить список пропущенных точек после rerun-failed",
                        has_failed_points_callback,
                    )
                    if has_failed_points is None or has_failed_points:
                        self.next_failed_rerun_at = now + timedelta(
                            seconds=self.settings.failed_rerun_interval_seconds
                        )
                    else:
                        self.logger.info(
                            "Пропущенные точки успешно добраны, hourly rerun остановлен."
                        )
                        self.next_failed_rerun_at = None
                else:
                    self.next_failed_rerun_at = None

            time.sleep(self.settings.scheduler_poll_seconds)

    def _is_due(self, now: datetime) -> bool:
        current_key = now.strftime("%Y-%m-%d %H:%M")
        if self.last_trigger_key == current_key:
            return False
        if now.hour != self.settings.schedule_hour or now.minute != self.settings.schedule_minute:
            return False
        if self.settings.schedule_frequency == "daily":
            self.last_trigger_key = current_key
            return True
        is_due = self.WEEKDAYS.get(self.settings.schedule_day.lower()) == now.weekday()
        if is_due:
            self.last_trigger_key = current_key
        return is_due

    def _safe_invoke(self, message: str, callback: Callable[[], bool]) -> bool:
        try:
            return callback()
        except Exception as error:
            self.logger.exception("%s: %s", message, error)
            return False

    def _safe_check_failed_points(
        self,
        message: str,
        callback: Callable[[], bool],
    ) -> bool | None:
        try:
            return callback()
        except StopIteration:
            raise
        except Exception as error:
            self.logger.exception("%s: %s", message, error)
            return None
