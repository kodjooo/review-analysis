from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.adapters.anti_bot import PageExpectation
from app.adapters.base import BaseReviewAdapter, ReviewSortConfig
from app.adapters.html_extractors import extract_json_candidates, find_aggregate_rating, flatten_reviews
from app.core.config import Settings
from app.core.models import PlatformName


class TwoGisAdapter(BaseReviewAdapter):
    UNKNOWN_AUTHOR = "Имя не определено"
    platform_url_field = "twogis_url"
    page_expectation = PageExpectation(
        target_selectors=[
            "title",
            "h1",
            "[class*='CardHeader']",
            "[class*='Reviews']",
        ],
        anti_bot_selectors=[
            "form[action*='captcha']",
            "iframe[src*='captcha']",
            "input[name='captcha']",
        ],
        anti_bot_text_markers=[
            "докажите, что вы не робот",
            "verify you are human",
            "подтвердите, что запросы отправляли вы",
        ],
    )

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings=settings, platform=PlatformName.TWOGIS)

    @property
    def review_sort_config(self) -> ReviewSortConfig:
        return ReviewSortConfig(
            trigger_selectors=[
                "div._8pvyfb",
                "div._jyy5a0",
                "[data-testid*='sort']",
                "[class*='reviewsSort']",
            ],
            trigger_texts=[
                "По умолчанию",
                "По доверию",
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
        soup = BeautifulSoup(html, "html.parser")
        meta_description = self._meta_description(soup)
        review_count = self._extract_integer(
            soup.select_one("[data-review-count]"),
            soup.select_one("a[href*='/tab/reviews'] [class*='count']"),
            soup.select_one("a[href*='/tab/reviews'] span:last-child"),
            soup.select_one("[class*=ReviewsPageHeader]"),
            soup.select_one("[class*=Reviews]"),
        )
        rating = self._extract_float(
            soup.select_one("[data-rating]"),
            soup.select_one("._1tam240"),
            soup.select_one("._y10azs"),
            soup.select_one("[class*=RatingValue]"),
        )
        reviews = self._fetch_reviews_from_api(html=html, source_url=source_url)

        if review_count is None:
            review_count = self._extract_count_from_text(meta_description)
        if review_count is None:
            review_count = self._extract_count_from_text(soup.get_text(" ", strip=True))
        if rating is None:
            rating = self._extract_rating_from_text(meta_description)
        if rating is None:
            rating = self._extract_rating_from_text(soup.get_text(" ", strip=True))
        if not reviews:
            for candidate in extract_json_candidates(html):
                candidate_review_count, candidate_rating = find_aggregate_rating(candidate)
                candidate_reviews = flatten_reviews(candidate)
                if candidate_review_count is not None and review_count is None:
                    review_count = candidate_review_count
                if candidate_rating is not None and rating is None:
                    rating = candidate_rating
                if candidate_reviews:
                    reviews = [self._normalize_review(item) for item in candidate_reviews]
                    break
        if not reviews:
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

    def _fetch_reviews_from_api(self, html: str, source_url: str | None) -> list[dict[str, Any]]:
        branch_id = self._extract_branch_id(html=html, source_url=source_url)
        api_key = self._extract_review_api_key(html)
        if not branch_id or not api_key:
            return []

        params = {
            "limit": str(self.settings.review_fetch_limit),
            "sort_by": "date_created",
            "locale": "ru_RU",
            "key": api_key,
        }
        if self.settings.review_sort_order == "oldest":
            params["sort_order"] = "asc"

        request = Request(
            (
                f"https://public-api.reviews.2gis.com/3.0/branches/{branch_id}/reviews?"
                f"{urlencode(params)}"
            ),
            headers={"User-Agent": self._api_user_agent()},
        )
        with urlopen(request, timeout=self.settings.page_timeout_seconds) as response:
            payload = response.read().decode("utf-8")

        for candidate in extract_json_candidates(payload):
            if isinstance(candidate, dict) and isinstance(candidate.get("reviews"), list):
                return [self._normalize_api_review(item) for item in candidate["reviews"]]
        return []

    @staticmethod
    def _extract_review_api_key(html: str) -> str | None:
        match = re.search(r'"reviewApiKey":"([^"]+)"', html)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_branch_id(html: str, source_url: str | None) -> str | None:
        for candidate in (source_url or "", html):
            match = re.search(r"/firm/(\d+)", candidate)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _normalize_api_review(item: dict[str, Any]) -> dict[str, Any]:
        user = item.get("user", {})
        return {
            "external_id": str(item.get("id") or "").strip() or None,
            "author_name": str(user.get("name") or "").strip() or TwoGisAdapter.UNKNOWN_AUTHOR,
            "published_at": str(item.get("date_created") or "").strip(),
            "text": str(item.get("text") or "").strip(),
            "source_url": str(item.get("url") or "").strip() or None,
            "stars": int(float(item.get("rating") or 0)),
        }

    @staticmethod
    def _api_user_agent() -> str:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @staticmethod
    def _meta_description(soup: BeautifulSoup) -> str:
        node = soup.find("meta", attrs={"name": "description"})
        if node is None:
            return ""
        return str(node.get("content") or "")

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

    @staticmethod
    def _extract_count_from_text(text: str) -> int | None:
        match = re.search(r"(\d+)\s+отзыв", text.lower())
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_rating_from_text(text: str) -> float | None:
        match = re.search(r"рейтинг[^0-9]*(\d+(?:[.,]\d+)?)", text.lower())
        if match:
            return float(match.group(1).replace(",", "."))
        match = re.search(r"(\d+[.,]\d+)\s+из\s+5", text.lower())
        if match:
            return float(match.group(1).replace(",", "."))
        return None
