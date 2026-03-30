from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
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

    def run_forever(self, callback: Callable[[], bool]) -> None:
        self.logger.info("Запущен планировщик.")
        while True:
            now = datetime.now(tz=self.settings.timezone)
            if self._is_due(now):
                self.logger.info("Наступило время планового запуска.")
                callback()
                time.sleep(self.settings.scheduler_poll_seconds)
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
