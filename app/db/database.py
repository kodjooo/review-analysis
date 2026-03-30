from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS monitoring_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS platform_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    point_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    review_count INTEGER,
                    rating REAL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    FOREIGN KEY(run_id) REFERENCES monitoring_runs(id)
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL,
                    point_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    external_id TEXT,
                    signature TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    stars INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    author_name TEXT,
                    FOREIGN KEY(snapshot_id) REFERENCES platform_snapshots(id)
                );

                CREATE INDEX IF NOT EXISTS idx_platform_snapshots_point_platform
                ON platform_snapshots(point_id, platform, collected_at DESC);

                CREATE INDEX IF NOT EXISTS idx_reviews_signature
                ON reviews(point_id, platform, signature);
                """
            )
