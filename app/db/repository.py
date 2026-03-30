from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.models import PlatformSnapshot, PlatformStatus
from app.db.database import Database


@dataclass(slots=True)
class PreviousSnapshot:
    review_count: int | None
    rating: float | None
    signatures: set[str]


class MonitoringRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_run(self, started_at: datetime) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO monitoring_runs(started_at, status) VALUES (?, ?)",
                (started_at.isoformat(), "running"),
            )
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, finished_at: datetime, status: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE monitoring_runs SET finished_at = ?, status = ? WHERE id = ?",
                (finished_at.isoformat(), status, run_id),
            )

    def get_previous_snapshot(self, point_id: str, platform: str) -> PreviousSnapshot | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, review_count, rating
                FROM platform_snapshots
                WHERE point_id = ? AND platform = ? AND status = ?
                ORDER BY collected_at DESC, id DESC
                LIMIT 1
                """,
                (point_id, platform, PlatformStatus.SUCCESS.value),
            ).fetchone()
            if row is None:
                return None

            signatures = {
                item["signature"]
                for item in connection.execute(
                    "SELECT signature FROM reviews WHERE snapshot_id = ?",
                    (row["id"],),
                ).fetchall()
            }
            return PreviousSnapshot(
                review_count=row["review_count"],
                rating=row["rating"],
                signatures=signatures,
            )

    def save_snapshot(self, run_id: int, snapshot: PlatformSnapshot) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO platform_snapshots(
                    run_id, point_id, platform, source_url, collected_at,
                    review_count, rating, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    snapshot.point_id,
                    snapshot.platform.value,
                    snapshot.source_url,
                    snapshot.collected_at.isoformat(),
                    snapshot.review_count,
                    snapshot.rating,
                    snapshot.status.value,
                    snapshot.error_message,
                ),
            )
            snapshot_id = int(cursor.lastrowid)
            for review in snapshot.reviews:
                connection.execute(
                    """
                    INSERT INTO reviews(
                        snapshot_id, point_id, platform, external_id, signature,
                        published_at, stars, text, source_url, author_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        snapshot.point_id,
                        snapshot.platform.value,
                        review.external_id,
                        review.signature,
                        review.published_at,
                        review.stars,
                        review.text,
                        review.source_url,
                        review.author_name,
                    ),
                )
            return snapshot_id
