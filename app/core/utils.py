from __future__ import annotations

import hashlib

from app.core.models import Review


def make_review_signature(review: Review) -> str:
    source = "|".join(
        [
            review.platform.value,
            review.external_id or "",
            review.published_at.strip(),
            str(review.stars),
            (review.text or "").strip(),
            (review.author_name or "").strip(),
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
