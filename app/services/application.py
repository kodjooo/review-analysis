from __future__ import annotations

from datetime import datetime
from logging import Logger

from app.core.config import Settings
from app.core.models import MonitoringRunResult
from app.db.database import Database
from app.db.repository import MonitoringRepository
from app.services.email_service import EmailService
from app.services.monitoring_service import MonitoringService
from app.services.report_builder import ReportBuilder
from app.services.review_fetcher import ReviewFetcher
from app.services.scheduler import SchedulerService


class ReviewMonitoringApplication:
    def __init__(
        self,
        settings: Settings,
        logger: Logger,
        database: Database,
        review_fetcher: ReviewFetcher,
        report_builder: ReportBuilder,
        email_service: EmailService,
        scheduler: SchedulerService,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.database = database
        self.repository = MonitoringRepository(database)
        self.report_builder = report_builder
        self.email_service = email_service
        self.monitoring_service = MonitoringService(
            settings=settings,
            logger=logger,
            repository=self.repository,
            review_fetcher=review_fetcher,
            report_builder=report_builder,
            email_service=email_service,
        )
        self.scheduler = scheduler

    def execute(self, command: str) -> int:
        self.database.initialize()

        if command == "init-db":
            self.logger.info("База данных инициализирована.")
            return 0

        if command == "test-email":
            return self._test_email()

        if command == "schedule":
            self.scheduler.run_forever(self.monitoring_service.run_once)
            return 0

        result = self.monitoring_service.run_once()
        return 0 if result else 1

    def _test_email(self) -> int:
        started = datetime.now(tz=self.settings.timezone)
        result = MonitoringRunResult(
            run_started_at=started,
            run_finished_at=started,
            point_reports=[],
        )
        message = self.report_builder.build(result)
        self.email_service.send(message)
        self.logger.info("Тестовое письмо отправлено.")
        return 0
