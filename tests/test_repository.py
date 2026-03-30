from datetime import datetime
from pathlib import Path

from app.core.models import PlatformName, PlatformSnapshot, Review
from app.core.utils import make_review_signature
from app.db.database import Database
from app.db.repository import MonitoringRepository


def test_repository_saves_and_loads_previous_snapshot(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    repository = MonitoringRepository(database)

    run_id = repository.create_run(datetime(2026, 3, 30, 9, 0, 0))
    review = Review(
        platform=PlatformName.YANDEX,
        published_at="2026-03-30",
        stars=5,
        text="Хорошо",
        source_url="https://example.com/review/1",
        author_name="Иван",
    )
    review.signature = make_review_signature(review)
    snapshot = PlatformSnapshot(
        point_id="point-1",
        platform=PlatformName.YANDEX,
        source_url="https://example.com/yandex",
        collected_at=datetime(2026, 3, 30, 9, 0, 0),
        review_count=15,
        rating=4.8,
        reviews=[review],
    )

    repository.save_snapshot(run_id, snapshot)
    previous = repository.get_previous_snapshot("point-1", PlatformName.YANDEX.value)

    assert previous is not None
    assert previous.review_count == 15
    assert review.signature in previous.signatures
