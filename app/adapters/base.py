from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.core.config import Settings
from app.core.models import MonitoringPoint, PlatformName, PlatformSnapshot, Review
from app.core.utils import make_review_signature


class BaseReviewAdapter(ABC):
    def __init__(self, settings: Settings, platform: PlatformName) -> None:
        self.settings = settings
        self.platform = platform

    @property
    @abstractmethod
    def platform_url_field(self) -> str:
        raise NotImplementedError

    def fetch(self, point: MonitoringPoint) -> PlatformSnapshot:
        source_url = getattr(point, self.platform_url_field)
        html = self._load_html(source_url)
        review_count, rating, raw_reviews = self.parse_html(html)
        reviews = [self._build_review(source_url, item) for item in raw_reviews]
        return PlatformSnapshot(
            point_id=point.id,
            platform=self.platform,
            source_url=source_url,
            collected_at=datetime.now(tz=self.settings.timezone),
            review_count=review_count,
            rating=rating,
            reviews=reviews[: self.settings.review_fetch_limit],
        )

    def _load_html(self, source_url: str) -> str:
        if source_url.startswith("file://"):
            return Path(source_url.replace("file://", "", 1)).read_text(encoding="utf-8")

        last_error: Exception | None = None
        for _ in range(2):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(
                        source_url,
                        wait_until="networkidle",
                        timeout=self.settings.page_timeout_seconds * 1000,
                    )
                    return page.content()
                except PlaywrightTimeoutError as error:
                    last_error = RuntimeError(f"Истек таймаут открытия страницы: {source_url}")
                except Exception as error:  # noqa: BLE001
                    last_error = error
                finally:
                    browser.close()
        if last_error is None:
            raise RuntimeError(f"Не удалось открыть страницу: {source_url}")
        raise last_error

    def _build_review(self, source_url: str, item: dict[str, Any]) -> Review:
        review = Review(
            platform=self.platform,
            published_at=str(item.get("published_at", "")).strip(),
            stars=int(item.get("stars", 0)),
            text=str(item.get("text", "")).strip(),
            source_url=str(item.get("source_url") or source_url),
            author_name=self._none_if_empty(item.get("author_name")),
            external_id=self._none_if_empty(item.get("external_id")),
        )
        review.signature = make_review_signature(review)
        return review

    @staticmethod
    def _none_if_empty(value: object) -> str | None:
        if value is None:
            return None
        value_str = str(value).strip()
        return value_str or None

    @abstractmethod
    def parse_html(self, html: str) -> tuple[int, float, list[dict[str, Any]]]:
        raise NotImplementedError
