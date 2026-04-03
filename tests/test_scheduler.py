from __future__ import annotations

from datetime import datetime
from logging import getLogger
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services.scheduler import SchedulerService


def build_settings() -> SimpleNamespace:
    return SimpleNamespace(
        timezone=ZoneInfo("Europe/Moscow"),
        failed_rerun_interval_seconds=1800,
        scheduler_poll_seconds=5,
        schedule_frequency="daily",
        schedule_day="monday",
        schedule_hour=15,
        schedule_minute=23,
    )


def test_scheduler_schedules_failed_rerun_on_startup_when_skipped_points_exist(monkeypatch) -> None:
    scheduler = SchedulerService(build_settings(), getLogger("test-scheduler"))
    callbacks = {"main": 0, "rerun": 0, "checks": 0}

    def main_callback() -> bool:
        callbacks["main"] += 1
        return True

    def rerun_callback() -> bool:
        callbacks["rerun"] += 1
        raise SystemExit

    def has_failed_points_callback() -> bool:
        callbacks["checks"] += 1
        return True

    moments = iter(
        [
            datetime(2026, 4, 3, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
            datetime(2026, 4, 3, 12, 30, tzinfo=ZoneInfo("Europe/Moscow")),
        ]
    )

    class FakeDatetime:
        @staticmethod
        def now(tz=None):
            current = next(moments)
            return current if tz is None else current.astimezone(tz)

    monkeypatch.setattr("app.services.scheduler.datetime", FakeDatetime)
    monkeypatch.setattr("app.services.scheduler.time.sleep", lambda seconds: None)

    try:
        scheduler.run_forever(main_callback, rerun_callback, has_failed_points_callback)
    except SystemExit:
        pass

    assert callbacks["main"] == 0
    assert callbacks["checks"] >= 1
    assert callbacks["rerun"] == 1
