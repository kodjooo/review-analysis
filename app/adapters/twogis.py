from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from app.adapters.base import BaseReviewAdapter
from app.adapters.html_extractors import extract_json_candidates, find_aggregate_rating, flatten_reviews
from app.core.config import Settings
from app.core.models import PlatformName


class TwoGisAdapter(BaseReviewAdapter):
    platform_url_field = "twogis_url"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings=settings, platform=PlatformName.TWOGIS)

    def parse_html(self, html: str) -> tuple[int, float, list[dict[str, Any]]]:
        for candidate in extract_json_candidates(html):
            review_count, rating = find_aggregate_rating(candidate)
            reviews = flatten_reviews(candidate)
            if review_count is not None and rating is not None and reviews:
                return review_count, rating, [self._normalize_review(item) for item in reviews]

        soup = BeautifulSoup(html, "html.parser")
        review_count = self._extract_integer(
            soup.select_one("[data-review-count]"),
            soup.select_one("[class*=ReviewsPageHeader]"),
        )
        rating = self._extract_float(
            soup.select_one("[data-rating]"),
            soup.select_one("[class*=RatingValue]"),
        )
        reviews = []
        for node in soup.select("[data-review-id]"):
            reviews.append(
                {
                    "external_id": node.get("data-review-id"),
                    "author_name": self._text(node.select_one("[class*=Name]")),
                    "published_at": self._text(node.select_one("time")),
                    "text": self._text(node.select_one("[class*=Comment]")),
                    "source_url": node.get("data-review-url"),
                    "stars": self._extract_stars(node),
                }
            )
        if review_count is None or rating is None:
            raise ValueError("Не удалось извлечь рейтинг или количество отзывов из 2ГИС.")
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
            number = "".join(ch for ch in normalized if ch.isdigit() or ch == ".")
            if number:
                return float(number)
        return None

    @staticmethod
    def _extract_stars(node: Any) -> int:
        value = node.get("data-review-rating")
        if value:
            return int(float(value))
        return len(node.select("[class*=star]"))
