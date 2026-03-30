from datetime import datetime

from app.core.models import PlatformName, PlatformSnapshot, Review
from app.core.utils import make_review_signature
from app.db.repository import PreviousSnapshot
from app.services.comparison import SnapshotComparisonService


def test_comparison_detects_new_and_low_rated_reviews() -> None:
    old_review = Review(
        platform=PlatformName.YANDEX,
        published_at="2026-03-29",
        stars=5,
        text="Старый отзыв",
        source_url="https://example.com/1",
        author_name="Иван",
    )
    old_review.signature = make_review_signature(old_review)

    new_review = Review(
        platform=PlatformName.YANDEX,
        published_at="2026-03-30",
        stars=3,
        text="Новый отзыв",
        source_url="https://example.com/2",
        author_name="Олег",
    )
    new_review.signature = make_review_signature(new_review)

    snapshot = PlatformSnapshot(
        point_id="point-1",
        platform=PlatformName.YANDEX,
        source_url="https://example.com",
        collected_at=datetime.now(),
        review_count=10,
        rating=4.2,
        reviews=[old_review, new_review],
    )
    previous = PreviousSnapshot(review_count=9, rating=4.5, signatures={old_review.signature})

    delta = SnapshotComparisonService(stars_threshold=4).compare(snapshot, previous)

    assert delta.previous_review_count == 9
    assert delta.current_review_count == 10
    assert len(delta.new_reviews) == 1
    assert len(delta.low_rated_new_reviews) == 1
