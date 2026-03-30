from pathlib import Path

from app.core.config import load_settings
from app.core.logging import configure_logging
from app.db.database import Database
from app.services.application import ReviewMonitoringApplication
from app.services.email_service import EmailService
from app.services.report_builder import ReportBuilder
from app.services.review_fetcher import ReviewFetcher
from app.services.scheduler import SchedulerService


def build_application(env_path: Path, config_path: Path) -> ReviewMonitoringApplication:
    settings = load_settings(env_path=env_path, config_path=config_path)
    logger = configure_logging(settings.log_level)
    database = Database(settings.database_path)
    report_builder = ReportBuilder(stars_threshold=settings.report_stars_threshold)
    email_service = EmailService(settings=settings, logger=logger)
    fetcher = ReviewFetcher(settings=settings, logger=logger)
    scheduler = SchedulerService(settings=settings, logger=logger)
    return ReviewMonitoringApplication(
        settings=settings,
        logger=logger,
        database=database,
        review_fetcher=fetcher,
        report_builder=report_builder,
        email_service=email_service,
        scheduler=scheduler,
    )
