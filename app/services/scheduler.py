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
                main_callback()
                self.next_failed_rerun_at = now + timedelta(
                    seconds=self.settings.failed_rerun_interval_seconds
                )
                time.sleep(self.settings.scheduler_poll_seconds)
                continue

            if (
                self.next_failed_rerun_at is not None
                and now >= self.next_failed_rerun_at
            ):
                if has_failed_points_callback():
                    self.logger.info("Наступило время повторного прохода пропущенных точек.")
                    rerun_failed_callback()
                    if has_failed_points_callback():
                        self.next_failed_rerun_at = now + timedelta(
                            seconds=self.settings.failed_rerun_interval_seconds
                        )
                    else:
                        self.logger.info("Пропущенные точки успешно добраны, hourly rerun остановлен.")
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
