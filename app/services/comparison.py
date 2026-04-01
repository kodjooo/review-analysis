from __future__ import annotations

from app.core.models import PlatformDelta, PlatformSnapshot, PlatformStatus
from app.db.repository import PreviousSnapshot


class SnapshotComparisonService:
    def __init__(self, stars_threshold: int) -> None:
        self.stars_threshold = stars_threshold

    def compare(
        self,
        snapshot: PlatformSnapshot,
        previous: PreviousSnapshot | None,
    ) -> PlatformDelta:
        if snapshot.status == PlatformStatus.ERROR:
            return PlatformDelta(
                point_id=snapshot.point_id,
                platform=snapshot.platform,
                previous_review_count=previous.review_count if previous else None,
                current_review_count=None,
                previous_rating=previous.rating if previous else None,
                current_rating=None,
                last_updated_at=None,
                status=PlatformStatus.ERROR,
                error_message=snapshot.error_message,
            )

        previous_signatures = previous.signatures if previous else set()
        new_reviews = [
            review
            for review in snapshot.reviews
            if review.signature and review.signature not in previous_signatures
        ]
        low_rated_new_reviews = [
            review for review in new_reviews if review.stars <= self.stars_threshold
        ]

        return PlatformDelta(
            point_id=snapshot.point_id,
            platform=snapshot.platform,
            previous_review_count=previous.review_count if previous else None,
            current_review_count=snapshot.review_count,
            previous_rating=previous.rating if previous else None,
            current_rating=snapshot.rating,
            last_updated_at=snapshot.collected_at.strftime("%Y-%m-%d %H:%M:%S"),
            new_reviews=new_reviews,
            low_rated_new_reviews=low_rated_new_reviews,
            status=PlatformStatus.SUCCESS,
        )
