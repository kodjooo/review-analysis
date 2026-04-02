from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services.scheduler import SchedulerService


def build_settings() -> SimpleNamespace:
    return SimpleNamespace(
        timezone=ZoneInfo("Europe/Moscow"),
        scheduler_poll_seconds=1,
        schedule_frequency="daily",
        schedule_day="monday",
        schedule_hour=9,
        schedule_minute=0,
        failed_rerun_interval_seconds=3600,
    )


def test_scheduler_runs_hourly_reruns_until_failed_points_disappear(monkeypatch) -> None:
    settings = build_settings()
    scheduler = SchedulerService(
        settings=settings,
        logger=SimpleNamespace(
            info=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        ),
    )
    timeline = iter(
        [
            datetime(2026, 4, 1, 9, 0, 0, tzinfo=settings.timezone),
            datetime(2026, 4, 1, 10, 0, 0, tzinfo=settings.timezone),
            datetime(2026, 4, 1, 11, 0, 0, tzinfo=settings.timezone),
            datetime(2026, 4, 1, 11, 0, 1, tzinfo=settings.timezone),
        ]
    )

    class FakeDatetime:
        @staticmethod
        def now(tz=None):
            return next(timeline)

    sleep_calls: list[int] = []
    events: list[str] = []
    failed_states = iter([True, True, True, False])

    monkeypatch.setattr("app.services.scheduler.datetime", FakeDatetime)
    monkeypatch.setattr("app.services.scheduler.time.sleep", lambda seconds: sleep_calls.append(seconds))

    def main_callback() -> bool:
        events.append("main")
        return True

    def rerun_callback() -> bool:
        events.append("rerun")
        return True

    def has_failed_points_callback() -> bool:
        value = next(failed_states)
        if value is False and len(events) >= 3:
            raise StopIteration
        return value

    try:
        scheduler.run_forever(main_callback, rerun_callback, has_failed_points_callback)
    except StopIteration:
        pass

    assert events == ["main", "rerun", "rerun"]
    assert sleep_calls[:2] == [1, 1]
