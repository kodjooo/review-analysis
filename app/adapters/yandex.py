from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from app.adapters.anti_bot import PageExpectation
from app.adapters.base import BaseReviewAdapter, ReviewSortConfig
from app.adapters.html_extractors import extract_json_candidates, find_aggregate_rating, flatten_reviews
from app.core.config import Settings
from app.core.models import PlatformName


class YandexAdapter(BaseReviewAdapter):
    platform_url_field = "yandex_url"
    page_expectation = PageExpectation(
        target_selectors=[
            "[class*='business-reviews-card-view']",
            "[class*='business-rating-badge-view']",
            "[class*='business-review-view']",
            "[itemprop='aggregateRating']",
        ],
        anti_bot_selectors=[
            "form[action*='showcaptcha']",
            "form[action*='checkcaptcha']",
            "#checkbox-captcha-form",
            "[data-testid='checkbox-captcha']",
            "input[name='rep']",
            "[class*='Captcha']",
        ],
        anti_bot_text_markers=[
            "докажите, что вы не робот",
            "подтвердите, что запросы отправляли вы, а не робот",
            "я не робот",
            "showcaptcha",
            "verify you are human",
        ],
    )

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings=settings, platform=PlatformName.YANDEX)

    @property
    def review_sort_config(self) -> ReviewSortConfig:
        return ReviewSortConfig(
            trigger_selectors=[
                ".business-reviews-card-view__ranking",
                ".business-reviews-card-view__ranking [role='button'][aria-haspopup='true']",
                "[class*='business-reviews-card-view__ranking']",
            ],
            trigger_texts=[
                "По умолчанию",
                "По новизне",
            ],
            option_selectors={
                "newest": [
                    "[role='menuitem']:has-text('По новизне')",
                    "[role='option']:has-text('По новизне')",
                ],
                "oldest": [],
            },
            option_texts={
                "newest": ["По новизне"],
                "oldest": [],
            },
            selected_state_texts={
                "newest": ["По новизне"],
                "oldest": [],
            },
        )

    def parse_html(
        self,
        html: str,
        source_url: str | None = None,
    ) -> tuple[int, float, list[dict[str, Any]]]:
        for candidate in extract_json_candidates(html):
            review_count, rating = find_aggregate_rating(candidate)
            reviews = flatten_reviews(candidate)
            if review_count is not None and rating is not None and reviews:
                return review_count, rating, [self._normalize_review(item) for item in reviews]

        embedded_review_count, embedded_rating = self._extract_rating_data(html)
        embedded_params_count = self._extract_embedded_params_count(html)

        soup = BeautifulSoup(html, "html.parser")
        dom_review_count = self._extract_integer(
            soup.select_one("[data-review-count]"),
            soup.select_one(".business-reviews-card-view__header .card-section-header__title_wide"),
            soup.select_one(".business-tab_type_reviews"),
            soup.select_one(".business-tab_type_reviews .business-tab__count"),
            soup.select_one("[class*=business-reviews-card-view__review-count]"),
            soup.select_one("[class*=card-section-header__title-count]"),
        )
        review_count = embedded_review_count or embedded_params_count or dom_review_count
        rating = embedded_rating or self._extract_float(
            soup.select_one("[data-rating]"),
            soup.select_one(".business-rating-badge-view__rating-text"),
            soup.select_one("[class*=business-rating-badge-view__rating-text]"),
            soup.select_one("[class*=business-summary-rating-badge-view__rating]"),
        )

        review_nodes = soup.select("[data-review-id]")
        if not review_nodes:
            review_nodes = soup.select("[class*=business-review-view]")

        reviews = []
        for node in review_nodes:
            reviews.append(
                {
                    "external_id": node.get("data-review-id") or node.get("id"),
                    "author_name": self._text(
                        node.select_one("[class*=review-author]")
                        or node.select_one("[class*=business-review-view__author]")
                        or node.select_one("[class*=business-review-view__author-name]")
                    ),
                    "published_at": self._text(node.select_one("time")),
                    "text": self._text(
                        node.select_one("[class*=review-comment]")
                        or node.select_one("[class*=business-review-view__body-text]")
                        or node.select_one("[class*=business-review-view__comment]")
                    ),
                    "source_url": node.get("data-review-url") or self._extract_review_url(node),
                    "stars": self._extract_stars(node),
                }
            )

        if review_count is None or rating is None:
            text_blob = soup.get_text(" ", strip=True)
            review_count = review_count or self._extract_count_from_text(text_blob)
            rating = rating or self._extract_rating_from_text(text_blob)
        if not reviews:
            reviews = self._extract_embedded_reviews(html)
        reviews = self._sort_reviews(reviews)

        if review_count is None or rating is None:
            raise ValueError("Не удалось извлечь рейтинг или количество отзывов из Яндекс.")
        return review_count, rating, reviews

    def _normalize_review(self, item: dict[str, Any]) -> dict[str, Any]:
        rating = item.get("reviewRating", {})
        return {
            "external_id": item.get("@id") or item.get("identifier"),
            "author_name": self._coalesce(item.get("author"), "name"),
            "published_at": item.get("datePublished", ""),
            "text": item.get("reviewBody", ""),
            "source_url": item.get("url"),
            "stars": int(float(rating.get("ratingValue", 0))) if isinstance(rating, dict) else 0,
        }

    @staticmethod
    def _coalesce(value: Any, key: str) -> str | None:
        if isinstance(value, dict):
            nested = value.get(key)
            return str(nested) if nested else None
        return None

    def _extract_embedded_reviews(self, html: str) -> list[dict[str, Any]]:
        match = re.search(r'"reviews":\s*(\[.*?\])\s*,\s*"params":\s*\{', html, flags=re.DOTALL)
        if not match:
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []
        return [self._normalize_embedded_review(item) for item in payload if isinstance(item, dict)]

    @staticmethod
    def _extract_rating_data(html: str) -> tuple[int | None, float | None]:
        match = re.search(
            r'"ratingData":\{"ratingCount":\d+,"ratingValue":(\d+(?:\.\d+)?),"reviewCount":(\d+)\}',
            html,
        )
        if not match:
            return None, None
        rating = float(match.group(1))
        review_count = int(match.group(2))
        return review_count, rating

    @staticmethod
    def _extract_embedded_params_count(html: str) -> int | None:
        match = re.search(r'"params":\{"offset":\d+,"limit":\d+,"count":(\d+)', html)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _normalize_embedded_review(item: dict[str, Any]) -> dict[str, Any]:
        author = item.get("author", {})
        return {
            "external_id": item.get("reviewId"),
            "author_name": YandexAdapter._coalesce(author, "name"),
            "published_at": str(item.get("updatedTime") or "").strip(),
            "text": str(item.get("text") or "").strip(),
            "source_url": None,
            "stars": int(float(item.get("rating") or 0)),
        }

    def _sort_reviews(self, reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
        reverse = self.settings.review_sort_order != "oldest"
        return sorted(reviews, key=self._review_sort_key, reverse=reverse)

    @staticmethod
    def _review_sort_key(item: dict[str, Any]) -> tuple[int, str]:
        raw_value = str(item.get("published_at") or "").strip()
        if not raw_value:
            return (0, "")
        normalized = raw_value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            return (1, parsed.isoformat())
        except ValueError:
            return (0, raw_value)

    @staticmethod
    def _text(node: Any) -> str:
        if node is None:
            return ""
        return node.get_text(" ", strip=True)

    @staticmethod
    def _extract_integer(*nodes: Any) -> int | None:
        for node in nodes:
            if node is None:
                continue
            value = "".join(ch for ch in node.get_text(" ", strip=True) if ch.isdigit())
            if value:
                return int(value)
        return None

    @staticmethod
    def _extract_float(*nodes: Any) -> float | None:
        for node in nodes:
            if node is None:
                continue
            text = node.get("data-rating") if hasattr(node, "get") else None
            text = text or node.get_text(" ", strip=True)
            normalized = text.replace(",", ".")
            match = re.search(r"\d+(?:\.\d+)?", normalized)
            if match:
                return float(match.group(0))
        return None

    @staticmethod
    def _extract_stars(node: Any) -> int:
        value = node.get("data-review-rating")
        if value:
            return int(float(value))
        return len(node.select("[class*=star]"))

    @staticmethod
    def _extract_review_url(node: Any) -> str | None:
        anchor = node.select_one("a[href*='reviews']")
        if anchor is None:
            return None
        return anchor.get("href")

    @staticmethod
    def _extract_count_from_text(text: str) -> int | None:
        match = re.search(r"(\d+)\s+отзыв", text.lower())
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_rating_from_text(text: str) -> float | None:
        match = re.search(r"рейтинг[^0-9]*(\d+[.,]\d+)", text.lower())
        if match:
            return float(match.group(1).replace(",", "."))
        return None
