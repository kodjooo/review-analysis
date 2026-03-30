from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup


def extract_json_candidates(html: str) -> list[Any]:
    candidates: list[Any] = []
    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.get_text(strip=True)
        if not text:
            continue
        try:
            candidates.append(json.loads(text))
        except json.JSONDecodeError:
            continue

    for match in re.findall(r"<script[^>]*>(\s*[\[{].*?[\]}]\s*)</script>", html, re.DOTALL):
        snippet = match.strip()
        if "\"reviewCount\"" not in snippet and "\"ratingValue\"" not in snippet and "\"review\"" not in snippet:
            continue
        try:
            candidates.append(json.loads(snippet))
        except json.JSONDecodeError:
            continue

    return candidates


def flatten_reviews(candidate: Any) -> list[dict[str, Any]]:
    if isinstance(candidate, dict):
        reviews = candidate.get("review")
        if isinstance(reviews, list):
            return [item for item in reviews if isinstance(item, dict)]
        for value in candidate.values():
            nested = flatten_reviews(value)
            if nested:
                return nested
    if isinstance(candidate, list):
        for item in candidate:
            nested = flatten_reviews(item)
            if nested:
                return nested
    return []


def find_aggregate_rating(candidate: Any) -> tuple[int | None, float | None]:
    if isinstance(candidate, dict):
        aggregate = candidate.get("aggregateRating")
        if isinstance(aggregate, dict):
            review_count = aggregate.get("reviewCount") or aggregate.get("ratingCount")
            rating_value = aggregate.get("ratingValue")
            try:
                return (
                    int(float(review_count)) if review_count is not None else None,
                    float(rating_value) if rating_value is not None else None,
                )
            except (TypeError, ValueError):
                return None, None
        for value in candidate.values():
            found = find_aggregate_rating(value)
            if found != (None, None):
                return found
    if isinstance(candidate, list):
        for item in candidate:
            found = find_aggregate_rating(item)
            if found != (None, None):
                return found
    return None, None
