from __future__ import annotations

from datetime import datetime
from logging import Logger

from app.adapters.twogis import TwoGisAdapter
from app.adapters.yandex import YandexAdapter
from app.core.config import Settings
from app.core.models import MonitoringPoint, PlatformName, PlatformSnapshot, PlatformStatus


class ReviewFetcher:
    def __init__(self, settings: Settings, logger: Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.adapters = {
            PlatformName.YANDEX: YandexAdapter(settings=settings),
            PlatformName.TWOGIS: TwoGisAdapter(settings=settings),
        }

    def fetch_point_reviews(
        self,
        point: MonitoringPoint,
        platform: PlatformName,
    ) -> PlatformSnapshot:
        adapter = self.adapters[platform]
        source_url = point.yandex_url if platform == PlatformName.YANDEX else point.twogis_url
        try:
            self.logger.info("Сбор данных %s для точки %s.", platform.value, point.id)
            return adapter.fetch(point)
        except Exception as error:
            self.logger.exception(
                "Ошибка сбора данных %s для точки %s: %s",
                platform.value,
                point.id,
                error,
            )
            return PlatformSnapshot(
                point_id=point.id,
                platform=platform,
                source_url=source_url,
                collected_at=datetime.now(tz=self.settings.timezone),
                review_count=0,
                rating=0.0,
                reviews=[],
                status=PlatformStatus.ERROR,
                error_message=str(error),
            )
